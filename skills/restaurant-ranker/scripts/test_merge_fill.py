"""test_merge_fill.py — unit tests for merge_fill.py (CloakBrowser fill fold-in).

Covers:
  - readable_record_from_clickthrough: fill computed from clickthrough units,
    record carries channel='readable' + source='cloakbrowser'
  - honesty rail (BOOK-03): unresolved / date='*' / closed-only venues produce
    NO record (None) -> caller leaves the blocked-here record untouched
  - merge_clickthrough: blocked-here -> readable upgrade, browser-only insert,
    no-grid skip, idempotency
  - read-only guard: merge_fill.py issues no network / booking-write calls

No live network. All tests feed fixture data directly. Python 3.10 stdlib only.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _import_merge():
    spec = importlib.util.spec_from_file_location(
        "merge_fill", _SCRIPTS_DIR / "merge_fill.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _clickthrough(slug, platform, units, **extra):
    """Build a clickthrough venue dict (booking-probe output shape)."""
    v = {"slug": slug, "platform": platform, "units": units}
    v.update(extra)
    return v


def _unit(date, available, filled=(), status="available", note=""):
    slots = [{"time": t, "meal": "", "state": "available"} for t in available]
    slots += [{"time": t, "meal": "", "state": "filled"} for t in filled]
    return {"date": date, "party_size": 2, "status": status, "slots": slots, "note": note}


# ---------------------------------------------------------------------------
# 1. readable_record_from_clickthrough
# ---------------------------------------------------------------------------

class TestReadableRecord(unittest.TestCase):
    def setUp(self):
        self.m = _import_merge()

    def test_resolved_grid_becomes_readable(self):
        """A venue with offers across dates -> channel='readable', fill computed."""
        venue = _clickthrough("adhoc", "tablecheck", [
            _unit("2026-06-06", ["18:00", "19:00", "20:00"]),
            _unit("2026-06-07", ["18:00"]),  # 2 of the 3-slot grid filled
        ])
        rec = self.m.readable_record_from_clickthrough(venue)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["channel"], "readable")
        self.assertEqual(rec["engine"], "tablecheck")
        self.assertEqual(rec["slug"], "adhoc")
        self.assertEqual(rec["g_i"], 0)
        self.assertFalse(rec["off_platform"])
        self.assertEqual(rec["grid_size"], 3)
        self.assertEqual(rec["N_slots"], 6)
        self.assertEqual(rec["filled"], 2)
        self.assertEqual(rec["source"], "cloakbrowser")

    def test_fill_matches_booking_fill_from_units(self):
        """Fill folds in identically to the HTTP path (same fill_from_units)."""
        import booking
        units = [
            _unit("2026-06-06", ["18:00", "19:00"], ["20:00"]),
        ]
        venue = _clickthrough("x", "opentable", units)
        rec = self.m.readable_record_from_clickthrough(venue)
        bf, bN, bg = booking.fill_from_units(units)
        self.assertEqual((rec["filled"], rec["N_slots"], rec["grid_size"]), (bf, bN, bg))

    def test_unresolved_star_date_returns_none(self):
        """date='*' unresolved unit (e.g. blocked OpenTable) -> None (honesty rail)."""
        venue = _clickthrough("jan", "opentable", [
            {"date": "*", "party_size": 2, "status": "unresolved", "slots": [],
             "note": "curl blocked (HTTP 000 from datacenter IP)"},
        ])
        self.assertIsNone(self.m.readable_record_from_clickthrough(venue))

    def test_closed_only_returns_none(self):
        """All dated units closed/no-slots with empty grid -> None (no observation)."""
        venue = _clickthrough("reale", "sevenrooms", [
            _unit("2026-06-06", [], status="no-slots", note="closed"),
            _unit("2026-06-07", [], status="no-slots", note="closed"),
        ])
        self.assertIsNone(self.m.readable_record_from_clickthrough(venue))

    def test_full_dates_count_as_filled_when_grid_exists(self):
        """A full date (no offers) counts as fully filled against the grid."""
        venue = _clickthrough("busy", "dinnerbooking", [
            _unit("2026-06-06", ["18:00", "19:00"]),
            _unit("2026-06-07", [], status="full"),  # both grid slots filled
        ])
        rec = self.m.readable_record_from_clickthrough(venue)
        self.assertEqual(rec["grid_size"], 2)
        self.assertEqual(rec["N_slots"], 4)
        self.assertEqual(rec["filled"], 2)

    def test_deposit_note_sets_deposit_true(self):
        venue = _clickthrough("goat", "sevenrooms",
                              [_unit("2026-06-06", ["18:00"])],
                              deposit_note="credit-card hold required")
        rec = self.m.readable_record_from_clickthrough(venue)
        self.assertTrue(rec["deposit"])

    def test_no_deposit_note_default_false(self):
        venue = _clickthrough("plain", "sevenrooms", [_unit("2026-06-06", ["18:00"])])
        rec = self.m.readable_record_from_clickthrough(venue)
        self.assertFalse(rec["deposit"])

    def test_negated_deposit_note_is_false(self):
        venue = _clickthrough("free", "sevenrooms",
                              [_unit("2026-06-06", ["18:00"])],
                              deposit_note="no deposit")
        rec = self.m.readable_record_from_clickthrough(venue)
        self.assertFalse(rec["deposit"])


# ---------------------------------------------------------------------------
# 2. merge_clickthrough
# ---------------------------------------------------------------------------

class TestMergeClickthrough(unittest.TestCase):
    def setUp(self):
        self.m = _import_merge()

    def _blocked(self, slug, engine):
        return {"slug": slug, "engine": engine, "channel": "blocked-here",
                "g_i": 0, "filled": None, "N_slots": None, "grid_size": 0,
                "off_platform": False, "note": "", "deposit": False}

    def test_blocked_here_upgraded_to_readable(self):
        records = [self._blocked("adhoc", "tablecheck")]
        ct = [_clickthrough("adhoc", "tablecheck",
                            [_unit("2026-06-06", ["18:00", "19:00"]),
                             _unit("2026-06-07", ["18:00"])])]
        merged, stats = self.m.merge_clickthrough(records, ct)
        self.assertEqual(merged[0]["channel"], "readable")
        self.assertEqual(merged[0]["source"], "cloakbrowser")
        self.assertIsNotNone(merged[0]["filled"])
        self.assertEqual(stats["upgraded"], ["adhoc"])
        self.assertEqual(stats["readable_via_cloakbrowser"], 1)

    def test_unresolved_clickthrough_leaves_blocked_here(self):
        """Honesty rail end-to-end: a blocked read does not fabricate a fill."""
        records = [self._blocked("jan", "opentable")]
        ct = [_clickthrough("jan", "opentable",
                            [{"date": "*", "status": "unresolved", "slots": [], "note": "blocked"}])]
        merged, stats = self.m.merge_clickthrough(records, ct)
        self.assertEqual(merged[0]["channel"], "blocked-here")
        self.assertIsNone(merged[0]["filled"])
        self.assertEqual(stats["skipped_no_grid"], ["jan"])
        self.assertEqual(stats["upgraded"], [])

    def test_browser_only_venue_inserted(self):
        records = []  # venue absent from HTTP probe
        ct = [_clickthrough("superb-venue", "superb",
                            [_unit("2026-06-06", ["18:00", "19:00"])])]
        merged, stats = self.m.merge_clickthrough(records, ct)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["slug"], "superb-venue")
        self.assertEqual(merged[0]["channel"], "readable")
        self.assertEqual(stats["inserted"], ["superb-venue"])

    def test_http_readable_preserved_when_no_clickthrough(self):
        records = [{"slug": "helm", "engine": "sevenrooms", "channel": "readable",
                    "g_i": 0, "filled": 5, "N_slots": 12, "grid_size": 4,
                    "off_platform": False, "note": "", "deposit": False,
                    "source": "http"}]
        merged, stats = self.m.merge_clickthrough(records, [])
        self.assertEqual(merged[0]["filled"], 5)
        self.assertEqual(merged[0]["source"], "http")
        self.assertEqual(stats["readable_after"], 1)

    def test_order_preserved_existing_then_inserted(self):
        records = [self._blocked("a", "tablecheck"), self._blocked("b", "opentable")]
        ct = [_clickthrough("b", "opentable", [_unit("2026-06-06", ["18:00", "19:00"])]),
              _clickthrough("c", "superb", [_unit("2026-06-06", ["20:00", "21:00"])])]
        merged, _ = self.m.merge_clickthrough(records, ct)
        self.assertEqual([r["slug"] for r in merged], ["a", "b", "c"])

    def test_idempotent_rerun(self):
        records = [self._blocked("adhoc", "tablecheck")]
        ct = [_clickthrough("adhoc", "tablecheck",
                            [_unit("2026-06-06", ["18:00", "19:00"]),
                             _unit("2026-06-07", ["18:00"])])]
        once, _ = self.m.merge_clickthrough(records, ct)
        twice, stats2 = self.m.merge_clickthrough(once, ct)
        self.assertEqual(once[0]["filled"], twice[0]["filled"])
        self.assertEqual(stats2["upgraded"], [])  # already readable


# ---------------------------------------------------------------------------
# 3. Read-only guard
# ---------------------------------------------------------------------------

class TestReadOnlyGuard(unittest.TestCase):
    def setUp(self):
        self.src = (_SCRIPTS_DIR / "merge_fill.py").read_text(encoding="utf-8")

    def test_no_network_calls(self):
        for tok in ("urlopen", "urllib.request", "requests.", "http.client"):
            self.assertNotIn(tok, self.src, f"merge_fill must not do network I/O ({tok})")

    def test_no_booking_writes(self):
        for tok in ("confirm_reservation", "create_reservation", "/checkout",
                    "finalize_booking"):
            self.assertNotIn(tok, self.src)

    def test_parses_as_valid_python(self):
        ast.parse(self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
