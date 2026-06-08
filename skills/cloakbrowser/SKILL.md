---
name: cloakbrowser
description: >
  Use when a website you need to READ is walled by anti-bot defenses — Cloudflare
  Turnstile, DataDome, ALTCHA proof-of-work, PerimeterX "Press & Hold", CDP/headless
  detection, or container TLS-MITM — and a plain HTTP/JSON request or ordinary headless
  browser gets blocked, 403'd, or served a challenge. Launches a stealth Chromium via
  CloakBrowser (patchright + xvfb + humanize) that clears these walls, then reads the
  page's own availability/JSON read-only. This is the escalation tier behind the
  booking-probe skill's per-engine recipes, AND the playbook for cracking a NEW booking
  engine that has no recipe yet. Read-only: read the data, never submit or transact.
---

# CloakBrowser — anti-bot read escalation

When a site won't give up its data to `curl`/`urllib` or to a vanilla headless browser —
it 403s, hangs on a CAPTCHA, serves a Turnstile/DataDome interstitial, or the container's
TLS interception breaks Chromium — escalate to **CloakBrowser**: a stealth Chromium with
CDP-signal suppression (patchright), a virtual display (xvfb so the browser runs *headed*,
which most anti-bot scoring requires), and humanized input (Bézier mouse paths + realistic
timing). It clears the walls that stop ordinary automation, and you read the site's own
network responses or rendered DOM.

This skill is the **escalation tier** under `../booking-probe/` — its per-engine recipes
(`recipes/<engine>.md`) call this technique. It is also the **generalization playbook**:
when you hit an engine with no recipe, this is how you figure it out from scratch.

## THE READ-ONLY LAW (non-negotiable)

**Read the data only. NEVER submit, confirm, complete, pay, or transact.**

CloakBrowser exists to *reach and read* — slot lists, availability JSON, prices, calendars.
Push through gates that only reveal data (accept cookies/T&C, set party size, pick a default
option). Then STOP. Clicking a final "Book"/"Confirm"/"Checkout"/"Submit"/"Pay" control, or
entering payment/deposit details, is a FAILURE — it creates a real transaction. "Just to see
the next screen" / "I'll cancel after" / "fake data, won't submit" are all the same mistake:
back out. The data you already read is the result.

## A 403 / challenge is NOT a verdict — it means WRONG TIER. Do not rationalize.

The most common failure is running **vanilla CloakBrowser** (headless, no patchright, no xvfb)
against a strong wall, getting a `403`/challenge, and concluding the venue is "unautomatable"
or "architecturally gated." **That conclusion is almost always wrong.** A 403 from a light
config means you are below the tier the wall demands — escalate, don't surrender.

Worked example (real): **TableCheck new-React (Sorn, Nusara, Gaa) returns `403 Forbidden` to
headless/plain stealth** because it sniffs CDP and sits behind Cloudflare-grade detection. The
verified recipe reads it fine with **`backend="patchright"` (CDP suppression) + `headless=False`
under `xvfb`** (proven on ADHOC Bangkok, party 2). Same venue: 403 vanilla → readable with the
right tier. The wall didn't change; the tier did.

Before you ever write "blocked" / "impossible" / "gated by design", confirm ALL of:
- [ ] Tried the HTTP/JSON endpoint directly (tier 0)?
- [ ] Ran **headed under xvfb** (`headless=False`), not headless?
- [ ] Used `backend="patchright"` for CDP/Cloudflare/React walls (tiers 3–4)?
- [ ] Added `ignore_https_errors=True` + `--ignore-certificate-errors` (tier 5, on MA)?
- [ ] Distinguished a **tooling 403** from a **genuine gate** (lottery / phone-only / prepay)?

