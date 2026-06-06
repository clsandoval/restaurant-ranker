"""booking.py — HTTP-only booking-demand channel for the restaurant ranker.

Ports spike-026 probe100.py HTTP readers (SevenRooms, Eatigo, CoverManager) and the
fill-computation + channel-classification logic from spike-013 assemble.py and
spike-016 gate_ladder.py into the pipeline's booking channel.

HARD CONSTRAINTS (by design):
  - HTTP-only: no browser automation (spike 023 shows browser is TLS-blocked
    on Managed Agents; booking platforms' own JSON endpoints work over plain
    HTTP through the MA proxy — spike 026 validates: β_b=+2.67, 10 readable
    venues live).
  - READ-ONLY: probers read availability only. Never POST to create, confirm,
    or complete a reservation. Reading the slot list IS the probe. (BOOK-04)
  - Python 3.10 stdlib only: urllib, json, re, datetime, argparse, os, sys.

Exports
-------
  probe_venue(engine, identifier) -> units dict
  fill_from_units(units) -> (filled:int|None, N_slots:int|None, grid_size:int)
  gate_level(engine, note, deposit) -> (level:int 0..4, label:str)
  classify(engine, units, city_config) -> per-venue booking record dict
  PROBERS  -- dict mapping engine name -> callable(identifier) -> units dict

CLI
---
  python booking.py --city manila --venues <map.json> [--out <path>]

  <map.json> shape:  { "venue-slug": {"engine": "sevenrooms", "identifier": "cantabriamnlwp"}, ... }

  Writes a booking JSON to --out (default: <cwd>/<city-slug>-booking.json).
  Prints a FILL EVIDENCE summary (per readable venue: dates returned, offered
  slots, computed fill rate) plus the off-platform venue count.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Lazy import of cityconfig (same pattern as corpus.py)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from cityconfig import load_city, UnknownCityError  # noqa: E402

__all__ = [
    "probe_venue",
    "fill_from_units",
    "gate_level",
    "classify",
    "PROBERS",
]

# ---------------------------------------------------------------------------
# Network helpers (HTTP-only — no browser)
# ---------------------------------------------------------------------------

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/149.0 Safari/537.36"
_TIMEOUT = 25  # seconds per request

# Target dates for probing (6 dates spread across the next few weeks).
# In a live run the agent would compute these relative to today; we mirror
# probe100.py's static set for the portfolio-validation context.
_PROBE_DATES = [
    "2026-06-06", "2026-06-07", "2026-06-10",
    "2026-06-13", "2026-06-20", "2026-06-24",
]


def _get(url: str, headers: dict | None = None) -> str:
    """HTTP GET — read-only availability fetch. Never issues booking writes."""
    h = {"User-Agent": _UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=_TIMEOUT).read().decode("utf-8", "replace")


def _post_form(url: str, data: dict, headers: dict | None = None) -> str:
    """HTTP POST with form-encoded body — used ONLY for calendar-read endpoints.

    The CoverManager 'reservation/highlight' endpoint requires POST to return
    the month's availability map. This is a read operation — it returns a
    calendar highlight, never creates a reservation.

    Read-only contract: this function is called ONLY for the CoverManager
    highlight (calendar read). It MUST NOT be used for booking-write operations.
    """
    h = {"Content-Type": "application/x-www-form-urlencoded",
         "User-Agent": _UA}
    if headers:
        h.update(headers)
    encoded = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=encoded, headers=h, method="POST")
    return urllib.request.urlopen(req, timeout=_TIMEOUT).read().decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# HTTP probers — read-only availability readers
# Each returns: {"engine": str, "units": list[dict], ...extra engine-specific fields}
# units element: {"date": str, "party_size": int, "status": str, "slots": [...]}
# slot element:  {"time": str, "state": "available"|"filled", ...}
# ---------------------------------------------------------------------------

def _probe_covermanager(slug: str) -> dict:
    """Read CoverManager availability for party=2 across _PROBE_DATES.

    Uses:
      POST /reservation/highlight — returns month calendar map (READ, not book)
      GET  /Reserve/change_day/<slug>/<date>/2/english — returns slot list per date

    Never POSTs to a booking-confirmation endpoint.
    """
    base = "https://www.covermanager.com"
    extra_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Origin": base,
        "Referer": f"{base}/reserve/module_restaurant/{slug}/english",
    }
    try:
        raw_hl = _post_form(
            f"{base}/reservation/highlight",
            {
                "language": "english",
                "restaurant": slug,
                "month": "06",
                "year": "2026",
                "vip": "0",
                "skip_blocked_tables": "false",
                "people": "2",
            },
            headers=extra_headers,
        )
        hl = json.loads(raw_hl)
    except Exception as exc:
        return {"engine": "covermanager", "error": str(exc), "units": []}

    if isinstance(hl, list):
        return {"engine": "covermanager", "error": "invalid slug ([] highlight)", "units": []}

    units = []
    for d in _PROBE_DATES:
        ds = (hl.get(d) or [None, "missing"])[1]
        slots = []
        try:
            raw_day = _get(
                f"{base}/Reserve/change_day/{slug}/{d}/2/english",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            j = json.loads(raw_day)
            for meal, m in (j.get("hours") or {}).items():
                per = None
                if not isinstance(m.get("hours"), list):
                    per = (m.get("hours") or {}).get("2")
                if per and per.get("all"):
                    for s in per["all"]:
                        slots.append({"time": s["value"], "meal": meal, "state": "available"})
        except Exception:
            pass
        st = "available" if slots else ("no-slots" if ds == "close_date" else "full")
        units.append({
            "date": d,
            "party_size": 2,
            "status": st,
            "slots": slots,
            "note": ("day:" + ds) if slots else ds,
        })

    return {
        "engine": "covermanager",
        "month_map": {k: (v[1] or "open") for k, v in hl.items() if isinstance(v, list)},
        "units": units,
    }


def _probe_sevenrooms(venue: str) -> dict:
    """Read SevenRooms availability widget for party=2 across _PROBE_DATES.

    Queries /api-yoa/availability/widget/range — the public availability widget
    endpoint. Reads bookable slots (type=='book'). Never POSTs a reservation.

    The deposit/credit-card requirement is read from the slot metadata (carry
    flag only — no booking-write step triggered).
    """
    base = "https://www.sevenrooms.com/api-yoa/availability/widget/range"
    byd: dict[str, dict[str, str]] = {d: {} for d in _PROBE_DATES}
    deposit_seen = False
    deposit_detail: set[str] = set()

    for ts in ["13:00", "19:00"]:
        for d in _PROBE_DATES:
            sd = datetime.datetime.strptime(d, "%Y-%m-%d").strftime("%m-%d-%Y")
            url = (
                f"{base}?venue={venue}"
                f"&time_slot={urllib.parse.quote(ts)}"
                f"&party_size=2&halo_size_interval=16"
                f"&start_date={sd}&num_days=1"
                f"&channel=SEVENROOMS_WIDGET"
            )
            try:
                j = json.loads(_get(url))
                av = (j.get("data") or {}).get("availability") or {}
                for date, shifts in av.items():
                    for sh in shifts:
                        for t in sh.get("times", []):
                            tm = t.get("time")
                            if not tm:
                                continue
                            # type=="book" or a real access_persistent_id = bookable.
                            # type=="request" = waitlist inquiry — NOT real availability.
                            bookable = (
                                t.get("type") == "book"
                                or (
                                    t.get("access_persistent_id")
                                    and t.get("type") != "request"
                                )
                            )
                            if bookable:
                                byd.setdefault(date, {})[tm] = "book"
                                # Read deposit flag from slot metadata only —
                                # no booking-write call issued (READ-ONLY).
                                if (t.get("require_credit_card") or t.get("cost")
                                        or t.get("cc_payment_rule") or t.get("charge_type")):
                                    deposit_seen = True
                                    if t.get("cost"):
                                        deposit_detail.add(f"cost {t.get('cost')}")
                                    if t.get("cc_payment_rule"):
                                        deposit_detail.add(str(t.get("cc_payment_rule")))
                                    if t.get("require_credit_card"):
                                        deposit_detail.add("credit-card required")
                            elif t.get("type") == "request" or t.get("is_requestable"):
                                byd.setdefault(date, {}).setdefault(tm, "request")
            except Exception:
                pass

    units = []
    for d in _PROBE_DATES:
        m = byd[d]
        book = sorted(t for t, k in m.items() if k == "book")
        wait = sorted(t for t, k in m.items() if k == "request")
        slots = (
            [{"time": t, "state": "available"} for t in book]
            + [{"time": t, "state": "filled", "note": "waitlist/request-only"} for t in wait]
        )
        note = (
            ""
            if book
            else (
                "waitlist-only (" + str(len(wait)) + " request slots)"
                if wait
                else "no times offered"
            )
        )
        units.append({
            "date": d,
            "party_size": 2,
            "status": "available" if book else "full",
            "slots": slots,
            "note": note,
        })

    return {
        "engine": "sevenrooms",
        "units": units,
        "deposit": {"required": deposit_seen, "detail": sorted(deposit_detail)},
    }


def _probe_eatigo(branch_id: str) -> dict:
    """Read Eatigo availability for party=2 across _PROBE_DATES.

    Fetches the branch page HTML and extracts the __NUXT_DATA__ embedded JSON.
    Read-only: slot times are read from the page data, no booking action taken.
    """
    try:
        html = _get(
            f"https://eatigo.com/en/branches/{branch_id}",
            headers={"User-Agent": _UA},
        )
    except Exception as exc:
        return {"engine": "eatigo", "error": str(exc), "units": []}

    m = re.search(r'id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return {"engine": "eatigo", "error": "no __NUXT_DATA__", "units": []}

    try:
        arr = json.loads(m.group(1))
    except Exception as exc:
        return {"engine": "eatigo", "error": f"JSON parse error: {exc}", "units": []}

    def deref(i: int, depth: int = 0) -> Any:
        if depth > 16:
            return None
        v = arr[i]
        if isinstance(v, list):
            if len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], int):
                return deref(v[1], depth + 1)
            return [deref(x, depth + 1) if isinstance(x, int) else x for x in v]
        if isinstance(v, dict):
            return {k: (deref(r, depth + 1) if isinstance(r, int) else r) for k, r in v.items()}
        return v

    ref = None
    for v in arr:
        if isinstance(v, dict):
            for k, val in v.items():
                if (isinstance(k, str)
                        and k.startswith("branch-arrival-times_branch-detail")
                        and isinstance(val, int)
                        and val >= 0):
                    ref = val
                    break
        if ref is not None:
            break

    data = deref(ref) if ref is not None else None
    if not data or not data.get("slots"):
        return {"engine": "eatigo", "error": "no slots", "units": []}

    by_date: dict[str, list] = {}
    for s in data["slots"]:
        d, t = s["slot"].split(" ")
        by_date.setdefault(d, []).append({"time": t, "discount": s.get("discount")})

    start = data["start_day"][:10]
    end = data["end_day"][:10]
    units = []
    for d in _PROBE_DATES:
        if d in by_date:
            units.append({
                "date": d,
                "party_size": 2,
                "status": "available",
                "slots": [
                    {"time": x["time"], "state": "available", "discount_pct": x["discount"]}
                    for x in by_date[d]
                ],
                "note": "",
            })
        elif start <= d <= end:
            units.append({"date": d, "party_size": 2, "status": "full",
                          "slots": [], "note": "in-window no times"})
        else:
            units.append({"date": d, "party_size": 2, "status": "no-slots",
                          "slots": [], "note": "outside window"})

    return {"engine": "eatigo", "window": [start, end], "units": units}


# ---------------------------------------------------------------------------
# PROBERS — the dispatch registry (BOOK-02: extensible via config)
# ---------------------------------------------------------------------------

PROBERS: dict[str, Any] = {
    "sevenrooms": _probe_sevenrooms,
    "eatigo": _probe_eatigo,
    "covermanager": _probe_covermanager,
}


# ---------------------------------------------------------------------------
# fill_from_units — ported from spike-013 assemble.py
# ---------------------------------------------------------------------------

def fill_from_units(units: list[dict]) -> tuple[int | None, int | None, int]:
    """Infer fill from the service grid.

    Booking-probe doctrine: widgets render only bookable slots, so
    filled = grid_size − offered per date. The grid is the union of all
    slot times across all dated units (including explicitly-filled slots,
    which enlarge the grid to account for waitlist slots).

    Parameters
    ----------
    units : list[dict]
        The 'units' list from a probe result. Each unit has: date, slots list.
        Slots have: time (str), state ('available'|'filled'|...).

    Returns
    -------
    tuple[int|None, int|None, int]
        (filled, N_slots, grid_size)
        Returns (None, None, 0) when there are no dated units or the grid is empty.
    """
    dated = [
        u for u in units
        if isinstance(u.get("slots"), list) and u.get("date") not in (None, "*")
    ]
    if not dated:
        return None, None, 0

    # Build service grid: union of all times across all dated units.
    grid: set[str] = set()
    for u in dated:
        for sl in u["slots"]:
            t = sl.get("time")
            if t:
                grid.add(t)

    grid_size = len(grid)
    if grid_size == 0:
        return None, None, 0

    N = grid_size * len(dated)
    filled = 0
    for u in dated:
        offered = {sl["time"] for sl in u["slots"] if sl.get("state") == "available"}
        filled += grid_size - len(offered)

    return filled, N, grid_size


# ---------------------------------------------------------------------------
# gate_level — ported from spike-016 gate_ladder.py
# ---------------------------------------------------------------------------

_ONLINE_INVENTORY_ENGINES = {
    "sevenrooms", "eatigo", "opentable", "tablecheck",
    "autoreserve", "dishcult", "oddle", "covermanager",
}

_DEPOSIT_TOKENS = ["deposit", "prepay", "prepaid", "down payment", "bank transfer", "50%"]
_DROP_TOKENS = ["lottery", "released in batches", "monthly drop", "timed release", "drops "]


def gate_level(engine: str, note: str, deposit: bool) -> tuple[int, str]:
    """Return the demand-friction gate level for a venue.

    Ladder (higher = harder to book, hypothesised higher demand):
      0  online    — online inventory exists (readable or blocked-here engine)
      1  walk-in   — no reservation needed / walk-ins only
      2  phone/IG  — phone / IG / email / form reservation
      3  deposit   — up-front deposit / prepayment required
      4  lottery   — timed monthly drop / Tock-style release / lottery

    Parameters
    ----------
    engine : str
        The booking engine name (e.g. 'sevenrooms', 'tock', 'phone').
    note : str
        Free-text booking note from city config or corpus (e.g. 'bank transfer required').
    deposit : bool
        Explicit deposit flag (e.g. from SevenRooms slot metadata).

    Returns
    -------
    tuple[int, str]
        (level, label)
    """
    e = (engine or "").lower()
    n = (note or "").lower()
    blob = e + " " + n

    has_deposit = deposit or any(t in blob for t in _DEPOSIT_TOKENS)
    is_drop = ("tock" in e) or any(t in blob for t in _DROP_TOKENS)

    if is_drop:
        return 4, "lottery/drop"
    if any(t in e for t in _ONLINE_INVENTORY_ENGINES):
        return 0, "online"
    if has_deposit:
        return 3, "deposit"
    if "walk-in" in blob or "walk in" in blob:
        return 1, "walk-in"
    return 2, "phone/IG/form"


# ---------------------------------------------------------------------------
# classify — channel assignment + off-platform honesty (BOOK-03)
# ---------------------------------------------------------------------------

def classify(engine: str, units: list[dict], city_config: dict) -> dict:
    """Assign channel, g_i, fill, and off_platform flag for a venue.

    Uses city_config['booking_platforms']['readable_engines'] and
    'online_engines' to determine channel:

      readable  — engine in readable_engines; fill computed from units
      blocked-here — engine in online_engines but NOT readable; g_i=0; fill=None (BOOK-03)
      online-noslots — readable engine with no usable dated slots
      gated     — engine not in online_engines (phone/walk-in/lottery); g_i=1; off_platform=True

    HONESTY RAIL: blocked-here and gated venues NEVER get a fabricated fill.
    fill=None is the signal: "we have no direct demand observation for this venue." (BOOK-03)

    Parameters
    ----------
    engine : str
        Booking engine name.
    units : list[dict]
        Units list from probe_venue (may be empty for gated/blocked venues).
    city_config : dict
        Full city config from load_city() — must contain 'booking_platforms'.

    Returns
    -------
    dict
        Per-venue booking record:
        { engine, channel, g_i, filled, N_slots, grid_size, off_platform }
    """
    bp = city_config.get("booking_platforms", {})
    online_engines = set(bp.get("online_engines", []))
    readable_engines = set(bp.get("readable_engines", []))

    e = (engine or "").lower()
    is_online = e in online_engines
    is_readable = e in readable_engines

    if is_readable:
        # Attempt fill computation
        filled, N_slots, grid_size = fill_from_units(units)
        if N_slots:
            channel = "readable"
        else:
            channel = "online-noslots"
        return {
            "engine": engine,
            "channel": channel,
            "g_i": 0,
            "filled": filled,
            "N_slots": N_slots,
            "grid_size": grid_size,
            "off_platform": False,
        }
    elif is_online:
        # Online engine but not readable (anti-bot or unsupported) — fill MISSING (BOOK-03)
        return {
            "engine": engine,
            "channel": "blocked-here",
            "g_i": 0,
            "filled": None,   # honesty rail: never fabricate
            "N_slots": None,
            "grid_size": 0,
            "off_platform": False,
        }
    else:
        # Not in any online set — phone / walk-in / lottery — off-platform (BOOK-03)
        return {
            "engine": engine,
            "channel": "gated",
            "g_i": 1,
            "filled": None,   # honesty rail: never fabricate
            "N_slots": None,
            "grid_size": 0,
            "off_platform": True,
        }


# ---------------------------------------------------------------------------
# probe_venue — dispatch + graceful degradation
# ---------------------------------------------------------------------------

def probe_venue(engine: str, identifier: str) -> dict:
    """Dispatch an HTTP availability read for *engine* / *identifier*.

    Looks up the prober in PROBERS and calls it. Unknown engines return a
    gated/off_platform record (no crash) — the caller continues the run.

    Parameters
    ----------
    engine : str
        Platform name (e.g. 'sevenrooms', 'eatigo', 'covermanager').
    identifier : str
        Engine-specific venue identifier (slug, branch_id, etc.).

    Returns
    -------
    dict
        The prober's units dict on success, or an error/empty-units dict if
        the engine is unknown or the probe raises an exception.
    """
    e = (engine or "").lower()
    prober = PROBERS.get(e)
    if prober is None:
        # Unknown engine — flag as off-platform; no crash (BOOK-02 contract)
        return {
            "engine": engine,
            "error": f"unknown engine '{engine}' — not in PROBERS",
            "units": [],
        }
    try:
        return prober(identifier)
    except Exception as exc:
        return {
            "engine": engine,
            "error": str(exc),
            "units": [],
        }


# ---------------------------------------------------------------------------
# Per-corpus booking runner
# ---------------------------------------------------------------------------

def run_booking(
    venues_map: dict[str, dict],
    city_config: dict,
    *,
    verbose: bool = True,
) -> list[dict]:
    """Run booking probes for all venues in *venues_map*.

    Parameters
    ----------
    venues_map : dict[str, dict]
        { "venue-slug": {"engine": str, "identifier": str}, ... }
        Venues absent from the map are flagged gated/off_platform with fill None.
    city_config : dict
        Full city config from load_city() — must contain 'booking_platforms'.
    verbose : bool
        Print FILL EVIDENCE summary to stdout (spike-026 proof-of-live-read output).

    Returns
    -------
    list[dict]
        Per-venue booking records with slug, engine, channel, g_i, filled,
        N_slots, grid_size, off_platform.
    """
    records: list[dict] = []
    readable_evidence: list[dict] = []
    off_platform_count = 0

    for slug, info in venues_map.items():
        engine = info.get("engine", "")
        identifier = info.get("identifier", "")

        if not engine:
            # No engine info -> treat as off-platform
            rec = {
                "slug": slug,
                "engine": "",
                "channel": "gated",
                "g_i": 1,
                "filled": None,
                "N_slots": None,
                "grid_size": 0,
                "off_platform": True,
            }
            records.append(rec)
            off_platform_count += 1
            continue

        units_result = probe_venue(engine, identifier)
        units = units_result.get("units", [])

        channel_rec = classify(engine, units, city_config)
        channel_rec["slug"] = slug

        # Count dated units returned and total offered slots (fill evidence)
        dated_units = [u for u in units if u.get("date") not in (None, "*")]
        total_offered = sum(
            len([s for s in u.get("slots", []) if s.get("state") == "available"])
            for u in dated_units
        )

        if channel_rec["channel"] == "readable" and channel_rec["N_slots"]:
            readable_evidence.append({
                "slug": slug,
                "engine": engine,
                "n_dates": len(dated_units),
                "total_offered": total_offered,
                "filled": channel_rec["filled"],
                "N_slots": channel_rec["N_slots"],
                "grid_size": channel_rec["grid_size"],
                "fill_rate": (
                    channel_rec["filled"] / channel_rec["N_slots"]
                    if channel_rec["N_slots"] else None
                ),
            })

        if channel_rec["off_platform"] or channel_rec["channel"] in ("gated", "blocked-here"):
            off_platform_count += 1

        records.append(channel_rec)

    if verbose:
        _print_fill_evidence(readable_evidence, off_platform_count, len(records))

    return records


def _print_fill_evidence(
    readable: list[dict],
    off_platform_count: int,
    total: int,
) -> None:
    """Print FILL EVIDENCE summary — spike-026 proof-of-live-read output."""
    print("\n=== FILL EVIDENCE (HTTP booking probe) ===")
    if readable:
        print(f"{'venue':28s} {'engine':12s} {'dates':5s} {'offered':7s} {'fill':5s}")
        print("-" * 65)
        for ev in sorted(readable, key=lambda r: -(r.get("fill_rate") or 0.0)):
            fr = ev.get("fill_rate")
            fr_str = f"{fr:.2f}" if fr is not None else "n/a"
            print(
                f"{ev['slug'][:28]:28s} {ev['engine'][:12]:12s} "
                f"{ev['n_dates']:5d} {ev['total_offered']:7d} {fr_str:5s}"
            )
    else:
        print("  (no readable venues with fill observation)")
    print(f"\nOff-platform / no-signal venues: {off_platform_count}/{total}")
    print("==========================================\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="booking.py",
        description=(
            "Read live booking availability (HTTP-only, read-only) for a configured city.\n"
            "Writes per-venue booking JSON to --out (default: <cwd>/<city-slug>-booking.json).\n"
            "Prints a FILL EVIDENCE summary (dates returned, offered slots, fill rate per venue).\n"
            "\n"
            "HARD CONSTRAINTS: HTTP-only (no browser), strictly READ-ONLY (no booking writes)."
        ),
    )
    parser.add_argument(
        "--city",
        required=True,
        metavar="CITY",
        help="City name or slug (e.g. 'manila'). Must match a file in cities/<slug>.json.",
    )
    parser.add_argument(
        "--venues",
        required=True,
        metavar="MAP_JSON",
        help=(
            'Path to venue-engine map JSON. '
            'Shape: {"slug": {"engine": "sevenrooms", "identifier": "..."}, ...}'
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help=(
            "Output file path. Defaults to <cwd>/<city-slug>-booking.json. "
            "Never built from venue data (T-04-03)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Load city config
    try:
        config = load_city(args.city)
    except UnknownCityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    city_slug = config["slug"]

    # Load venue-engine map
    try:
        with open(args.venues, encoding="utf-8") as fh:
            venues_map = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not load venues map '{args.venues}': {exc}", file=sys.stderr)
        return 1

    if not isinstance(venues_map, dict):
        print(
            f"ERROR: venues map must be a JSON object, got {type(venues_map).__name__}",
            file=sys.stderr,
        )
        return 1

    # Resolve output path — default to CWD/<slug>-booking.json
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = Path(os.getcwd()) / f"{city_slug}-booking.json"

    # Run probes
    records = run_booking(venues_map, config, verbose=True)

    # Write booking JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)

    print(f"city:    {config['city']}")
    print(f"venues:  {len(records)} booking records")
    print(f"output:  {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
