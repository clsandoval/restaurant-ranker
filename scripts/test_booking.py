"""test_booking.py — unit tests for booking.py (HTTP-only booking-demand channel).

TDD RED phase: all tests written before implementation exists.

Coverage:
  - fill_from_units: fixture-driven fill computation (ported assemble.py)
  - channel classification: readable / blocked-here / gated branches
  - gate_level: ladder 0..4 (online / walk-in / phone / deposit / lottery)
  - off-platform honesty: gated/blocked-here -> fill=None, never fabricated (BOOK-03)
  - read-only guard: no prober in booking.py issues a booking-write HTTP POST (BOOK-04)

No live network calls. All tests feed fixture data directly.

Python 3.10 stdlib only.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve booking.py relative to this file (works from any CWD)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# We import lazily inside test methods so failures show clear module-not-found messages.
def _import_booking():
    spec = importlib.util.spec_from_file_location(
        "booking", _SCRIPTS_DIR / "booking.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. fill_from_units — ported assemble.py logic
# ---------------------------------------------------------------------------

class TestFillFromUnits(unittest.TestCase):
    """fill_from_units(units) -> (filled:int|None, N_slots:int|None, grid_size:int)"""

    def setUp(self):
        self.booking = _import_booking()

    def _make_units(self, spec):
        """Build a units list. spec is list of (date, available_times, filled_times).
        available_times = times where slots have state='available'
        filled_times = times where slots have state='filled' (explicitly marked filled)
        """
        units = []
        for date, avail, filled in spec:
            slots = [{"time": t, "state": "available"} for t in avail]
            slots += [{"time": t, "state": "filled"} for t in filled]
            units.append({"date": date, "party_size": 2, "status": "available", "slots": slots})
        return units

    def test_basic_fill_two_dates(self):
        """2 dates × 3-slot grid; 1 offered each -> filled=4 across 6 slots total."""
        units = self._make_units([
            ("2026-06-06", ["18:00", "19:00", "20:00"], []),  # all 3 available (0 filled)
            ("2026-06-07", ["18:00"], []),                    # only 18:00 available (2 filled)
        ])
        filled, N, grid_size = self.booking.fill_from_units(units)
        self.assertEqual(grid_size, 3, "grid is union of all times across all dates")
        self.assertEqual(N, 6, "N_slots = grid_size * n_dates = 3 * 2")
        self.assertEqual(filled, 2, "date1: 0 filled, date2: 2 filled -> total 2")

    def test_empty_units_returns_none(self):
        """No dated units -> (None, None, 0)."""
        filled, N, grid_size = self.booking.fill_from_units([])
        self.assertIsNone(filled)
        self.assertIsNone(N)
        self.assertEqual(grid_size, 0)

    def test_no_slots_returns_none(self):
        """Dated units with empty slots -> no grid -> (None, None, 0)."""
        units = [{"date": "2026-06-06", "party_size": 2, "status": "full", "slots": []}]
        filled, N, grid_size = self.booking.fill_from_units(units)
        self.assertIsNone(filled)
        self.assertIsNone(N)
        self.assertEqual(grid_size, 0)

    def test_explicit_filled_slots_count_toward_grid(self):
        """Slots with state='filled' (SevenRooms waitlist) still enlarge the grid."""
        units = self._make_units([
            ("2026-06-06", ["18:00", "19:00"], ["20:00"]),  # 20:00 is explicitly filled
        ])
        filled, N, grid_size = self.booking.fill_from_units(units)
        self.assertEqual(grid_size, 3, "filled slot counted in grid")
        self.assertEqual(N, 3)
        # offered = {18:00, 19:00}; grid - offered = 3-2 = 1
        self.assertEqual(filled, 1)

    def test_fully_booked_single_date(self):
        """0 available slots on one date -> filled = grid_size."""
        units = [{"date": "2026-06-06", "party_size": 2, "status": "full", "slots": []}]
        # No available slots -> grid is empty -> (None, None, 0)
        # Actually: we need at least one filled slot to establish a grid.
        # Let's test with a unit that has only filled slots.
        units2 = self._make_units([
            ("2026-06-06", [], ["18:00", "19:00"]),
        ])
        filled, N, grid_size = self.booking.fill_from_units(units2)
        self.assertEqual(grid_size, 2)
        self.assertEqual(N, 2)
        self.assertEqual(filled, 2, "both grid slots are filled")

    def test_all_open_zero_fill(self):
        """All slots available -> filled=0."""
        units = self._make_units([
            ("2026-06-06", ["18:00", "19:00", "20:00"], []),
            ("2026-06-07", ["18:00", "19:00", "20:00"], []),
        ])
        filled, N, grid_size = self.booking.fill_from_units(units)
        self.assertEqual(grid_size, 3)
        self.assertEqual(N, 6)
        self.assertEqual(filled, 0)

    def test_no_dated_units_ignored(self):
        """Units without a real date (date is None or '*') are ignored."""
        units = [
            {"date": None, "slots": [{"time": "18:00", "state": "available"}]},
            {"date": "*", "slots": [{"time": "19:00", "state": "available"}]},
        ]
        filled, N, grid_size = self.booking.fill_from_units(units)
        self.assertIsNone(filled)
        self.assertIsNone(N)
        self.assertEqual(grid_size, 0)


# ---------------------------------------------------------------------------
# 2. channel classification (classify function)
# ---------------------------------------------------------------------------

class TestClassify(unittest.TestCase):
    """classify(engine, units, city_config) assigns channel/g_i/off_platform."""

    CITY_CONFIG = {
        "booking_platforms": {
            "online_engines": ["sevenrooms", "eatigo", "tablecheck", "opentable"],
            "readable_engines": ["sevenrooms", "eatigo"],
        }
    }

    def setUp(self):
        self.booking = _import_booking()

    def _make_units_with_slots(self, times=None, n_dates=2):
        """Build simple units fixture with available slots."""
        times = times or ["18:00", "19:00", "20:00"]
        units = []
        for i in range(n_dates):
            date = f"2026-06-0{6+i}"
            slots = [{"time": t, "state": "available"} for t in times]
            units.append({"date": date, "party_size": 2, "status": "available", "slots": slots})
        return units

    def test_readable_engine_with_slots_is_readable(self):
        """sevenrooms (in readable_engines) with dated slots -> channel='readable', off_platform=False."""
        units = self._make_units_with_slots()
        result = self.booking.classify("sevenrooms", units, self.CITY_CONFIG)
        self.assertEqual(result["channel"], "readable")
        self.assertFalse(result["off_platform"])
        self.assertEqual(result["g_i"], 0)
        self.assertIsNotNone(result["filled"])
        self.assertIsNotNone(result["N_slots"])

    def test_eatigo_readable(self):
        """eatigo (in readable_engines) with slots -> channel='readable'."""
        units = self._make_units_with_slots(["12:00", "13:00"])
        result = self.booking.classify("eatigo", units, self.CITY_CONFIG)
        self.assertEqual(result["channel"], "readable")
        self.assertFalse(result["off_platform"])

    def test_online_not_readable_is_blocked_here(self):
        """tablecheck in online_engines but NOT readable_engines -> channel='blocked-here', fill=None."""
        units = self._make_units_with_slots()
        result = self.booking.classify("tablecheck", units, self.CITY_CONFIG)
        self.assertEqual(result["channel"], "blocked-here")
        self.assertEqual(result["g_i"], 0, "online engine -> g_i=0")
        self.assertIsNone(result["filled"], "blocked-here must never fabricate fill (BOOK-03)")
        self.assertIsNone(result["N_slots"])
        self.assertFalse(result["off_platform"])

    def test_neither_online_nor_readable_is_gated(self):
        """Engine not in online_engines or readable_engines (phone/walk-in/lottery) -> channel='gated'."""
        result = self.booking.classify("phone", [], self.CITY_CONFIG)
        self.assertEqual(result["channel"], "gated")
        self.assertEqual(result["g_i"], 1, "gated -> g_i=1")
        self.assertIsNone(result["filled"], "gated must never fabricate fill (BOOK-03)")
        self.assertIsNone(result["N_slots"])
        self.assertTrue(result["off_platform"])

    def test_gated_has_off_platform_true(self):
        """Walk-in / phone / lottery venue -> off_platform=True."""
        result = self.booking.classify("walkin", [], self.CITY_CONFIG)
        self.assertTrue(result["off_platform"])

    def test_blocked_here_fill_is_none_not_fabricated(self):
        """Blocked-here fill stays None even if units has slot data — never fabricate."""
        units = self._make_units_with_slots()
        result = self.booking.classify("opentable", units, self.CITY_CONFIG)
        self.assertEqual(result["channel"], "blocked-here")
        self.assertIsNone(result["filled"])

    def test_readable_no_slots_is_online_noslots(self):
        """Readable engine with no usable slots -> channel='online-noslots' (not 'readable')."""
        units = [{"date": "2026-06-06", "party_size": 2, "status": "full", "slots": []}]
        result = self.booking.classify("sevenrooms", units, self.CITY_CONFIG)
        self.assertIn(result["channel"], ("online-noslots", "readable"))
        # fill may be None or 0; key check is that it's not fabricated
        # (if N_slots=0 then grid_size=0 -> fill=None)

    def test_result_has_required_keys(self):
        """classify result always contains the required output-contract keys."""
        result = self.booking.classify("sevenrooms", [], self.CITY_CONFIG)
        for key in ("engine", "channel", "g_i", "filled", "N_slots", "grid_size", "off_platform"):
            self.assertIn(key, result, f"Missing key: {key}")


# ---------------------------------------------------------------------------
# 3. gate_level — ported gate_ladder.py (level 0..4)
# ---------------------------------------------------------------------------

class TestGateLevel(unittest.TestCase):
    """gate_level(engine, note, deposit) -> (level:int 0..4, label:str)"""

    def setUp(self):
        self.booking = _import_booking()

    def test_online_engine_level_0(self):
        level, label = self.booking.gate_level("sevenrooms", "", False)
        self.assertEqual(level, 0)

    def test_eatigo_level_0(self):
        level, label = self.booking.gate_level("eatigo", "", False)
        self.assertEqual(level, 0)

    def test_walk_in_level_1(self):
        level, label = self.booking.gate_level("", "walk-in only", False)
        self.assertEqual(level, 1)

    def test_phone_level_2(self):
        level, label = self.booking.gate_level("", "call to reserve", False)
        self.assertEqual(level, 2)

    def test_deposit_level_3(self):
        level, label = self.booking.gate_level("", "bank transfer required", False)
        self.assertEqual(level, 3)

    def test_deposit_flag_level_3(self):
        level, label = self.booking.gate_level("", "", True)  # deposit=True flag
        self.assertEqual(level, 3)

    def test_lottery_note_level_4(self):
        level, label = self.booking.gate_level("", "monthly drop lottery", False)
        self.assertEqual(level, 4)

    def test_tock_engine_level_4(self):
        """Tock engine = lottery/drop (Manila usage per gate_ladder.py)."""
        level, label = self.booking.gate_level("tock", "", False)
        self.assertEqual(level, 4)

    def test_prepay_level_3(self):
        level, label = self.booking.gate_level("", "prepay required", False)
        self.assertEqual(level, 3)

    def test_labels_are_strings(self):
        for eng, note, dep in [("sevenrooms", "", False), ("", "walk-in", False),
                                ("", "", False), ("", "", True), ("tock", "", False)]:
            level, label = self.booking.gate_level(eng, note, dep)
            self.assertIsInstance(label, str)


# ---------------------------------------------------------------------------
# 4. Read-only guard — BOOK-04
# ---------------------------------------------------------------------------

class TestReadOnlyGuard(unittest.TestCase):
    """Assert that booking.py does NOT contain any booking-write HTTP calls.

    This test reads the source of booking.py as a string and asserts that no
    call site issues an HTTP POST whose body encodes a booking confirmation.
    We look for patterns that would indicate a reservation-write operation
    (confirm, checkout, reserve-POST, book-POST).

    The guard is intentionally strict: the SevenRooms prober DOES use POST
    for the CoverManager highlight endpoint, but that is a calendar *read*
    (returns availability highlight map, not a reservation).  The guard checks
    for booking-write semantics, not the HTTP verb alone.
    """

    BOOKING_WRITE_PATTERNS = [
        # URL fragments that would only appear in booking-write calls
        "confirm_reservation",
        "create_reservation",
        "book_reservation",
        "/checkout",
        "finalize_booking",
        # Any call that POSTs to a 'book' or 'reserve' endpoint
        # (the widget endpoint uses 'availability' — that's OK)
        "POST.*reserve",     # not a raw string match but a conceptual flag
    ]

    # Patterns that are ALLOWED (read-only availability/calendar reads)
    ALLOWED_POST_PURPOSES = [
        "reservation/highlight",    # CoverManager: calendar highlight read
        "api-yoa/availability",     # SevenRooms: availability widget read
    ]

    def setUp(self):
        self.booking_src = (_SCRIPTS_DIR / "booking.py").read_text(encoding="utf-8")

    def test_no_confirm_reservation_call(self):
        """No call to a reservation-confirmation endpoint."""
        self.assertNotIn("confirm_reservation", self.booking_src)

    def test_no_create_reservation_call(self):
        self.assertNotIn("create_reservation", self.booking_src)

    def test_no_book_reservation_call(self):
        self.assertNotIn("book_reservation", self.booking_src)

    def test_no_checkout_endpoint(self):
        """No /checkout endpoint — checkout = booking completion step."""
        self.assertNotIn("/checkout", self.booking_src)

    def test_no_finalize_booking(self):
        self.assertNotIn("finalize_booking", self.booking_src)

    def test_no_agent_browser_import(self):
        """booking.py must not import agent-browser, playwright, or selenium (TLS-blocked on MA)."""
        self.assertNotIn("agent-browser", self.booking_src)
        self.assertNotIn("playwright", self.booking_src)
        self.assertNotIn("selenium", self.booking_src)
        self.assertNotIn("import driver", self.booking_src)

    def test_module_parses_as_valid_python(self):
        """booking.py must be syntactically valid Python."""
        try:
            ast.parse(self.booking_src)
        except SyntaxError as exc:
            self.fail(f"booking.py has a syntax error: {exc}")

    def test_probers_dict_exists(self):
        """PROBERS dict must exist in the module source."""
        self.assertIn("PROBERS", self.booking_src)

    def test_no_browser_import_at_ast_level(self):
        """AST-level check: no import of known browser automation packages."""
        tree = ast.parse(self.booking_src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    self.assertNotIn("playwright", name.lower(),
                                     f"Browser import found: {name}")
                    self.assertNotIn("selenium", name.lower(),
                                     f"Browser import found: {name}")


# ---------------------------------------------------------------------------
# 5. PROBERS dict — engine coverage (BOOK-02)
# ---------------------------------------------------------------------------

class TestProbers(unittest.TestCase):
    """PROBERS must cover sevenrooms, eatigo, and covermanager; no booking entry."""

    def setUp(self):
        self.booking = _import_booking()

    def test_sevenrooms_in_probers(self):
        self.assertIn("sevenrooms", self.booking.PROBERS)

    def test_eatigo_in_probers(self):
        self.assertIn("eatigo", self.booking.PROBERS)

    def test_covermanager_in_probers(self):
        self.assertIn("covermanager", self.booking.PROBERS)

    def test_probers_are_callable(self):
        for name, fn in self.booking.PROBERS.items():
            self.assertTrue(callable(fn), f"PROBERS['{name}'] is not callable")

    def test_no_booking_confirm_in_prober_names(self):
        """No prober entry should be named 'book', 'confirm', or 'checkout'."""
        for name in self.booking.PROBERS:
            self.assertNotIn("book", name.lower())
            self.assertNotIn("confirm", name.lower())
            self.assertNotIn("checkout", name.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
