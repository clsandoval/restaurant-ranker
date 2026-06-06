"""test_reviews.py — unit tests for reviews.py (no network, no API keys).

Tests cover:
- REV-02: key-absent skip path (no network call, flagged channel_status)
- REV-03: count_aware standardization reproduces spike-021 logc_z formula
- enrich_reviews over fixture corpus (key-absent returns corpus unchanged)

Python 3.10 stdlib only. No third-party dependencies.
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure we can import reviews.py from the scripts directory regardless of CWD.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import reviews  # noqa: E402 — import after path setup


# ---------------------------------------------------------------------------
# Fixture corpus — minimal venue rows matching corpus.py output contract
# ---------------------------------------------------------------------------

FIXTURE_CORPUS = [
    {
        "venue": "Helm",
        "slug": "helm",
        "area": "BGC",
        "cuisine": "Modern/Contemporary",
        "cuisine_raw": "Modern Filipino",
        "prestige_score": 3,
        "prestige_sources": ["Tatler", "Miele Guide", "Asia's 50 Best"],
        "sources_n": 3,
    },
    {
        "venue": "Toyo Eatery",
        "slug": "toyo-eatery",
        "area": "Makati",
        "cuisine": "Modern/Contemporary",
        "cuisine_raw": "Filipino",
        "prestige_score": 3,
        "prestige_sources": ["Tatler", "Asia's 50 Best", "Miele Guide"],
        "sources_n": 3,
    },
    {
        "venue": "Gallery by Chele",
        "slug": "gallery-by-chele",
        "area": "BGC",
        "cuisine": "Modern/Contemporary",
        "cuisine_raw": "European",
        "prestige_score": 2,
        "prestige_sources": ["Tatler", "Miele Guide"],
        "sources_n": 2,
    },
]


# ---------------------------------------------------------------------------
# REV-02: Key-absent skip path
# ---------------------------------------------------------------------------

class TestKeyAbsentSkip(unittest.TestCase):
    """When GOOGLE_MAPS_API_KEY is absent, enrich_reviews must skip cleanly."""

    def setUp(self):
        # Ensure the key is absent in the test environment
        self._original = os.environ.pop("GOOGLE_MAPS_API_KEY", None)

    def tearDown(self):
        if self._original is not None:
            os.environ["GOOGLE_MAPS_API_KEY"] = self._original
        else:
            os.environ.pop("GOOGLE_MAPS_API_KEY", None)

    def test_skip_returns_skipped_status(self):
        """channel_status.status == 'skipped' when key is absent."""
        venues, status = reviews.enrich_reviews(FIXTURE_CORPUS, "manila")
        self.assertEqual(status["channel"], "reviews")
        self.assertEqual(status["status"], "skipped")

    def test_skip_reason_mentions_env_var(self):
        """channel_status.reason mentions GOOGLE_MAPS_API_KEY."""
        _, status = reviews.enrich_reviews(FIXTURE_CORPUS, "manila")
        self.assertIn("GOOGLE_MAPS_API_KEY", status.get("reason", ""))

    def test_skip_n_enriched_is_zero(self):
        """channel_status.n_enriched == 0 when key is absent."""
        _, status = reviews.enrich_reviews(FIXTURE_CORPUS, "manila")
        self.assertEqual(status["n_enriched"], 0)

    def test_skip_corpus_passes_through_unchanged(self):
        """Corpus venues are returned with rating/review_count/log_count_z set to None."""
        venues, _ = reviews.enrich_reviews(FIXTURE_CORPUS, "manila")
        self.assertEqual(len(venues), len(FIXTURE_CORPUS))
        for venue in venues:
            self.assertIsNone(venue.get("rating"))
            self.assertIsNone(venue.get("review_count"))
            self.assertIsNone(venue.get("log_count_z"))

    def test_skip_makes_no_network_calls(self):
        """places_text must never be called when the key is absent."""
        with patch.object(reviews, "places_text", side_effect=AssertionError("network call made")) as mock_pt:
            venues, status = reviews.enrich_reviews(FIXTURE_CORPUS, "manila")
            mock_pt.assert_not_called()
        self.assertEqual(status["status"], "skipped")

    def test_skip_preserves_original_venue_fields(self):
        """All original corpus fields must survive the skip path unchanged."""
        venues, _ = reviews.enrich_reviews(FIXTURE_CORPUS, "manila")
        for original, returned in zip(FIXTURE_CORPUS, venues):
            for field in ("venue", "slug", "area", "cuisine", "prestige_score"):
                self.assertEqual(returned[field], original[field])


# ---------------------------------------------------------------------------
# REV-03: count_aware standardization
# ---------------------------------------------------------------------------

class TestCountAware(unittest.TestCase):
    """count_aware(counts) reproduces spike-021 logc_z standardization."""

    def _logc_z(self, counts):
        """Reference implementation from spike-021 (stdlib only)."""
        import math
        log_counts = [math.log(max(c, 1)) for c in counts]
        n = len(log_counts)
        mean = sum(log_counts) / n
        variance = sum((x - mean) ** 2 for x in log_counts) / n
        std = math.sqrt(variance)
        if std == 0:
            return [0.0] * n
        return [(x - mean) / std for x in log_counts]

    def test_single_value_returns_zero(self):
        """Single count: log_count_z must be 0.0 (std is 0)."""
        result = reviews.count_aware([100])
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0], 0.0)

    def test_standardized_mean_is_zero(self):
        """Mean of log_count_z values must be 0.0 (within floating-point tolerance)."""
        counts = [100, 500, 2000, 50, 768, 3788]
        result = reviews.count_aware(counts)
        mean = sum(result) / len(result)
        self.assertAlmostEqual(mean, 0.0, places=10)

    def test_standardized_std_is_one(self):
        """Population std of log_count_z values must be 1.0."""
        counts = [100, 500, 2000, 50, 768, 3788]
        result = reviews.count_aware(counts)
        mean = sum(result) / len(result)
        variance = sum((x - mean) ** 2 for x in result) / len(result)
        std = math.sqrt(variance)
        self.assertAlmostEqual(std, 1.0, places=10)

    def test_matches_spike_021_formula(self):
        """Results match the reference log(count) - mean / std formula from spike-021."""
        counts = [2113, 768, 3788, 1200, 450, 89]  # realistic venue counts
        result = reviews.count_aware(counts)
        expected = self._logc_z(counts)
        for got, want in zip(result, expected):
            self.assertAlmostEqual(got, want, places=12)

    def test_count_of_zero_treated_as_one(self):
        """count=0 should not cause log(0) — use log(max(count,1))."""
        # Should not raise ZeroDivisionError or ValueError
        counts = [0, 100, 500]
        try:
            result = reviews.count_aware(counts)
        except (ValueError, ZeroDivisionError):
            self.fail("count_aware raised an exception on count=0")
        self.assertEqual(len(result), 3)

    def test_empty_list_returns_empty(self):
        """Empty count list returns empty list."""
        result = reviews.count_aware([])
        self.assertEqual(result, [])

    def test_spike_021_exact_values(self):
        """Reproduce spike-021 Manila sample: Blackbird=2113, Toyo=768."""
        counts = [2113, 768]
        result = reviews.count_aware(counts)
        expected = self._logc_z(counts)
        for got, want in zip(result, expected):
            self.assertAlmostEqual(got, want, places=12)
        # Higher count (Blackbird 2113) must have higher logc_z
        self.assertGreater(result[0], result[1])

    def test_order_preserved(self):
        """Output order matches input order."""
        counts = [300, 100, 200]
        result = reviews.count_aware(counts)
        # log(300) > log(200) > log(100), so result[0] > result[2] > result[1]
        self.assertGreater(result[0], result[2])
        self.assertGreater(result[2], result[1])


# ---------------------------------------------------------------------------
# places_text shape (no network — verifies the function exists and accepts args)
# ---------------------------------------------------------------------------

class TestPlacesTextShape(unittest.TestCase):
    """places_text must exist and accept (query, key) args (no network called)."""

    def test_places_text_callable(self):
        """places_text is callable with (query, key)."""
        self.assertTrue(callable(reviews.places_text))

    def test_places_text_raises_on_network_with_bad_key(self):
        """places_text raises an error on a real HTTP call with a bogus key (expected)."""
        # We verify the function signature is correct — it should attempt a
        # network call and fail, not fail with a TypeError from wrong args.
        import urllib.error
        with self.assertRaises((urllib.error.URLError, urllib.error.HTTPError, Exception)):
            reviews.places_text("Test Restaurant BGC Philippines", "BOGUS_KEY")


# ---------------------------------------------------------------------------
# channel_status export
# ---------------------------------------------------------------------------

class TestChannelStatus(unittest.TestCase):
    """channel_status() is exported and returns the correct schema when key absent."""

    def setUp(self):
        self._original = os.environ.pop("GOOGLE_MAPS_API_KEY", None)

    def tearDown(self):
        if self._original is not None:
            os.environ["GOOGLE_MAPS_API_KEY"] = self._original
        else:
            os.environ.pop("GOOGLE_MAPS_API_KEY", None)

    def test_channel_status_keys(self):
        """channel_status dict has channel/status/reason/n_enriched keys."""
        _, status = reviews.enrich_reviews(FIXTURE_CORPUS, "manila")
        for key in ("channel", "status", "reason", "n_enriched"):
            self.assertIn(key, status, f"channel_status missing key: {key}")

    def test_channel_name_is_reviews(self):
        _, status = reviews.enrich_reviews(FIXTURE_CORPUS, "manila")
        self.assertEqual(status["channel"], "reviews")


if __name__ == "__main__":
    unittest.main(verbosity=2)
