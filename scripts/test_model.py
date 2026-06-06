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


# ---------------------------------------------------------------------------
# 3. summarize_posterior — PURE (mocked InferenceData; needs arviz)
# ---------------------------------------------------------------------------

def _arviz_available() -> bool:
    return importlib.util.find_spec("arviz") is not None


def _mock_idata(q_means, q_sds, beta_b_samples=None, beta_p_samples=None,
                divergences=0, chains=2, draws=200, seed=0):
    """Build a small arviz DataTree with a known posterior q + betas + diverging.

    Uses the arviz 1.x from_dict signature: raw arrays + a `dims` map.
    """
    import numpy as np
    import arviz as az
    rng = np.random.default_rng(seed)
    nv = len(q_means)
    q = np.stack([
        np.stack([rng.normal(q_means[v], q_sds[v], draws) for v in range(nv)], axis=1)
        for _ in range(chains)
    ])  # (chains, draws, venue)
    if beta_b_samples is None:
        beta_b_samples = rng.normal(1.4, 0.5, (chains, draws))
    if beta_p_samples is None:
        beta_p_samples = rng.normal(0.75, 0.2, (chains, draws))
    posterior = {
        "q": q,
        "beta_b": beta_b_samples,
        "beta_p": beta_p_samples,
        "tau": np.abs(rng.normal(0.3, 0.1, (chains, draws))),
    }
    diverging = (np.arange(chains * draws).reshape(chains, draws) < divergences)
    return az.from_dict(
        {"posterior": posterior, "sample_stats": {"diverging": diverging}},
        dims={"q": ["venue"]},
    )


@unittest.skipUnless(_arviz_available(), "arviz not installed (needs uv 3.12 venv)")
class TestSummarizePosterior(unittest.TestCase):

    def setUp(self):
        self.model = _import_model()

    def _meta(self, n, readable_idx, wide_idx=None):
        meta = []
        for i in range(n):
            is_readable = i in readable_idx
            meta.append({
                "venue": f"V{i}", "slug": f"v-{i}", "cuisine": "Asian",
                "prestige_score": 3, "s_sources": 5, "michelin": None,
                "rating": 4.5, "n_reviews": 200, "gate_lv": 0, "gate_label": "online",
                "readable": is_readable,
                "fill": 0.8 if is_readable else None,
                "N_slots": 100 if is_readable else None,
                "engine": "sevenrooms" if is_readable else None,
                "off_platform": not is_readable,
            })
        return meta

    def test_ranking_sorted_by_q_desc(self):
        idata = _mock_idata([0.5, 2.0, 1.0], [0.3, 0.3, 0.3])
        res = self.model.summarize_posterior(idata, self._meta(3, {0}))
        qs = [r["q"] for r in res.ranking]
        self.assertEqual(qs, sorted(qs, reverse=True))
        self.assertEqual(res.ranking[0]["name"], "V1")  # highest q

    def test_records_carry_hdi(self):
        idata = _mock_idata([1.0, 0.0], [0.5, 0.5])
        res = self.model.summarize_posterior(idata, self._meta(2, {0}))
        for r in res.ranking:
            self.assertIn("hdi_lo", r)
            self.assertIn("hdi_hi", r)
            self.assertLess(r["hdi_lo"], r["hdi_hi"])

    def test_diagnostics_dict(self):
        idata = _mock_idata([1.0, 0.0], [0.4, 0.4], divergences=3)
        res = self.model.summarize_posterior(idata, self._meta(2, {0}))
        self.assertEqual(res.diagnostics["divergences"], 3)
        self.assertIsInstance(res.diagnostics["rhat_max"], float)
        self.assertIsInstance(res.diagnostics["ess_min"], float)

    def test_beta_b_carries_p_gt0_and_hdi(self):
        idata = _mock_idata([1.0, 0.0], [0.4, 0.4])
        res = self.model.summarize_posterior(idata, self._meta(2, {0}))
        self.assertIn("p_gt0", res.beta_b)
        self.assertIn("hdi", res.beta_b)
        self.assertIn("mean", res.beta_b)
        self.assertIn("mean", res.beta_p)
        self.assertIn("hdi", res.beta_p)

    def test_non_readable_has_wider_hdi(self):
        """MODEL-04 honesty: a non-readable venue with wider q spread -> wider HDI."""
        # venue 0 readable (narrow sd), venue 1 non-readable (wide sd)
        idata = _mock_idata([1.0, 1.0], [0.2, 0.9])
        res = self.model.summarize_posterior(idata, self._meta(2, {0}))
        by_name = {r["name"]: r for r in res.ranking}
        readable_w = by_name["V0"]["hdi_hi"] - by_name["V0"]["hdi_lo"]
        nonread_w = by_name["V1"]["hdi_hi"] - by_name["V1"]["hdi_lo"]
        self.assertGreater(nonread_w, readable_w)
        self.assertFalse(by_name["V1"]["readable"])
        self.assertIsNone(by_name["V1"]["fill"])

    def test_channel_coverage(self):
        idata = _mock_idata([1.0, 0.5, 0.0], [0.3, 0.3, 0.3])
        res = self.model.summarize_posterior(idata, self._meta(3, {0, 2}))
        self.assertEqual(res.channel_coverage["readable"], 2)
        self.assertEqual(res.channel_coverage["total"], 3)


