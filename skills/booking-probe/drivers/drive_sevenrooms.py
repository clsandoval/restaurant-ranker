#!/usr/bin/env python3
"""SevenRooms agent-browser clickthrough driver.

Codifies the verified recipe (booking-probe/recipes/sevenrooms.md). Drives the
real booking widget via the `agent-browser` CLI only (no Playwright). All
interaction is eval-based because SevenRooms hides results in shadow DOM.
READ-ONLY: reads the offered slot list, never clicks a slot / confirm.

Usage (from booking-probe/clickthrough/):
  python3 drive_sevenrooms.py --test                      # one unit self-check
  python3 drive_sevenrooms.py --venue-id sr-lenormandie \
      --name "Anne-Sophie Pic at Le Normandie" \
      --url https://www.sevenrooms.com/reservations/lenormandie/ \
      --parties 2,4,6                                      # full June grid
"""
import argparse
import json
import subprocess
import time
from datetime import date
from pathlib import Path

SESSION = "lakbai-bkk-booking"  # overridable via --session (one per restaurant = autopilot model)
# Output to the CALLER'S CWD (lakbai rule: never hard-code paths). Override with --outdir.
OUTDIR = Path.cwd() / "booking-probe-data" / "clickthrough"
JUNE = [f"2026-06-{d:02d}" for d in range(1, 31)]


def ab(*args, timeout=90):
    """Run an agent-browser CLI command, return stdout (last line)."""
    cmd = ["agent-browser", "--session", SESSION, *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "").strip()


def ab_eval(js, timeout=90):
    out = ab("eval", js, timeout=timeout)
    # agent-browser prints the JS return value, often as a JSON string literal
    line = out.splitlines()[-1] if out else ""
    line = line.strip()
    try:
        v = json.loads(line)
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return v
        return v
    except json.JSONDecodeError:
        return line


# --- eval payloads -----------------------------------------------------------

# generic shadow-DOM-piercing click-by-predicate, plus the specific steps
_HELPERS = r"""
function _walkClick(pred){
  let hit=null;
  const w=(r)=>{ if(!r||!r.querySelectorAll)return;
    for(const el of r.querySelectorAll('*')){ if(!hit&&pred(el)){hit=el;return;} if(el.shadowRoot)w(el.shadowRoot); } };
  w(document); if(hit){ hit.click(); return true; } return false;
}
function _txt(el){ return (el.textContent||'').trim(); }
function _g(el,a){ return (el.getAttribute&&el.getAttribute(a))||''; }
// combined signature: some buttons hold their name in data-test, others in aria-label/title/text
function _dt(el){ return [_g(el,'data-test'),_g(el,'data-testid'),_g(el,'aria-label'),_g(el,'title'),_txt(el).slice(0,40)].join(' | '); }
"""


