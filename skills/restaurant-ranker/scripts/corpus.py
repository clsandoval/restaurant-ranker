"""corpus.py — city-parameterized corpus builder for the restaurant ranker.

Builds an editorial-prestige venue table for any configured city:
    build_corpus(city) -> list[dict]

Each venue dict:
    {
      "venue":            str,          # canonical (first-seen) venue name
      "slug":             str,          # url-safe lowercase slug
      "area":             str | None,   # neighbourhood/area if known
      "cuisine":          str,          # coarse bucket from config taxonomy
      "cuisine_raw":      str | None,   # raw text from editorial source
      "prestige_score":   int,          # CORP-04: distinct configured sources listing this venue
      "prestige_sources": list[str],    # which sources (provenance)
      "sources_n":        int,          # == len(prestige_sources)
    }

CLI
---
    python corpus.py --city manila [--out <path>]

Writes <slug>-corpus.json to --out (default: CWD/<slug>-corpus.json).
Prints deduped venue count + prestige_score distribution.

Design
------
- City config is loaded via cityconfig.load_city (CORP-01, CORP-02)
- Cuisine bucketing reads from config taxonomy, never hardcoded (CORP-01)
- Name normalization + dedup produces one row per real venue (CORP-03)
- prestige_score = count of distinct configured sources (CORP-04)
- gather_source(source, city_config) is the isolated gathering seam;
  edit only that function to change the underlying retrieval mechanism
- Security T-02-01: venue names are stored as plain JSON strings only;
  callers must urlencode before using in HTTP query strings
- Security T-02-02: output path uses os.getcwd() default; never built
  from untrusted venue data

Python 3.10 stdlib only. No third-party dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------------------
# Lazy import of cityconfig — resolved via __file__-relative path so corpus.py
# works from any caller CWD, not just the scripts/ directory.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from cityconfig import load_city, UnknownCityError  # noqa: E402

__all__ = ["build_corpus", "normalize_name", "bucket_cuisine", "dedup"]

# ---------------------------------------------------------------------------
# Cuisine bucketing
# ---------------------------------------------------------------------------

def bucket_cuisine(raw: str | None, taxonomy: list[dict]) -> str:
    """Return the coarse cuisine bucket for *raw* using *taxonomy*.

    Iterates ``taxonomy`` in order; returns the bucket whose token list contains
    any substring of *raw* (case-insensitive).  The last bucket with an empty
    ``tokens`` list acts as the fallthrough (must be last in the config array).

    Parameters
    ----------
    raw : str | None
        Free-text cuisine label from an editorial source.
    taxonomy : list[dict]
        The ``cuisine_taxonomy`` array from the city config.  Each entry has
        ``bucket`` (str) and ``tokens`` (list[str]).

    Returns
    -------
    str
        The matched bucket name, or the fallthrough bucket if nothing matches.
    """
    normalized = (raw or "").lower()
    fallthrough = "Modern/Contemporary"  # sensible default if config has no empty-token entry
    for entry in taxonomy:
        tokens = entry.get("tokens", [])
        if not tokens:
            # This is the fallthrough bucket — remember it, keep scanning in
            # case a later entry (unusual but possible) matches.
            fallthrough = entry["bucket"]
            continue
        if any(t in normalized for t in tokens):
            return entry["bucket"]
    return fallthrough


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

# Common trailing suffixes to strip (checked in order after full normalization).
# Each is a regex alternation component, applied as a whole-word suffix.
_SUFFIX_PATTERNS: list[str] = [
    r"restaurant",
    r"ristorante",
    r"ristoranti",
    r"bistro",
    r"brasserie",
    r"trattoria",
    r"cantina",
    r"by\s+\w+",          # "by Chele", "by Chef Juan"
]

_SUFFIX_RE = re.compile(
    r"\s+(?:" + "|".join(_SUFFIX_PATTERNS) + r")\s*$",
    re.IGNORECASE,
)


def normalize_name(name: str) -> str:
    """Return a normalized form of *name* suitable for dedup key comparison.

    Steps:
    1. Strip leading/trailing whitespace.
    2. NFKD decompose + strip combining marks (removes diacritics: é -> e).
    3. Lowercase.
    4. Remove punctuation characters (anything that is not a letter, digit,
       whitespace, or hyphen).
    5. Collapse multiple whitespace to a single space.
    6. Strip common trailing suffixes (restaurant, ristorante, by <word>).
    7. Strip again.

    The result is a stable plain-ASCII-ish key; two venue names that differ only
    in punctuation, diacritics, or common branding suffixes will hash to the same
    key and be deduped to one row.
    """
    s = name.strip()
    # Decompose unicode + drop combining marks
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    # Lowercase
    s = s.lower()
    # Remove punctuation (keep letters, digits, whitespace, hyphen)
    s = re.sub(r"[^\w\s-]", " ", s)
    # Collapse runs of whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # Strip common trailing suffixes (may need multiple passes)
    prev = None
    while prev != s:
        prev = s
        s = _SUFFIX_RE.sub("", s).strip()
    return s


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def dedup(rows: list[dict]) -> list[dict]:
    """Collapse rows sharing the same normalized name into one venue per real place.

    Algorithm:
    - Group rows by ``normalize_name(row["venue"])``.
    - Within each group, take the first-seen venue name as canonical.
    - Union the ``prestige_sources`` lists (set of distinct source names).
    - ``prestige_score`` = ``len(distinct prestige_sources)`` (CORP-04).
    - ``sources_n`` = same as ``prestige_score`` (convenience alias matching the
      output contract consumed by plans 03 + 04).

    The function is order-independent: the prestige_score and prestige_sources set
    are the same regardless of input row ordering.  (The canonical ``venue`` string
    may differ between orderings — it is always the first-seen raw name.)

    Parameters
    ----------
    rows : list[dict]
        Raw venue rows, each expected to have at least: ``venue``, ``area``,
        ``cuisine``, ``cuisine_raw``, ``prestige_sources`` (list[str]).

    Returns
    -------
    list[dict]
        Deduplicated venues in the order canonical names were first encountered.
    """
    seen: dict[str, dict] = {}  # normalized key -> merged row

    for row in rows:
        key = normalize_name(row["venue"])
        if key not in seen:
            # First time we see this venue — copy the row and start the source set
            merged = dict(row)
            merged["prestige_sources"] = list(row.get("prestige_sources", []))
            seen[key] = merged
        else:
            # Merge sources from subsequent appearances
            existing_sources = set(seen[key]["prestige_sources"])
            for src in row.get("prestige_sources", []):
                existing_sources.add(src)
            seen[key]["prestige_sources"] = sorted(existing_sources)

    # Compute derived fields after all merges
    result = []
    for row in seen.values():
        distinct_sources = sorted(set(row["prestige_sources"]))
        row["prestige_sources"] = distinct_sources
        row["prestige_score"] = len(distinct_sources)
        row["sources_n"] = len(distinct_sources)
        result.append(row)

    return result


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------

def _venue_slug(name: str) -> str:
    """Return a url-safe lowercase slug for a venue name (not a city slug)."""
    s = normalize_name(name)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


# ---------------------------------------------------------------------------
# Gathering seam
# ---------------------------------------------------------------------------

def gather_source(source: dict, city_config: dict) -> list[dict]:
    """Return raw venue rows for a single editorial source.

    This is the isolated gather seam — the ONLY place where external data
    retrieval happens.  Callers (build_corpus) are insulated from the
    retrieval mechanism by this interface.

    Current implementation: no live retrieval is available in the local
    execution environment (web_search is not a Python stdlib function; it is
    a Claude Code tool available only inside an agent session).  The function
    returns an empty list with a warning.  When running inside an agent session
    (e.g. as a sub-call from the trip-brainstorm skill), this seam should be
    replaced by actual web_search calls following the spike-026 run-brief Step 2
    pattern.

    The expected output contract per row:
        {
          "venue":            str,
          "area":             str | None,
          "cuisine_raw":      str | None,
          "prestige_sources": [source_name],
        }

    Parameters
    ----------
    source : dict
        A single entry from ``city_config["prestige_sources"]``.
        Has at least: ``{"name": str}``.
    city_config : dict
        The full city config dict from load_city().

    Returns
    -------
    list[dict]
        Raw venue rows tagged with this source's name.
    """
    source_name = source.get("name", "")
    print(
        f"  [gather_source] NOTE: live web_search not available in stdlib environment. "
        f"No rows gathered for '{source_name}'. "
        f"Override gather_source() in an agent context to enable live retrieval.",
        file=sys.stderr,
    )
    return []


# ---------------------------------------------------------------------------
# build_corpus — the main pipeline
# ---------------------------------------------------------------------------

def build_corpus(city: str) -> list[dict]:
    """Assemble an editorial-prestige venue set for *city*.

    1. Load city config via load_city(city).
    2. For each prestige source, call gather_source() to obtain raw venue rows.
    3. Bucket cuisine via bucket_cuisine() reading from config taxonomy.
    4. Dedup by normalized name into one row per real venue (CORP-03).
    5. Each row carries prestige_score = distinct-source count (CORP-04).

    Parameters
    ----------
    city : str
        City name or slug (passed directly to load_city — case-insensitive).

    Returns
    -------
    list[dict]
        Deduped venue list, each following the output contract in the module docstring.

    Raises
    ------
    UnknownCityError
        If no cities/<slug>.json exists for *city* (propagated from load_city).
    """
    config = load_city(city)
    taxonomy = config.get("cuisine_taxonomy", [])
    prestige_sources = config.get("prestige_sources", [])

    raw_rows: list[dict] = []
    for source in prestige_sources:
        source_rows = gather_source(source, config)
        for row in source_rows:
            # Ensure prestige_sources is a list tagging this row
            row.setdefault("prestige_sources", [])
            source_name = source.get("name", "")
            if source_name and source_name not in row["prestige_sources"]:
                row["prestige_sources"].append(source_name)
            # Bucket cuisine using config taxonomy
            row["cuisine"] = bucket_cuisine(row.get("cuisine_raw"), taxonomy)
            raw_rows.append(row)

    venues = dedup(raw_rows)

    # Ensure slug field on every venue
    for v in venues:
        v.setdefault("slug", _venue_slug(v["venue"]))

    return venues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="corpus.py",
        description=(
            "Build an editorial-prestige venue corpus for a configured city.\n"
            "Writes <slug>-corpus.json to --out (default: current working directory)."
        ),
    )
    parser.add_argument(
        "--city",
        required=True,
        metavar="CITY",
        help="City name or slug (e.g. 'manila'). Must match a file in cities/<slug>.json.",
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help=(
            "Output file path. Defaults to <cwd>/<city-slug>-corpus.json. "
            "Never built from venue data (T-02-02)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_city(args.city)
    except UnknownCityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    city_slug = config["slug"]

    # Resolve output path — default to CWD/<slug>-corpus.json (T-02-02: never use venue data)
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = Path(os.getcwd()) / f"{city_slug}-corpus.json"

    venues = build_corpus(args.city)

    # Write corpus JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(venues, fh, indent=2, ensure_ascii=False)

    # Print summary to stdout
    print(f"city:    {config['city']}")
    print(f"venues:  {len(venues)} (deduped)")

    if venues:
        from collections import Counter
        score_dist = Counter(v["prestige_score"] for v in venues)
        print("prestige_score distribution:")
        for score in sorted(score_dist):
            print(f"  score={score}: {score_dist[score]} venues")
    else:
        print("prestige_score distribution: (no venues — gather_source returned empty; "
              "run inside an agent context with live web_search to populate)")

    print(f"output:  {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