# ---------------------------------------------------------------------------
# 4. fit — the sampling seam (monkeypatch for fast; gated smoke fit)
# ---------------------------------------------------------------------------

@unittest.skipUnless(_pymc_available(), "PyMC not installed (needs uv 3.12 venv)")
class TestFitSeam(unittest.TestCase):

    def setUp(self):
        self.model = _import_model()

    def test_fit_wires_args_and_returns_idata(self):
        """Monkeypatch pm.sample to a canned idata -> fit returns it, no real sampling."""
        import pymc as pm
        sentinel = object()
        captured = {}

        def fake_sample(*args, **kwargs):
            captured.update(kwargs)
            return sentinel

        orig = pm.sample
        pm.sample = fake_sample
        try:
            corpus = _fixture_corpus()
            md = self.model.prepare_model_data(
                corpus, _fixture_reviews(corpus), _fixture_booking(corpus), s_sources=5)
            m = self.model.build_model(md)
            out = self.model.fit(m, seed=7, draws=11, tune=13)
        finally:
            pm.sample = orig
        self.assertIs(out, sentinel)
        self.assertEqual(captured["draws"], 11)
        self.assertEqual(captured["tune"], 13)
        self.assertEqual(captured["random_seed"], 7)


@unittest.skipUnless(os.environ.get("RUN_SLOW_FIT"), "RUN_SLOW_FIT not set — slow smoke fit skipped")
class TestSmokeFit(unittest.TestCase):

    def test_tiny_fixed_seed_fit(self):
        import numpy as np
        model = _import_model()
        corpus = _fixture_corpus()
        md = model.prepare_model_data(
            corpus, _fixture_reviews(corpus), _fixture_booking(corpus), s_sources=5)
        m = model.build_model(md)
        import pymc as pm
        with m:
            idata = pm.sample(draws=50, tune=50, chains=1, random_seed=42,
                              progressbar=False)
        q = idata.posterior["q"].values
        self.assertEqual(q.shape, (1, 50, md.n_venues))
        self.assertEqual(int(np.isnan(q).sum()), 0)


# ---------------------------------------------------------------------------
# 5. main S_SOURCES seam — derives S_SOURCES from len(prestige_sources)
# ---------------------------------------------------------------------------

