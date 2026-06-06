"""reviews.py — Google Reviews channel for the restaurant ranker.

Ports spike-020 fetch_reviews.py into a corpus-aware, key-optional, count-aware
reviews enrichment channel.

Changes from spike-020:
  1. API key read from GOOGLE_MAPS_API_KEY env var (never hardcoded); graceful
     degradation when absent — run continues, channel flagged skipped (REV-02).
  2. Disambiguating Places query built from city config country instead of
     hardcoded "Metro Manila Philippines" (works for any city).
  3. Emits count-aware feature log_count_z = standardized log(review_count) per
     spike-021 (REV-03) — demand signal alongside the raw rating.

Public API
----------
enrich_reviews(corpus, city) -> (venues, channel_status)

    venues : list[dict]
        Each venue dict gains:
            rating          : float | None   (Google Places rating mean)
            review_count    : int | None     (userRatingCount)
            log_count_z     : float | None   (standardized log count; None if no count)
            reviews_matched : str | None     (Places displayName for provenance)

    channel_status : dict
        {
          "channel"    : "reviews",
          "status"     : "ok" | "skipped",
          "reason"     : str | None,          # set when skipped
          "n_enriched" : int,                 # venues with a non-None rating
        }

    When GOOGLE_MAPS_API_KEY is absent:
        - corpus is returned with rating/review_count/log_count_z = None
        - channel_status.status == "skipped" with reason naming the env var
        - NO network call is made (REV-02 honesty rail)

Helper exports (used by CLI and tests)
---------------------------------------
places_text(query, key)  -> dict | None
count_aware(counts)      -> list[float]

Threat mitigations (T-03-*)
----------------------------
T-03-01: API key never printed, never written to output JSON, never included in
         per-venue error strings.
T-03-02: textQuery sent in POST body (no shell interpolation; Places response
         treated as data only).
T-03-03: per-venue try/except + 50ms throttle so one bad venue or rate-limit
         does not abort the channel.
T-03-SC: stdlib only (os/json/math/time/urllib/argparse/pathlib/sys/unittest).

CLI
---
    python reviews.py --city manila --corpus <path/to/corpus.json> [--out <path>]

Reads a plan-02 corpus JSON, writes an enriched JSON to --out (default:
<city-slug>-reviews.json under os.getcwd()), and prints:
    reviews: ok|skipped (N/T enriched)

Python 3.10 stdlib only. No third-party dependencies.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Lazy import of cityconfig — resolved relative to this file so reviews.py
# works from any caller CWD (T-02 pattern from corpus.py).
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from cityconfig import load_city, UnknownCityError  # noqa: E402

__all__ = ["enrich_reviews", "places_text", "count_aware", "channel_status"]

# Places API endpoint (POST)
_PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
# FieldMask: only the fields we need (REV-01)
_FIELD_MASK = "places.displayName,places.rating,places.userRatingCount,places.formattedAddress"


# ---------------------------------------------------------------------------
# places_text — low-level Places API helper (REV-01)
# ---------------------------------------------------------------------------

def places_text(query: str, key: str) -> dict | None:
    """POST a textSearch query to the Google Places API and return the top result.

    Parameters
    ----------
    query : str
        Free-text search query (e.g. "Helm restaurant BGC Philippines").
        Sent in the JSON POST body; no shell interpolation (T-03-02).
    key : str
        Google Maps API key.  Passed as the X-Goog-Api-Key header only;
        never logged or included in exceptions (T-03-01).

    Returns
    -------
    dict | None
        The first Places result dict, or None if no results.

    Raises
    ------
    urllib.error.URLError / urllib.error.HTTPError
        On network failure.  The caller is responsible for per-venue try/except
        (T-03-03 pattern).
    """
    payload = json.dumps({"textQuery": query, "maxResultCount": 1}).encode()
    req = urllib.request.Request(
        _PLACES_SEARCH_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            # T-03-01: key used only as header value; never logged
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": _FIELD_MASK,
        },
        method="POST",
    )
    response_bytes = urllib.request.urlopen(req, timeout=20).read()
    result = json.loads(response_bytes)
    places = result.get("places") or []
    return places[0] if places else None


# ---------------------------------------------------------------------------
# count_aware — REV-03 count-aware feature derivation
# ---------------------------------------------------------------------------

def count_aware(counts: list[int | float]) -> list[float]:
    """Standardize log(review_count) across venues — reproduces spike-021 logc_z.

    Formula: logc_z_i = (log(max(count_i, 1)) - mean(log_counts)) / std(log_counts)

    This is a demand-signal feature: venues with more reviews (revealed
    preference) get a higher log_count_z.  Standardization (mean 0, std 1)
    puts it on the same scale as other model inputs.

    Parameters
    ----------
    counts : list[int | float]
        Raw review counts per venue.  Zero or negative values are clamped to 1
        before taking the log (avoids log(0)).

    Returns
    -------
    list[float]
        Standardized log counts in the same order as input.
        If the input list is empty, returns [].
        If all values produce the same log (std == 0), returns [0.0, ...].
    """
    if not counts:
        return []

    log_counts = [math.log(max(c, 1)) for c in counts]
    n = len(log_counts)
    mean = sum(log_counts) / n
    variance = sum((x - mean) ** 2 for x in log_counts) / n
    std = math.sqrt(variance)

    if std == 0:
        return [0.0] * n

    return [(x - mean) / std for x in log_counts]


# ---------------------------------------------------------------------------
# enrich_reviews — corpus enrichment (REV-01 + REV-02 + REV-03)
# ---------------------------------------------------------------------------

def enrich_reviews(
    corpus: list[dict],
    city: str,
) -> tuple[list[dict], dict]:
    """Enrich corpus venues with Google rating + review count + log_count_z.

    Parameters
    ----------
    corpus : list[dict]
        Venue rows from build_corpus (plan 02).  Each must have at least
        ``venue``, ``slug``, ``area`` keys.
    city : str
        City name or slug — passed to load_city() to get the country for
        the disambiguating Places query.

    Returns
    -------
    (venues, channel_status)
        venues : list[dict]
            Original rows with added keys:
                rating          : float | None
                review_count    : int | None
                log_count_z     : float | None
                reviews_matched : str | None
        channel_status : dict
            {"channel": "reviews", "status": "ok"|"skipped",
             "reason": str|None, "n_enriched": int}

    REV-02 guarantee: if GOOGLE_MAPS_API_KEY is not set in the environment,
    this function returns immediately with status="skipped" and makes NO
    network calls.  The corpus passes through with all review fields = None.
    The key is NEVER printed, logged, or written to the output (T-03-01).
    """
    # REV-02: check for key first — abort channel cleanly if absent
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        skipped_venues = [
            {
                **venue,
                "rating": None,
                "review_count": None,
                "log_count_z": None,
                "reviews_matched": None,
            }
            for venue in corpus
        ]
        return skipped_venues, {
            "channel": "reviews",
            "status": "skipped",
            "reason": (
                "GOOGLE_MAPS_API_KEY is not set in the environment. "
                "Set this env var to enable the reviews channel."
            ),
            "n_enriched": 0,
        }

    # Load city config to get country for the disambiguating query
    config = load_city(city)
    country = config.get("country", "")

    # Enrich each venue (T-03-03: per-venue try/except; one error never aborts the run)
    enriched_venues: list[dict] = []
    for venue in corpus:
        venue_name = venue.get("venue", "")
        area = venue.get("area") or ""
        # Build disambiguating query using config country (not hardcoded — REV-01)
        query = f"{venue_name} restaurant {area} {country}".strip()

        result_venue = dict(venue)
        result_venue["rating"] = None
        result_venue["review_count"] = None
        result_venue["log_count_z"] = None  # computed after loop
        result_venue["reviews_matched"] = None

        try:
            place = places_text(query, key)
            if place:
                result_venue["rating"] = place.get("rating")
                result_venue["review_count"] = place.get("userRatingCount")
                display_name = place.get("displayName")
                if isinstance(display_name, dict):
                    result_venue["reviews_matched"] = display_name.get("text")
                elif isinstance(display_name, str):
                    result_venue["reviews_matched"] = display_name
        except Exception as exc:
            # T-03-01: do NOT include the key in the error string
            # T-03-03: capture per-venue; do not abort
            safe_msg = _sanitize_error(str(exc), key)
            result_venue["error"] = safe_msg

        enriched_venues.append(result_venue)

        # Rate-limit throttle — same 50ms as spike-020
        time.sleep(0.05)

    # REV-03: compute log_count_z over all venues that have a count
    _attach_log_count_z(enriched_venues)

    n_enriched = sum(1 for v in enriched_venues if v.get("rating") is not None)

    return enriched_venues, {
        "channel": "reviews",
        "status": "ok",
        "reason": None,
        "n_enriched": n_enriched,
    }


def _sanitize_error(msg: str, key: str | None) -> str:
    """Remove API key from error messages (T-03-01)."""
    if key and key in msg:
        msg = msg.replace(key, "<REDACTED>")
    return msg


def _attach_log_count_z(venues: list[dict]) -> None:
    """Compute and attach log_count_z to venue dicts in-place.

    Only venues that have a non-None review_count participate in standardization.
    Venues without a count keep log_count_z=None.
    """
    indices_with_count = [
        i for i, v in enumerate(venues) if v.get("review_count") is not None
    ]
    if not indices_with_count:
        return

    counts = [venues[i]["review_count"] for i in indices_with_count]
    z_values = count_aware(counts)

    for i, z in zip(indices_with_count, z_values):
        venues[i]["log_count_z"] = z


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reviews.py",
        description=(
            "Enrich a plan-02 corpus JSON with Google rating + review count + log_count_z.\n"
            "Writes <city-slug>-reviews.json to --out (default: current working directory).\n"
            "Skips cleanly when GOOGLE_MAPS_API_KEY is absent (REV-02)."
        ),
    )
    parser.add_argument(
        "--city",
        required=True,
        metavar="CITY",
        help="City name or slug (e.g. 'manila'). Must match a cities/<slug>.json config.",
    )
    parser.add_argument(
        "--corpus",
        required=True,
        metavar="PATH",
        help="Path to the plan-02 corpus JSON produced by corpus.py.",
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help=(
            "Output file path. Defaults to <cwd>/<city-slug>-reviews.json. "
            "Never built from venue data (T-03 safe)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Load city config to resolve slug for output filename
    try:
        config = load_city(args.city)
    except UnknownCityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    city_slug = config["slug"]

    # Load input corpus
    corpus_path = Path(args.corpus)
    if not corpus_path.exists():
        print(f"ERROR: corpus file not found: {corpus_path}", file=sys.stderr)
        return 1

    with corpus_path.open(encoding="utf-8") as fh:
        corpus = json.load(fh)

    if not isinstance(corpus, list):
        print("ERROR: corpus JSON must be a list of venue dicts.", file=sys.stderr)
        return 1

    # Resolve output path — default to CWD/<slug>-reviews.json
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = Path(os.getcwd()) / f"{city_slug}-reviews.json"

    # Enrich
    venues, status = enrich_reviews(corpus, args.city)

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(venues, fh, indent=2, ensure_ascii=False)

    # Print status summary (T-03-01: never print the key)
    n_enriched = status["n_enriched"]
    n_total = len(venues)
    chan_status = status["status"]
    print(f"reviews: {chan_status} ({n_enriched}/{n_total} enriched)")
    if status.get("reason"):
        print(f"  reason: {status['reason']}")
    print(f"  output: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
