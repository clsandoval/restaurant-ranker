#!/usr/bin/env python3
"""Compute the per-slot FILL DISTRIBUTION for clickthrough venue JSONs.

For each venue, the real signal is which seating times are taken vs open per date.
Two sources (see SKILL.md "Slot-fill distribution"):
  - if a slot already carries state=available|filled (widget rendered greyed slots), keep it.
  - else infer: service_grid = union of every time the venue offers across the probed window;
    per available/full date, filled = service_grid - offered_that_date.

Augments each unit with `slots:[{time, meal, state}]` over the FULL grid + a `service_grid` field,
and recomputes the day `status` rollup. Leaves unresolved/gated/no-slots/error units untouched.

Usage:
  python3 finalize_fill.py <dir-of-venue-jsons> [--write]   # default dry-run prints summary
"""
import argparse
import json
import sys
from pathlib import Path


def time_key(t):
    try:
        h, m = t.replace("am", "").replace("pm", "").strip().split(":")
        base = int(h) % 12 * 60 + int(m)
        if "pm" in t.lower():
            base += 720
        return base
    except Exception:
        return 0


def process(venue):
    units = venue.get("units", [])
    # service grid = union of offered times across dates that actually had offers
    grid = set()
    for u in units:
        if u.get("status") in ("available", "full"):
            for s in u.get("slots", []):
                if s.get("time") and s.get("state") != "filled":
                    grid.add(s["time"])
    grid = sorted(grid, key=time_key)
    venue["service_grid"] = grid
    if not grid:
        return venue, 0
    n_dates = 0
    for u in units:
        if u.get("status") not in ("available", "full"):
            continue
        offered = {s["time"] for s in u.get("slots", []) if s.get("state") != "filled"}
        meal_of = {s["time"]: s.get("meal", "") for s in u.get("slots", [])}
        full = []
        for t in grid:
            full.append({"time": t, "meal": meal_of.get(t, ""),
                         "state": "available" if t in offered else "filled"})
        u["slots"] = full
        avail = sum(1 for s in full if s["state"] == "available")
        u["status"] = "available" if avail else "full"
        u["open_slots"] = avail
        u["filled_slots"] = len(full) - avail
        n_dates += 1
    return venue, n_dates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    d = Path(a.dir)
    files = sorted(d.glob("*.json"))
    for f in files:
        try:
            venue = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if "units" not in venue:
            continue
        venue, n = process(venue)
        grid = venue.get("service_grid", [])
        # per-date fill summary
        lines = []
        for u in venue.get("units", []):
            if u.get("status") in ("available", "full") and "open_slots" in u:
                lines.append(f"{u['date']}: {u['open_slots']}/{len(grid)} open")
        print(f"\n{venue.get('venue', f.stem)} ({venue.get('engine','?')}) — service grid {len(grid)} slots: {grid}")
        for ln in lines[:32]:
            print("   ", ln)
        if a.write and n:
            f.write_text(json.dumps(venue, ensure_ascii=False, indent=2), encoding="utf-8")
    if a.write:
        print("\n[written in place]")
    else:
        print("\n[dry-run — pass --write to augment the files]")


if __name__ == "__main__":
    main()
