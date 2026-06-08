"""merge_fill.py — fold CloakBrowser clickthrough reads into the booking channel.

The `booking.py` HTTP probe (Step C'-1) can only read JSON-endpoint engines
(SevenRooms, Eatigo, CoverManager). Every anti-bot engine (TableCheck,
OpenTable, DinnerBooking-Turnstile, Superb-ALTCHA, ...) comes back
`channel="blocked-here"` with `fill=None` — an HONEST gap, not a verdict.

The `booking-probe` sibling skill closes that gap: it drives the real widget
with CloakBrowser (patchright + xvfb + humanize) and writes one resolved
clickthrough JSON per venue under `./<city>-booking-probe/clickthrough/`.
Those live reads carry the SAME `units:[{date, slots:[{time, state}]}]` shape
`booking.fill_from_units` already consumes — but until now nothing folded them
back into `<slug>-booking.json`, so they never reached the model's β_b.

This script is that glue (Step C'-2 → merge). For every clickthrough venue with
a genuinely resolved service grid, it upgrades the booking record to
`channel="readable"` with `filled`/`N_slots`/`grid_size` computed by the exact
same `fill_from_units` used for HTTP reads. A CloakBrowser read IS a live fill
observation, so it counts — regardless of whether the engine is in the city's
HTTP `readable_engines` set.

HONESTY RAIL (BOOK-03, preserved):
  - Only venues with a non-empty resolved grid upgrade. Clickthrough units that
    are `unresolved`/`error`/`gated` or carry `date == "*"` produce no grid
    (`fill_from_units` returns N=None) → the venue is LEFT as-is (stays
    blocked-here, fill=None). A blocked read is never fabricated into a fill.
  - `source="cloakbrowser"` is stamped on every upgraded record so the
    provenance of each fill observation is auditable downstream.

READ-ONLY: this script only reads files on disk and merges JSON. It issues no
network calls and no booking writes (BOOK-04).

Python 3.10 stdlib only.

CLI
---
  python3 merge_fill.py --city <city> --booking <slug>-booking.json \
      [--clickthrough <dir>] [--out <path>]

  --clickthrough defaults to ./<city-slug>-booking-probe/clickthrough
  --out          defaults to the --booking path (merge in place)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Lazy import of booking + cityconfig (same pattern as the other scripts)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import booking  # noqa: E402  — reuse fill_from_units (the tested HTTP-path logic)
from cityconfig import load_city, UnknownCityError  # noqa: E402

__all__ = [
    "readable_record_from_clickthrough",
    "merge_clickthrough",
    "load_clickthrough_dir",
]


def _representative_note(units: list[dict], fallback: str = "") -> str:
    """First non-empty unit note, else the fallback (e.g. a deposit note)."""
    for u in units or []:
        n = (u.get("note") or "").strip()
        if n:
            return n
    return (fallback or "").strip()


def _deposit_flag(venue: dict) -> bool:
    """Read a deposit signal from the clickthrough venue metadata (no I/O).

    booking-probe records deposit friction as a free-text `deposit_note` (or an
    explicit `deposit` bool). A non-empty note that is not an explicit negation
    counts as deposit-required.
    """
    dep = venue.get("deposit")
    if isinstance(dep, bool):
        return dep
    note = (venue.get("deposit_note") or "").strip().lower()
    if not note:
        return False
    negations = ("no deposit", "none", "not required", "no card", "n/a")
    return not any(neg in note for neg in negations)


def readable_record_from_clickthrough(venue: dict) -> dict | None:
    """Build a `channel="readable"` booking record from one clickthrough venue.

    Returns None when the venue has no resolved service grid — i.e. the live
    read did not actually observe availability (unresolved / error / gated /
    closed-only / date=="*"). Returning None is the honesty rail: the caller
    leaves the existing blocked-here record untouched (fill stays None).

    The fill is computed by `booking.fill_from_units`, the identical function
    used for HTTP reads, so a CloakBrowser observation folds in on equal footing.
    """
    units = venue.get("units") or []
    filled, n_slots, grid_size = booking.fill_from_units(units)
    if not n_slots:
        return None  # no genuine grid → not a live fill observation

    engine = venue.get("platform") or venue.get("engine") or ""
    slug = venue.get("slug")
    return {
        "slug": slug,
        "engine": engine,
        "channel": "readable",
        "g_i": 0,
        "filled": filled,
        "N_slots": n_slots,
        "grid_size": grid_size,
        "off_platform": False,
        "note": _representative_note(units, venue.get("deposit_note", "")),
        "deposit": _deposit_flag(venue),
        "source": "cloakbrowser",
    }


def load_clickthrough_dir(clickthrough_dir: Path) -> list[dict]:
    """Load every *.json under the clickthrough dir that carries `units`.

    Missing dir → []. Malformed files are skipped (a single bad file must not
    sink the merge). Order is sorted by filename for deterministic output.
    """
    if not clickthrough_dir.is_dir():
        return []
    venues: list[dict] = []
    for f in sorted(clickthrough_dir.glob("*.json")):
        try:
            v = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(v, dict) and "units" in v and v.get("slug"):
            venues.append(v)
    return venues


def merge_clickthrough(
    booking_records: list[dict],
    clickthrough_venues: list[dict],
) -> tuple[list[dict], dict]:
    """Merge CloakBrowser clickthrough reads into the HTTP booking records.

    For each clickthrough venue with a resolved grid, upgrade (or insert) the
    record keyed by `slug` to `channel="readable"`. Venues with no grid are
    skipped — their existing record (typically blocked-here) is preserved.

    Returns (merged_records, stats) where stats reports what changed so the
    caller can print an honest before/after.
    """
    by_slug: dict[str, dict] = {}
    order: list[str] = []
    for rec in booking_records:
        s = rec.get("slug")
        if s is None:
            continue
        by_slug[s] = rec
        if s not in order:
            order.append(s)

    upgraded: list[str] = []   # blocked-here/gated/online-noslots → readable
    inserted: list[str] = []   # browser-discovered venue not in HTTP records
    skipped: list[str] = []    # clickthrough present but no resolved grid

    for venue in clickthrough_venues:
        slug = venue.get("slug")
        if not slug:
            continue
        rec = readable_record_from_clickthrough(venue)
        if rec is None:
            skipped.append(slug)
            continue
        prior = by_slug.get(slug)
        if prior is None:
            inserted.append(slug)
            order.append(slug)
        elif prior.get("channel") != "readable" or prior.get("source") == "http":
            # Upgrade a blocked-here / gated / HTTP-readable record to the live
            # CloakBrowser read. (A pre-existing CloakBrowser readable is left;
            # re-running is idempotent.)
            if prior.get("channel") != "readable":
                upgraded.append(slug)
        by_slug[slug] = rec

    merged = [by_slug[s] for s in order]
    stats = {
        "total_records": len(merged),
        "upgraded": upgraded,
        "inserted": inserted,
        "skipped_no_grid": skipped,
        "readable_after": sum(1 for r in merged if r.get("channel") == "readable"),
        "readable_via_cloakbrowser": sum(
            1 for r in merged
            if r.get("channel") == "readable" and r.get("source") == "cloakbrowser"
        ),
    }
    return merged, stats


def _print_merge_summary(stats: dict, n_clickthrough: int) -> None:
    print("\n=== MERGE FILL (CloakBrowser → booking channel) ===")
    print(f"clickthrough venues read:   {n_clickthrough}")
    print(f"upgraded blocked→readable:  {len(stats['upgraded'])}")
    if stats["upgraded"]:
        print("   " + ", ".join(stats["upgraded"]))
    print(f"inserted (browser-only):    {len(stats['inserted'])}")
    if stats["inserted"]:
        print("   " + ", ".join(stats["inserted"]))
    print(f"skipped (no resolved grid): {len(stats['skipped_no_grid'])}  "
          f"(honesty rail — left blocked-here, fill=None)")
    print(f"readable after merge:       {stats['readable_after']}  "
          f"({stats['readable_via_cloakbrowser']} via CloakBrowser)")
    print("===================================================\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merge_fill.py",
        description=(
            "Fold CloakBrowser clickthrough reads (booking-probe skill) into the\n"
            "<slug>-booking.json fill channel so anti-bot venues reach the model's β_b.\n"
            "Read-only / read-only-merge: no network, no booking writes. Honesty rail:\n"
            "only genuinely-resolved grids upgrade; blocked reads stay fill=None."
        ),
    )
    parser.add_argument("--city", required=True, metavar="CITY",
                        help="City name or slug (must match cities/<slug>.json).")
    parser.add_argument("--booking", required=True, metavar="BOOKING_JSON",
                        help="Path to the HTTP <slug>-booking.json from booking.py.")
    parser.add_argument("--clickthrough", default=None, metavar="DIR",
                        help="Clickthrough dir. Default: "
                             "./<city-slug>-booking-probe/clickthrough")
    parser.add_argument("--out", default=None, metavar="PATH",
                        help="Output path. Default: merge in place over --booking.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_city(args.city)
    except (UnknownCityError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    city_slug = config["slug"]

    booking_path = Path(args.booking)
    try:
        booking_records = json.loads(booking_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not load booking JSON '{booking_path}': {exc}",
              file=sys.stderr)
        return 1
    if not isinstance(booking_records, list):
        print("ERROR: booking JSON must be a list of records.", file=sys.stderr)
        return 1

    if args.clickthrough:
        ct_dir = Path(args.clickthrough)
    else:
        ct_dir = Path(os.getcwd()) / f"{city_slug}-booking-probe" / "clickthrough"

    clickthrough_venues = load_clickthrough_dir(ct_dir)
    if not clickthrough_venues:
        print(f"NOTE: no clickthrough venues found under {ct_dir} — "
              f"booking records unchanged.", file=sys.stderr)

    merged, stats = merge_clickthrough(booking_records, clickthrough_venues)
    _print_merge_summary(stats, len(clickthrough_venues))

    out_path = Path(args.out) if args.out else booking_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)
    print(f"output: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
