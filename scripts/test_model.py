"""test_model.py — unit tests for model.py (the 4-channel latent-quality model).

Mirrors the Phase-1 test style: stdlib unittest, lazy importlib module load,
inline fixtures, source-level guards. The PURE functions (prepare_model_data,
summarize_posterior) are testable WITHOUT PyMC; build_model / fit tests are
guarded with @unittest.skipUnless(PyMC importable) and the slow smoke fit is
gated behind RUN_SLOW_FIT so default CI runs without sampling.

Booking fixtures use the POST-Task-1 schema (note+deposit present).

Python: pure tests need numpy; PyMC tests need the uv 3.12 venv.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _import_model():
    spec = importlib.util.spec_from_file_location("model", _SCRIPTS_DIR / "model.py")
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec so @dataclass field-type resolution
    # (which looks up cls.__module__ in sys.modules) works under importlib load.
    sys.modules["model"] = mod
    spec.loader.exec_module(mod)
    return mod


def _pymc_available() -> bool:
    return importlib.util.find_spec("pymc") is not None


# ---------------------------------------------------------------------------
# Fixtures — small multi-cuisine corpus + reviews + booking (post-Task-1 schema)
# ---------------------------------------------------------------------------

def _fixture_corpus():
    # 12 venues across 2 cuisines (>=5 per bucket for the tau neck).
    rows = []
    for i in range(6):
        rows.append({"venue": f"Nordic{i}", "slug": f"nordic-{i}",
                     "cuisine": "New Nordic", "prestige_score": (i % 4)})
    for i in range(6):
        rows.append({"venue": f"Asian{i}", "slug": f"asian-{i}",
                     "cuisine": "Asian", "prestige_score": (i % 3)})
    # bump a couple of prestige scores ABOVE s_sources to exercise the clamp
    rows[0]["prestige_score"] = 99
    return rows


def _fixture_reviews(corpus, skipped=False):
    out = []
    for j, r in enumerate(corpus):
        if skipped:
            out.append({"slug": r["slug"], "rating": None,
                        "review_count": None, "log_count_z": None})
        else:
            out.append({"slug": r["slug"], "rating": 4.0 + (j % 5) * 0.1,
                        "review_count": 100 + j * 50, "log_count_z": (j - 5) * 0.2})
    return out


def _fixture_booking(corpus):
    """Build booking records via the real classify so the schema is authentic."""
    booking_mod = importlib.util.spec_from_file_location("booking", _SCRIPTS_DIR / "booking.py")
    bk = importlib.util.module_from_spec(booking_mod)
    booking_mod.loader.exec_module(bk)
    cfg = {"booking_platforms": {
        "online_engines": ["sevenrooms", "eatigo", "tablecheck", "tock"],
        "readable_engines": ["sevenrooms", "eatigo"],
    }}

    def readable_units():
        units = []
        for d in ("2026-06-06", "2026-06-07"):
            units.append({"date": d, "party_size": 2, "status": "available",
                          "slots": [{"time": "18:00", "state": "available"},
                                    {"time": "19:00", "state": "filled"}],
                          "note": ""})
        return units

    recs = []
    for k, r in enumerate(corpus):
        slug = r["slug"]
        if k in (1, 2, 7):                     # readable venues -> fill channel
            rec = bk.classify("sevenrooms", readable_units(), cfg)
        elif k == 3:                           # deposit venue (gated, deposit flag)
            rec = bk.classify("phone", [], cfg, deposit=True)
        elif k == 4:                           # lottery / Tock venue (online engine, level 4)
            rec = bk.classify("tock", [], cfg)
        elif k == 0:                           # online sevenrooms no slots -> blocked path
            rec = bk.classify("tablecheck", [], cfg)
        else:                                  # plain gated phone venue
            rec = bk.classify("phone", [], cfg)
        rec["slug"] = slug
        recs.append(rec)
    return recs


# ---------------------------------------------------------------------------
# 1. prepare_model_data — PURE (numpy only)
# ---------------------------------------------------------------------------

class TestPrepareModelData(unittest.TestCase):
    S_SOURCES = 5

    def setUp(self):
        self.model = _import_model()
        self.corpus = _fixture_corpus()
        self.reviews = _fixture_reviews(self.corpus)
        self.booking = _fixture_booking(self.corpus)

    def _prep(self, reviews=None, channel_status=None):
        return self.model.prepare_model_data(
            self.corpus, reviews if reviews is not None else self.reviews,
            self.booking, s_sources=self.S_SOURCES, channel_status=channel_status,
        )

    def test_returns_arrays_of_venue_length(self):
        md = self._prep()
        self.assertEqual(md.n_venues, len(self.corpus))
        self.assertEqual(len(md.prestige), len(self.corpus))
        self.assertEqual(len(md.gate_lv), len(self.corpus))
        self.assertEqual(len(md.cuisine_idx), len(self.corpus))

    def test_prestige_clamped_to_s_sources(self):
        """prestige_score=99 must clamp to s_sources, NOT a hardcoded 7/15."""
        md = self._prep()
        self.assertEqual(int(md.prestige.max()), self.S_SOURCES)
        self.assertEqual(int(md.prestige[0]), self.S_SOURCES)  # the 99 venue

    def test_s_sources_is_a_parameter(self):
        md7 = self.model.prepare_model_data(
            self.corpus, self.reviews, self.booking, s_sources=7)
        self.assertEqual(md7.s_sources, 7)
        self.assertLessEqual(int(md7.prestige.max()), 7)

    def test_readable_index_excludes_blocked_and_gated(self):
        """MODEL-04: only channel=='readable' AND truthy N_slots venues are readable."""
        md = self._prep()
        # venues 1,2,7 were built readable
        self.assertEqual(sorted(md.readable.tolist()), [1, 2, 7])
        self.assertEqual(len(md.filled), 3)
        self.assertEqual(len(md.N_slots), 3)
        # no readable index points at a gated/blocked venue
        for i in md.readable.tolist():
            self.assertEqual(self.booking[i]["channel"], "readable")

    def test_no_zero_fill_for_missing_channels(self):
        """Missing-channel venues are simply absent — fill arrays only span readable."""
        md = self._prep()
        self.assertEqual(len(md.filled), len(md.readable))
        self.assertEqual(len(md.N_slots), len(md.readable))
        # gated venue (index 5) is not represented in any fill array
        self.assertNotIn(5, md.readable.tolist())

    def test_gate_lv_is_ordinal_not_binary(self):
        """gate_lv from gate_level(engine,note,deposit)[0]: deposit->3, tock->4, online->0."""
        md = self._prep()
        self.assertEqual(int(md.gate_lv[3]), 3, "deposit venue -> level 3")
        self.assertEqual(int(md.gate_lv[4]), 4, "tock lottery venue -> level 4")
        self.assertEqual(int(md.gate_lv[1]), 0, "readable sevenrooms -> level 0")
        # ordinal range exceeds the binary {0,1}
        self.assertGreater(int(md.gate_lv.max()), 1)

    def test_reviews_skipped_drops_channel(self):
        md = self._prep(reviews=_fixture_reviews(self.corpus, skipped=True))
        self.assertTrue(md.reviews_skipped)
        self.assertIsNone(md.rating)
        self.assertIsNone(md.n_rev)
        self.assertIsNone(md.logcount_z)

    def test_reviews_skipped_via_channel_status(self):
        md = self._prep(channel_status={"channel": "reviews", "status": "skipped",
                                         "reason": "no API key"})
        self.assertTrue(md.reviews_skipped)

    def test_reviews_ok_builds_arrays(self):
        md = self._prep()
        self.assertFalse(md.reviews_skipped)
        self.assertEqual(len(md.rating), len(self.corpus))
        self.assertEqual(len(md.logcount_z), len(self.corpus))

    def test_venue_meta_michelin_defaults_none(self):
        """corpus emits no michelin field -> michelin is None (A2)."""
        md = self._prep()
        self.assertEqual(len(md.venue_meta), len(self.corpus))
        for m in md.venue_meta:
            self.assertIsNone(m["michelin"])
            self.assertIn("prestige_score", m)
            self.assertEqual(m["s_sources"], self.S_SOURCES)

    def test_venue_meta_fill_only_for_readable(self):
        md = self._prep()
        for m in md.venue_meta:
            if m["readable"]:
                self.assertIsNotNone(m["fill"])
            else:
                self.assertIsNone(m["fill"])

    def test_coords_dims(self):
        md = self._prep()
        self.assertEqual(len(md.coords["venue"]), len(self.corpus))
        self.assertEqual(len(md.coords["readable"]), len(md.readable))
        self.assertIn("New Nordic", md.coords["cuisine"])


# ---------------------------------------------------------------------------
# 2. build_model — PURE construct (needs PyMC; skipped when absent)
# ---------------------------------------------------------------------------

@unittest.skipUnless(_pymc_available(), "PyMC not installed (needs uv 3.12 venv)")
class TestBuildModel(unittest.TestCase):
    S_SOURCES = 5

    def setUp(self):
        self.model = _import_model()
        corpus = _fixture_corpus()
        self.md = self.model.prepare_model_data(
            corpus, _fixture_reviews(corpus), _fixture_booking(corpus),
            s_sources=self.S_SOURCES)

    def test_returns_pymc_model(self):
        import pymc as pm
        m = self.model.build_model(self.md)
        self.assertIsInstance(m, pm.Model)

    def test_named_rvs_exist(self):
        m = self.model.build_model(self.md)
        names = set(m.named_vars.keys())
        for rv in ("q", "beta_p", "beta_b", "log_cap_r", "tau", "beta_gl"):
            self.assertIn(rv, names, f"missing RV/Deterministic: {rv}")

    def test_readable_dim_matches_readable_count(self):
        m = self.model.build_model(self.md)
        self.assertEqual(len(m.coords["readable"]), len(self.md.readable))
        self.assertEqual(len(m.coords["venue"]), self.md.n_venues)

    def test_reviews_skipped_omits_review_rvs(self):
        corpus = _fixture_corpus()
        md = self.model.prepare_model_data(
            corpus, _fixture_reviews(corpus, skipped=True), _fixture_booking(corpus),
            s_sources=self.S_SOURCES)
        m = self.model.build_model(md)
        names = set(m.named_vars.keys())
        self.assertNotIn("rating_obs", names)
        self.assertNotIn("count_obs", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
