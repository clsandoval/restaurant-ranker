"""Test suite for cityconfig.py — stdlib unittest, no third-party deps.

Run from any directory:
    python -m unittest discover -s /path/to/restaurant-ranker/scripts -p 'test_cityconfig.py' -v
"""
import unittest
import sys
import os

# Ensure cityconfig is importable regardless of CWD.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import cityconfig
from cityconfig import load_city, list_cities, UnknownCityError


class TestLoadCityKnown(unittest.TestCase):
    """load_city('manila') round-trips the manila.json produced in Task 1."""

    def test_slug_matches(self):
        c = load_city("manila")
        self.assertEqual(c["slug"], "manila")

    def test_contains_booking_platforms(self):
        c = load_city("manila")
        self.assertIn("booking_platforms", c)
        self.assertIn("online_engines", c["booking_platforms"])
        self.assertIn("readable_engines", c["booking_platforms"])

    def test_cuisine_taxonomy_nonempty(self):
        c = load_city("manila")
        self.assertIsInstance(c["cuisine_taxonomy"], list)
        self.assertGreater(len(c["cuisine_taxonomy"]), 0)

    def test_prestige_sources_nonempty(self):
        c = load_city("manila")
        self.assertGreater(len(c["prestige_sources"]), 0)


class TestLoadCityUnknown(unittest.TestCase):
    """Requesting an unconfigured city raises an actionable UnknownCityError."""

    def test_raises_unknown_city_error(self):
        with self.assertRaises(UnknownCityError):
            load_city("atlantis")

    def test_error_message_names_file_path(self):
        try:
            load_city("atlantis")
            self.fail("UnknownCityError not raised")
        except UnknownCityError as e:
            self.assertIn("cities/atlantis.json", str(e))

    def test_error_message_contains_create_or_add(self):
        try:
            load_city("atlantis")
            self.fail("UnknownCityError not raised")
        except UnknownCityError as e:
            msg = str(e).lower()
            self.assertTrue(
                "create" in msg or "add" in msg,
                f"Expected 'create' or 'add' in error message, got: {msg}",
            )


class TestLoadCityCaseInsensitive(unittest.TestCase):
    """City name lookup is case-insensitive."""

    def test_uppercase_resolves(self):
        c = load_city("Manila")
        self.assertEqual(c["slug"], "manila")

    def test_mixed_case_resolves(self):
        c = load_city("MANILA")
        self.assertEqual(c["slug"], "manila")

    def test_stripped_whitespace_resolves(self):
        c = load_city("  manila  ")
        self.assertEqual(c["slug"], "manila")


class TestListCities(unittest.TestCase):
    """list_cities() returns discoverable slugs from the cities/ directory."""

    def test_contains_manila(self):
        cities = list_cities()
        self.assertIn("manila", cities)

    def test_returns_list(self):
        self.assertIsInstance(list_cities(), list)


class TestPathTraversal(unittest.TestCase):
    """T-01-01: city names containing path-traversal components are rejected."""

    def test_slash_rejected(self):
        with self.assertRaises((UnknownCityError, ValueError)):
            load_city("../etc/passwd")

    def test_dotdot_rejected(self):
        with self.assertRaises((UnknownCityError, ValueError)):
            load_city("..atlantis")

    def test_backslash_rejected(self):
        with self.assertRaises((UnknownCityError, ValueError)):
            load_city("manila\\..\\etc")

    def test_absolute_path_rejected(self):
        with self.assertRaises((UnknownCityError, ValueError)):
            load_city("/etc/passwd")


if __name__ == "__main__":
    unittest.main()