def js(body):
    return "(()=>{" + _HELPERS + body + "})()"


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def probe_unit(d, party):
    """One (date, party) probe. Returns dict {status, slots, note}."""
    y, m, dd = map(int, d.split("-"))
    month_name = date(y, m, dd).strftime("%B")          # "June"
    day_label = f"{month_name} {ordinal(dd)} {y}"        # "June 7th 2026"

    # accept cookies if present (best-effort)
    ab_eval(js(r"_walkClick(el=>el.tagName==='BUTTON'&&/accept all cookies/i.test(_txt(el))); return 'ok';"))
    time.sleep(0.5)
    # open the date calendar: the display button's text ends with 'Date'
    ab_eval(js(r"_walkClick(el=>el.tagName==='BUTTON'&&/Date$/.test(_txt(el))&&_txt(el).length>5&&!/crement/i.test(_dt(el))); return 'ok';"))
    time.sleep(1.0)
    # step months forward until the target month's day button is present (max 12 hops)
    for _ in range(12):
        present = ab_eval(js(
            r"let f=false;const w=(r)=>{if(!r||!r.querySelectorAll)return;for(const el of r.querySelectorAll('*')){"
            r"if(/" + day_label.replace(" ", r"\s+") + r"/.test(_dt(el))){f=true;}if(el.shadowRoot)w(el.shadowRoot);}};"
            r"w(document);return f;"))
        if present is True:
            break
        ab_eval(js(r"_walkClick(el=>/increment month/i.test(_dt(el))); return 'ok';"))
        time.sleep(0.6)
    # click the target day cell (SevenRooms days are <td> with the date in aria-label)
    clicked = ab_eval(js(
        r"return _walkClick(el=>{const al=(el.getAttribute&&el.getAttribute('aria-label'))||'';"
        r"return new RegExp('" + day_label.replace(" ", r"\\s+") + r"').test(al);});"))
    time.sleep(1.0)
    if clicked is not True:
        return {"status": "unresolved", "slots": [], "note": f"could not click day {day_label}"}

    # set guests: click 'increment Guests' (party-2) times (default is 2)
    for _ in range(max(0, party - 2)):
        ab_eval(js(r"_walkClick(el=>/increment Guests/i.test(_dt(el))); return 'ok';"))
        time.sleep(0.4)

    # click the shadow-DOM search button
    ab_eval(js(r"return _walkClick(el=>/sr-search-button/.test(_dt(el))||(el.tagName==='BUTTON'&&/^Search$/.test(_txt(el))));"))
    time.sleep(8.0)

    # read the result slots from body innerText
    res = ab_eval(js(
        r"const body=(document.body.innerText||'').replace(/\s+/g,' ');"
        r"const re=/(\d{1,2}:\d{2})\s*(Lunch|Dinner|Brunch|Breakfast)?/g;let m,slots=[];"
        r"const after=body.split(/Select a time/i).pop()||body;"
        r"while((m=re.exec(after))){slots.push({time:m[1],meal:m[2]||''});}"
        r"const noavail=/no .{0,30}(availab|times|tables)|fully committed|not available|other dates/i;"
        r"return JSON.stringify({slots:slots, raw:after.slice(0,300)});"))
    if not isinstance(res, dict):
        return {"status": "unresolved", "slots": [], "note": f"unreadable result: {str(res)[:80]}"}
    # de-dupe by TIME (prefer the entry that carries a meal label — drops the echoed
    # request-time which leaks in with an empty meal).
    by_time = {}
    for s in res.get("slots", []):
        t = s["time"]
        if t not in by_time or (not by_time[t]["meal"] and s["meal"]):
            by_time[t] = s
    slots = [by_time[t] for t in sorted(by_time, key=lambda x: (int(x.split(":")[0]), int(x.split(":")[1])))]
    if slots:
        return {"status": "available", "slots": slots, "note": ""}
    return {"status": "full", "slots": [], "note": "no slots offered for this date"}


RESOLVED = {"available", "full"}


def run_venue(venue_id, name, url, parties, dates):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTDIR / f"{venue_id}.json"
    # resume: load existing units, keep resolved ones, re-probe unresolved/error/missing
    units = {}
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            for u in prev.get("units", []):
                units[(u["date"], u["party_size"])] = u
        except (json.JSONDecodeError, KeyError):
            pass
    record = {"venue_id": venue_id, "name": name, "platform": "sevenrooms",
              "url": url, "method": "agent-browser-clickthrough", "units": []}

    def flush():
        record["units"] = [units[k] for k in sorted(units)]
        out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    todo = [(d, p) for d in dates for p in parties
            if units.get((d, p), {}).get("status") not in RESOLVED]
    skipped = len(dates) * len(parties) - len(todo)
    print(f"{venue_id}: {len(todo)} units to probe, {skipped} already resolved (resume)")
    for d, p in todo:
        ab("open", url)
        time.sleep(4.0)
        try:
            r = probe_unit(d, p)
        except subprocess.TimeoutExpired:
            r = {"status": "error", "slots": [], "note": "agent-browser timeout"}
        units[(d, p)] = {"date": d, "party_size": p, **r}
        print(f"  {venue_id} {d} p{p} -> {r['status']} ({len(r['slots'])} slots) {r['note']}")
        flush()
    flush()
    resolved = sum(1 for u in units.values() if u["status"] in RESOLVED)
    print(f"wrote {out_path} — {resolved}/{len(units)} resolved")


def main():
    global SESSION, OUTDIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue-id")
    ap.add_argument("--name")
    ap.add_argument("--url")
    ap.add_argument("--parties", default="2,4,6")
    ap.add_argument("--dates", default="", help="comma dates, default full June")
    ap.add_argument("--session", default=SESSION)
    ap.add_argument("--outdir", default="", help="output dir (default ./booking-probe-data/clickthrough)")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    SESSION = a.session
    if a.outdir:
        OUTDIR = Path(a.outdir)
    if a.test:
        ab("open", "https://www.sevenrooms.com/reservations/lenormandie/")
        time.sleep(4)
        r = probe_unit("2026-06-07", 2)
        print(json.dumps(r, indent=2))
        print("SELF-CHECK:", "PASS" if r["status"] == "available" and len(r["slots"]) >= 5 else "FAIL")
        return
    dates = [x for x in a.dates.split(",") if x] or JUNE
    parties = [int(x) for x in a.parties.split(",")]
    run_venue(a.venue_id, a.name, a.url, parties, dates)


if __name__ == "__main__":
    main()
