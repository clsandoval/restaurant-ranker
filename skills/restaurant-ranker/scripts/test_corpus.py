"""Unit tests for corpus.py — dedup/name-normalization and prestige scoring.

Covers four behaviors specified in plan 01-02 Task 1:
  1. bucket_cuisine returns the correct bucket given cuisine tokens from config taxonomy
  2. bucket_cuisine falls through to the fallthrough bucket for unmatched raw cuisine
  3. normalize_name collapses common suffixes and diacritics so variants hash to the same key
  4. dedup yields ONE row per normalized-name with prestige_sources = union of both source names
     and prestige_score = count of distinct sources (order-independent)

No network. All fixture data is inline.

Python 3.10 stdlib only.
"""
import unittest

# ---------------------------------------------------------------------------
# Inline fixture taxonomy (mirrors manila.json shape, no file I/O required)
# ---------------------------------------------------------------------------
FIXTURE_TAXONOMY = [
    {"bucket": "Japanese", "tokens": ["japanese", "sushi", "omakase", "kaiseki", "kappo"]},
    {"bucket": "Italian",  "tokens": ["italian"]},
    {"bucket": "French",   "tokens": ["french"]},
    {"bucket": "Spanish",  "tokens": ["spanish", "basque", "mediterranean"]},
    {"bucket": "Steakhouse", "tokens": ["steak"]},
    {"bucket": "Chinese",  "tokens": ["chinese", "cantonese", "dimsum"]},
    {"bucket": "Filipino", "tokens": ["filipino"]},
    {
        "_note": "fallthrough — anything not matched by the 7 buckets above",
        "bucket": "Modern/Contemporary",
        "tokens": [],
    },
]

# ---------------------------------------------------------------------------
# Lazy import so tests fail with an ImportError (not NameError) if the module
# doesn't exist yet — that's the desired RED state.
# ---------------------------------------------------------------------------
import importlib


def _import_corpus():
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    return importlib.import_module("corpus")


class TestBucketCuisine(unittest.TestCase):
    """bucket_cuisine(raw, taxonomy) -> str bucket name."""

    def setUp(self):
        self.corpus = _import_corpus()

    def test_omakase_sushi_is_japanese(self):
        result = self.corpus.bucket_cuisine("omakase sushi", FIXTURE_TAXONOMY)
        self.assertEqual(result, "Japanese")

    def test_kappo_is_japanese(self):
        result = self.corpus.bucket_cuisine("Kappo-style dining", FIXTURE_TAXONOMY)
        self.assertEqual(result, "Japanese")

    def test_italian_matched(self):
        result = self.corpus.bucket_cuisine("Modern Italian", FIXTURE_TAXONOMY)
        self.assertEqual(result, "Italian")

    def test_steakhouse_via_token(self):
        result = self.corpus.bucket_cuisine("steakhouse grill", FIXTURE_TAXONOMY)
        self.assertEqual(result, "Steakhouse")

    def test_gastropub_fallthrough(self):
        """Unmatched raw cuisine -> fallthrough bucket (Modern/Contemporary)."""
        result = self.corpus.bucket_cuisine("gastropub", FIXTURE_TAXONOMY)
        self.assertEqual(result, "Modern/Contemporary")

    def test_empty_string_fallthrough(self):
        result = self.corpus.bucket_cuisine("", FIXTURE_TAXONOMY)
        self.assertEqual(result, "Modern/Contemporary")

    def test_none_fallthrough(self):
        result = self.corpus.bucket_cuisine(None, FIXTURE_TAXONOMY)
        self.assertEqual(result, "Modern/Contemporary")

    def test_first_match_wins_spanish_before_fallthrough(self):
        """'mediterranean' should hit Spanish before falling through."""
        result = self.corpus.bucket_cuisine("mediterranean tapas", FIXTURE_TAXONOMY)
        self.assertEqual(result, "Spanish")

    def test_taxonomy_tokens_come_from_config_not_hardcode(self):
        """Verify that swapping out the taxonomy dict changes the result — proves
        bucket_cuisine reads from the config arg, not a hardcoded module-level constant."""
        tiny_taxonomy = [{"bucket": "TestBucket", "tokens": ["gastropub"]}]
        result = self.corpus.bucket_cuisine("gastropub", tiny_taxonomy)
        self.assertEqual(result, "TestBucket")