class TestMainSSourcesSeam(unittest.TestCase):

    def setUp(self):
        self.model = _import_model()

    def test_main_derives_s_sources_from_config_and_threads_it(self):
        """main reads S_SOURCES = len(config['prestige_sources']) and passes it to
        prepare_model_data (not a literal 7/15)."""
        corpus = _fixture_corpus()
        reviews = _fixture_reviews(corpus)
        booking = _fixture_booking(corpus)

        captured = {}
        real_prepare = self.model.prepare_model_data

        def spy_prepare(c, r, b, *, s_sources, **kw):
            captured["s_sources"] = s_sources
            return real_prepare(c, r, b, s_sources=s_sources, **kw)

        # stub city config with a KNOWN prestige_sources length (4, not 7/15)
        fake_config = {"city": "Testville", "slug": "testville",
                       "prestige_sources": ["a", "b", "c", "d"]}

        def fake_load_city(name):
            return fake_config

        # build/fit/summarize stubs so no sampling happens
        class _Diag:
            diagnostics = {"divergences": 0}
            channel_coverage = {"readable": 1, "total": len(corpus)}
            def to_dict(self):
                return {"ok": True}

        import json as _json
        import tempfile
        d = tempfile.mkdtemp()
        cp = Path(d) / "c.json"; rp = Path(d) / "r.json"; bp = Path(d) / "b.json"
        cp.write_text(_json.dumps(corpus)); rp.write_text(_json.dumps(reviews))
        bp.write_text(_json.dumps(booking))
        outp = Path(d) / "out.json"

        orig = {
            "prepare_model_data": self.model.prepare_model_data,
            "load_city": self.model.load_city,
            "build_model": self.model.build_model,
            "fit": self.model.fit,
            "summarize_posterior": self.model.summarize_posterior,
        }
        self.model.prepare_model_data = spy_prepare
        self.model.load_city = fake_load_city
        self.model.build_model = lambda md: object()
        self.model.fit = lambda m, **kw: object()
        self.model.summarize_posterior = lambda idata, meta: _Diag()
        try:
            rc = self.model.main([
                "--city", "testville", "--corpus", str(cp),
                "--reviews", str(rp), "--booking", str(bp), "--out", str(outp),
            ])
        finally:
            for k, v in orig.items():
                setattr(self.model, k, v)
        self.assertEqual(rc, 0)
        self.assertEqual(captured["s_sources"], 4,
                         "S_SOURCES must come from len(prestige_sources)=4, not a hardcode")


# ---------------------------------------------------------------------------
# 6. Source guard — MODEL-04 structural honesty + no-hardcode (mirror TestReadOnlyGuard)
# ---------------------------------------------------------------------------

class TestModelSourceGuard(unittest.TestCase):

    def setUp(self):
        self.src = (_SCRIPTS_DIR / "model.py").read_text(encoding="utf-8")

    def test_no_hdi_prob_kwarg(self):
        """arviz 1.x uses prob=, not hdi_prob= (Pitfall 1)."""
        self.assertNotIn("hdi_prob", self.src)

    def test_uses_prob_kwarg(self):
        self.assertIn("prob=0.94", self.src)

    def test_no_zero_fill_or_impute(self):
        """MODEL-04: no missing-channel zero-fill / imputation patterns.

        Note the guard targets imputation CODE patterns, not prose: the module
        docstring legitimately says "never fabricated" (describing the honesty
        rail), so we match concrete fill/impute idioms rather than the bare word.
        """
        for pat in ("fillna(0", "fillna(0.0", "= 0.0  # impute", "impute_zero",
                    "fabricate(", "fabricate_fill"):
            self.assertNotIn(pat, self.src, f"forbidden zero-fill/impute pattern: {pat}")
        # The readable-index restriction is the ONLY fill path (structural honesty).
        self.assertIn('channel") == "readable"', self.src)

    def test_no_hardcoded_s_sources_literal(self):
        """No `S_SOURCES = 7` / `= 15` — the count flows from the city config."""
        import re
        self.assertIsNone(re.search(r"S_SOURCES\s*=\s*(7|15)\b", self.src))
        self.assertIn("len(config", self.src)  # derived from config

    def test_no_hardcoded_absolute_output_path(self):
        """No hardcoded absolute output path; output resolves to CWD."""
        import re
        # crude: no string literal that looks like an absolute *output* path
        self.assertNotIn('open("/', self.src)
        self.assertIn("os.getcwd()", self.src)

    def test_module_parses(self):
        import ast
        ast.parse(self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