Only a venue that is *genuinely* lottery/phone/prepay (e.g. Sorn's lottery) is honestly
`unresolved`/`gated`. A 403 you got from a misconfigured browser is a TODO, not a finding.
Reporting a wrong-tier 403 as "the accurate representation of the ecosystem" is the
rationalization trap — and it is checkable: the data may already exist (e.g. 55 Bangkok venues
read live via Chope/Eatigo/HungryHub sit in `./bangkok-booking-probe/clickthrough/`).

## Decision ladder — escalate only as far as the wall demands

Cheapest first. Do NOT launch a browser when an HTTP read works.

| Tier | Wall you're facing | Tool | Notes |
|---|---|---|---|
| 0 | None — public JSON/HTML endpoint | plain `urllib`/`curl` | Fastest. Most "blocked" claims skip this. Find the XHR the page calls and hit it directly. |
| 1 | ALTCHA proof-of-work (Superb/Formitable) | CloakBrowser **headless** stealth | ALTCHA auto-solves in the browser; no patchright/xvfb needed. |
| 2 | DataDome (OpenTable) | CloakBrowser + **humanize** | `dapi/fe/human` returns 200 under humanized behavior; no patchright needed. |
| 3 | Cloudflare Turnstile (DinnerBooking/easyTable) | CloakBrowser + **patchright + xvfb (headed)** | Click the `.cf-turnstile` bounding box; token issues in <1s. |
| 4 | CDP / headless detection (TableCheck new-React, OMAKASE) | CloakBrowser + **patchright (CDP-suppressed) + xvfb** | The React widgets sniff CDP; patchright is the key. |
| 5 | Container TLS-MITM (Managed Agents) | add `ignore_https_errors=True`, `args=["--ignore-certificate-errors"]` | Clears the cert-authority break that fails plain Chromium navigation on MA. |
| 6 | PerimeterX "Press & Hold" (Inline); AWS WAF (Zenchef); full-prepay (Tock) | — | **Walled from datacenter IPs.** Needs a residential IP / warmed session, or there is no read-without-pay. Record `unresolved` with the blocker — do NOT fake a read. |

## Setup (once)

```bash
uv pip install --python /tmp/v/bin/python cloakbrowser patchright
/tmp/v/bin/cloakbrowser install        # stealth Chromium (~206 MB)
/tmp/v/bin/patchright install chromium # CDP-signal-suppressed Chromium
command -v xvfb-run || (apt-get update && apt-get install -y xvfb)
```

## The launch recipe (tiers 3–5, the strong preset)

Run **headed under a virtual display** — headless is detectable; xvfb gives you a headed
browser with no physical screen.

```bash
timeout 240 xvfb-run -a -s "-screen 0 1920x1080x24" /tmp/v/bin/python flow.py
```

```python
from cloakbrowser import launch_context

ctx = launch_context(
    headless=False,                       # CRITICAL: headed under xvfb
    humanize=True,                        # Bézier mouse + human timing
    human_preset="careful",               # extended delays for strict anti-bot
    backend="patchright",                 # CDP-signal suppression — the key for tiers 3–4
    ignore_https_errors=True,             # tier 5: container TLS-MITM
    args=["--ignore-certificate-errors"], # tier 5: clears cert-authority break
)
page = ctx.new_page()
```

For tiers 1–2 (ALTCHA / DataDome) drop `backend="patchright"` and you can run
`headless=True` — only escalate to the full headed+patchright preset when a lighter tier
is actually blocked.

## How to read availability (engine-agnostic)

Two complementary reads — capture the JSON if you can, fall back to the rendered grid:

1. **Intercept the availability XHR/fetch (preferred — structured data).** Register a
   response listener before navigating; keep responses whose URL matches an availability
   pattern and whose content-type is JSON. This is the same shape every booking widget
   ultimately renders from.

   ```python
   captured = []
   def on_resp(r):
       try:
           ct = (r.headers or {}).get("content-type", "")
           if AVAIL_RE.search(r.url) and "json" in ct:
               captured.append({"url": r.url, "json": r.json()})
       except Exception:
           pass
   page.on("response", on_resp)
   page.goto(url, wait_until="networkidle", timeout=45000)
   ```

2. **Read the rendered slots from the DOM (fallback).** Heavy widgets render slots in
   **shadow DOM** that the accessibility tree misses. Walk shadow roots recursively via
   `page.evaluate`, or scrape times out of `document.body.innerText` with a time regex.
   Match controls by a **combined signature** (data-test + aria-label + title + text),
   never a single attribute. Re-query after every state change — refs are ephemeral.

Full DOM/shadow technique + gotchas: `../booking-probe/references/clickthrough-technique.md`.

## Cracking an UNKNOWN engine (no recipe yet) — the generalization loop

1. **Identify the wall.** Load the booking URL in the browser; watch the network tab and
   page. Cloudflare interstitial? DataDome `dd` cookies? ALTCHA widget? React app that
   blanks under headless? 403 from an HTTP probe? That tells you the tier above.
2. **Find the data endpoint.** With the widget open, find the XHR that returns slots/times
   (search responses for time strings or `availability`/`times`/`slots`). Note its method,
   params (date, party, venue id), and shape. Often you can replay it directly (tier 0).
3. **Pick the lowest tier that clears the wall.** Try HTTP replay first; escalate only if
   it 403s or needs a token the browser mints.
4. **Read read-only across your date/party grid.** Stop at the slot list.
5. **If it cannot be read** (PerimeterX, WAF, prepay-only), record `unresolved` with the
   exact blocker — never fabricate availability. An honest gap beats a fake datapoint.
6. **Write it down.** Capture the working method as a new `../booking-probe/recipes/<engine>.md`
   (copy `recipes/_TEMPLATE.md`) so the next run inherits it.

## Verified coverage (proven recipes)

| Engine | Wall | Tier | Status |
|---|---|---|---|
| SevenRooms | none (JSON) | 0 | ✅ HTTP-readable |
| Eatigo | none (`__NUXT_DATA__`) | 0 | ✅ HTTP-readable |
| CoverManager | none (JSON) | 0 | ✅ HTTP-readable |
| Superb / Formitable | ALTCHA PoW | 1 | ✅ headless stealth |
| OpenTable | DataDome | 2 | ✅ humanize |
| DinnerBooking / easyTable | Cloudflare Turnstile | 3 | ✅ patchright + xvfb |
| TableCheck (new-React) | CDP detection | 4 | ✅ patchright-CDP |
| Pocket Concierge | CDP | 4 | ✅ patchright |
| Inline | PerimeterX Press&Hold | 6 | ⚠️ datacenter-IP walled → residential/warmed only |
| Zenchef | AWS WAF | 6 | ❌ 403 on API (Apollo-only) |
| Tock | full-prepay, no browse | 6 | ❌ no read-without-pay |

Per-engine step-by-step recipes live in `../booking-probe/recipes/`. Prior DOM/endpoint
knowledge per platform: `../booking-probe/references/platform-knowledge.md`.

## Common mistakes

- **Launching a browser when HTTP would work.** Always try tier 0 first.
- **Running headless against Turnstile/CDP walls.** Those need headed-under-xvfb + patchright.
- **Faking a read after a block.** A wall you can't clear is `unresolved` + blocker note — never a fabricated slot list.
- **Clicking through "just to verify."** The offered slot is the datapoint. Clicking a slot advances to checkout — that's a real booking.
- **Keeping element refs across actions.** Re-query after each state change; refs are ephemeral.
- **Single-attribute element matching.** Match the combined signature (data-test + aria-label + title + text).