class TestNormalizeName(unittest.TestCase):
    """normalize_name(name) -> str lowercase, no punctuation, no common suffixes."""

    def setUp(self):
        self.corpus = _import_corpus()

    def test_lowercase(self):
        result = self.corpus.normalize_name("TOYO EATERY")
        self.assertEqual(result, result.lower())

    def test_strips_restaurant_suffix(self):
        key1 = self.corpus.normalize_name("Helm Restaurant")
        key2 = self.corpus.normalize_name("Helm")
        self.assertEqual(key1, key2)

    def test_strips_ristorante_suffix(self):
        key1 = self.corpus.normalize_name("Caruso Ristorante")
        key2 = self.corpus.normalize_name("Caruso")
        self.assertEqual(key1, key2)

    def test_strips_by_chele_style_suffix(self):
        """'by chele' and similar 'by X' brandname suffixes collapse."""
        key1 = self.corpus.normalize_name("Cantabria by Chele")
        key2 = self.corpus.normalize_name("Cantabria")
        self.assertEqual(key1, key2)

    def test_diacritics_stripped(self):
        key1 = self.corpus.normalize_name("Café Flore")
        key2 = self.corpus.normalize_name("Cafe Flore")
        self.assertEqual(key1, key2)

    def test_punctuation_stripped(self):
        key1 = self.corpus.normalize_name("Steak & Frice")
        key2 = self.corpus.normalize_name("Steak  Frice")
        # Both should normalize to same key (ampersand removed, extra space collapsed)
        self.assertEqual(key1, key2)

    def test_leading_trailing_whitespace(self):
        key1 = self.corpus.normalize_name("  Helm  ")
        key2 = self.corpus.normalize_name("Helm")
        self.assertEqual(key1, key2)


class TestDedup(unittest.TestCase):
    """dedup(rows) collapses rows with the same normalized name into one venue.

    CORP-03 (one row per real venue) and CORP-04 (prestige_score = distinct-source count).
    """

    def setUp(self):
        self.corpus = _import_corpus()

    def _make_row(self, venue, source, area=None, cuisine="Modern/Contemporary"):
        return {
            "venue": venue,
            "area": area,
            "cuisine": cuisine,
            "cuisine_raw": cuisine,
            "prestige_sources": [source],
        }

    def test_two_sources_same_venue_collapse(self):
        rows = [
            self._make_row("Toyo Eatery", "Asia 50 Best"),
            self._make_row("Toyo Eatery", "Michelin Guide"),
        ]
        result = self.corpus.dedup(rows)
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(row["prestige_score"], 2)
        self.assertIn("Asia 50 Best", row["prestige_sources"])
        self.assertIn("Michelin Guide", row["prestige_sources"])

    def test_prestige_score_equals_distinct_source_count(self):
        rows = [
            self._make_row("Helm", "Asia 50 Best"),
            self._make_row("Helm", "Michelin Guide"),
            self._make_row("Helm", "Michelin Guide"),  # duplicate source entry
        ]
        result = self.corpus.dedup(rows)
        self.assertEqual(len(result), 1)
        # distinct sources = 2 even though 3 rows
        self.assertEqual(result[0]["prestige_score"], 2)

    def test_different_venues_not_collapsed(self):
        rows = [
            self._make_row("Toyo Eatery", "Asia 50 Best"),
            self._make_row("Helm", "Asia 50 Best"),
        ]
        result = self.corpus.dedup(rows)
        self.assertEqual(len(result), 2)

    def test_suffix_variant_collapses(self):
        """'Helm Restaurant' and 'Helm' must collapse to one row."""
        rows = [
            self._make_row("Helm Restaurant", "Asia 50 Best"),
            self._make_row("Helm", "Michelin Guide"),
        ]
        result = self.corpus.dedup(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["prestige_score"], 2)

    def test_dedup_is_order_independent(self):
        """Same result regardless of input row order."""
        rows_a = [
            self._make_row("Cantabria by Chele", "Asia 50 Best"),
            self._make_row("Cantabria", "Michelin Guide"),
        ]
        rows_b = [
            self._make_row("Cantabria", "Michelin Guide"),
            self._make_row("Cantabria by Chele", "Asia 50 Best"),
        ]
        result_a = self.corpus.dedup(rows_a)
        result_b = self.corpus.dedup(rows_b)
        self.assertEqual(len(result_a), 1)
        self.assertEqual(len(result_b), 1)
        self.assertEqual(result_a[0]["prestige_score"], result_b[0]["prestige_score"])
        self.assertEqual(
            sorted(result_a[0]["prestige_sources"]),
            sorted(result_b[0]["prestige_sources"]),
        )

    def test_single_source_venue_has_prestige_score_1(self):
        rows = [self._make_row("Blackbird", "Tatler Asia")]
        result = self.corpus.dedup(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["prestige_score"], 1)
        self.assertEqual(result[0]["sources_n"], 1)

    def test_sources_n_equals_len_prestige_sources(self):
        rows = [
            self._make_row("Gallery", "Asia 50 Best"),
            self._make_row("Gallery", "Michelin Guide"),
            self._make_row("Gallery", "Tatler Asia"),
        ]
        result = self.corpus.dedup(rows)
        self.assertEqual(result[0]["sources_n"], len(result[0]["prestige_sources"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
