# agent-browser clickthrough technique

The core method for reading availability from booking widgets. Read-only (see THE READ-ONLY LAW
in SKILL.md). agent-browser version tested: 0.27.0.

## The loop

```bash
agent-browser --session lakbai-<venue-slug> open <reservation-url>
agent-browser --session lakbai-<venue-slug> snapshot -i -c -d 4   # interactive tree
# → reason over the tree, pick @eN refs
agent-browser --session lakbai-<venue-slug> click @eN             # or fill / select / eval
agent-browser --session lakbai-<venue-slug> snapshot -i -c -d 4   # MANDATORY re-snapshot
```

Refs (`@eN`) are valid only within ONE snapshot. Re-snapshot (or re-query via eval) after every
click/fill/state change. Default snapshot flags: `-i -c -d 4`.

## The shadow-DOM problem (the #1 gotcha)

Heavy widgets (SevenRooms, and others) render their form controls in the accessibility tree
(snapshot sees them) but render the **result slots inside shadow-DOM web components** the
snapshot CANNOT see. Symptom: after clicking Search the snapshot still shows only the form, and
`snapshot -c` returns a near-empty tree.

**Fix: use `agent-browser eval` to pierce shadow roots** — both to click buried controls and to
read results from `document.body.innerText`.

Recursive shadow-walk helpers (reuse across platforms):

```javascript
// click the first element matching a predicate, descending into shadow roots
function _walkClick(pred){
  let hit=null;
  const w=(r)=>{ if(!r||!r.querySelectorAll)return;
    for(const el of r.querySelectorAll('*')){ if(!hit&&pred(el)){hit=el;return;} if(el.shadowRoot)w(el.shadowRoot); } };
  w(document); if(hit){ hit.click(); return true; } return false;
}
// COMBINED SIGNATURE — name lives in a different attribute per platform; never match just one.
// A non-empty data-test will MASK the aria-label if you only read data-test.
function _sig(el){
  const g=(a)=>(el.getAttribute&&el.getAttribute(a))||'';
  return [g('data-test'),g('data-testid'),g('aria-label'),g('title'),(el.textContent||'').trim().slice(0,40)].join(' | ');
}
```

**Guard className matching:** an element's `className` can be an `SVGAnimatedString` (on SVG nodes),
so `el.className.includes(...)` throws `TypeError: includes is not a function`. If you must match a
class, read it safely: `const cn = (el.getAttribute && el.getAttribute('class')) || ''`. The `_sig`
helper above already avoids this (it uses `getAttribute` + `textContent`, never `.className`).

Read slots from body text after the search fires (waits ~8s for the result render):

```javascript
const body=(document.body.innerText||'').replace(/\s+/g,' ');
const after=body.split(/Select a time/i).pop()||body;   // anchor on the results header
const re=/(\d{1,2}:\d{2})\s*(Lunch|Dinner|Brunch|Breakfast)?/g; let m,slots=[];
while((m=re.exec(after))) slots.push({time:m[1], meal:m[2]||''});
const noavail=/no .{0,30}(availab|times|tables)|fully committed|not available/i.test(body);
```

Then **dedup by time** (prefer the entry that carries a meal label — drops the widget's echoed
request-time which leaks in with an empty meal).

## Status classification

| Outcome | status |
|---|---|
| Slots parsed | `available` (one record per slot) |
| Gates passed, day genuinely empty / "no availability" message | `full` |
| Day closed / outside booking window | `no-slots` |
| A required gate couldn't be passed (party unselectable, T&C won't tick) | `gated` |
| Widget shape unrecognised / result unreadable / nav timeout | `unresolved` (record WHAT blocked) |
| CLI/process error | `error` |

## Confidence checks (do these before trusting a read)

- Verify the result header echoes the requested date + party ("Sun, 7 Jun · 2 Guests") before
  trusting the slot list — otherwise you may be reading a stale/other date.
- Cross-check the day-grid label ("Available"/"Sold Out") against the slot read.
- Vary across dates: if EVERY date returns an identical slot set, suspect you're reading a static
  default, not live data. Real data varies by date/venue.

## Anti-bot fallback — CloakBrowser over CDP (verified)

agent-browser's plain Chrome-for-Testing passed SevenRooms / Chope / TableCheck fine. But some
engines hard-block it (OMAKASE / `omakase.in` → Cloudflare "Sorry, you have been blocked"). An
empty/stripped tree from a normally-rich page is an **anti-bot signal, not "no availability"** —
check `get title` / `get url` first.

When blocked, drive **CloakBrowser stealth Chromium via CDP** instead of agent-browser's own Chrome:

```bash
# 1. launch stealth Chromium with remote debugging (WSL/no-X needs --headless=new)
~/.cloakbrowser/chromium-<ver>/chrome --headless=new \
  --remote-debugging-port=9333 --user-data-dir=$(mktemp -d) about:blank &
# 2. attach agent-browser to it — then snapshot/eval/click exactly as normal
agent-browser --session <s> connect 9333
```

This passes Cloudflare and renders real content. Same read-only loop applies after connecting.

**Caveat (verified 2026-06-03): CDP-attach may run UNCLOAKED.** With the `cloakbrowser` npm package,
the stealth is injected at the playwright **context** level by `cb.launch()`/`humanizeBrowser` —
NOT via chrome args (`buildLaunchOptions()` returns none). So `chrome --remote-debugging-port` +
`agent-browser connect` gets a vanilla browser. The CDP recipe above works for engines whose
stealth need is satisfied by the stealth Chromium *binary* (TLS/UA/JA3 — clears Cloudflare:
OMAKASE, TableCheck). For engines that need the injected JS patches, drive `cb.launch()` natively
in node. **PerimeterX "Press & Hold" behavioral CAPTCHA (Inline) beats BOTH** from a datacenter IP —
that's an anti-bot block → `unresolved`, never automate the gesture. Native `cb.launch()` needs
`playwright-core` installed as a peer dep.

**Cert-authority errors:** some venue sites chain to a root Chrome-for-Testing lacks →
`ERR_CERT_AUTHORITY_INVALID` (the cert is valid, the browser just doesn't trust the chain). Fix:
fully `close` + `pkill -f agent-browser-chrome`, then reopen with `AGENT_BROWSER_IGNORE_HTTPS_ERRORS=1`
set — a running daemon ignores the flag, so it must be restarted.

**agent-browser daemon contention:** overlapping/auto-backgrounded CLI calls can fail with
`Resource temporarily unavailable (os error 11)`. Fix: `agent-browser --session <s> close` +
`pkill -f agent-browser-chrome`, then re-issue as a single foreground command. **Serialize calls
within one session** — don't stack overlapping invocations.

## Login-walled calendars = `gated`, never bypass

Some engines (OMAKASE) hide the per-date slot calendar behind an **account login** — the
"reserve" link 302-redirects anonymous users to `/sign_in`. There is no anonymous slot view.
Resolve these as **`gated`** with the blocker noted. **Do NOT create an account / log in to get
past it** — that crosses into the booking flow and violates the READ-ONLY LAW. Still capture what
the public page DOES expose (active reservation window, fees, closed days) into the record.
