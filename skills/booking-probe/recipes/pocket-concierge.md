# Recipe: Pocket Concierge ✅ verified

Read-only availability via CloakBrowser clickthrough. Pocket Concierge (`pocket-concierge.jp`,
Amex-owned) is a major Japan fine-dining engine — and a **readable mirror for many login-walled
OMAKASE venues** (see engine-routing.md). Verified 2026-05-30 (Narisawa: real open/full/closed mix).

URL: `pocket-concierge.jp/<lang>/restaurants/<id>`.

## Anti-bot — use CloakBrowser (NOT plain agent-browser)
Cloudflare-walls agent-browser's plain Chrome (title stuck "Attention Required! | Cloudflare").
Use **CloakBrowser stealth Chromium** (Playwright API or via CDP — see clickthrough-technique.md):
`launch(headless=True, locale=<lang>, timezone="Asia/Tokyo")`, `goto(url, wait_until="domcontentloaded")`
— do NOT use `networkidle` (a persistent Stripe iframe never lets it settle). Wait ~6s for React
hydration (initial `body.innerText` is footer-only until then).

## Steps (one venue × date × party)
1. Open the venue page (CloakBrowser); wait ~6s for hydration.
2. Open the date picker: click the BUTTON whose text matches `/^(Sunday|Monday|...|Saturday),/`
   (aria-label "Select date"). Month grid appears; navigate via aria-label "Next Month"/"Previous Month".
3. **Day-button state = first signal:** day cells are BUTTONs (numeric text, class `rounded-full`).
   `disabled` = closed / not bookable (e.g. regular holidays). Enabled = selectable.
4. **Authoritative per-date read: click the enabled day, then read `body.innerText` tail** — the
   selected-date header is followed by EITHER:
   - **"Instant Reservation"** + concrete time slots ("12:00 PM") → `available` (record the slots).
   - **"Waitlist"** + "joining the Waitlist does not guarantee your reservation" (only an arrival-time
     *window*, not real seats) → `full` / booked out.
   This **Instant-vs-Waitlist** distinction is the key classification axis, unique to this engine.
5. Lunch / Dinner are **tabs** — click "Dinner" to read the dinner slot set separately.
6. Calendar closes on day-selection → re-open + re-navigate per date. STOP at the slot read;
   never click Reserve / Join Waitlist / payment.

## Classification
- "Instant Reservation" + times → `available` · "Waitlist" banner → `full` · day-button `disabled`
  → `no-slots` (closed) · global "No seats available" + all-disabled (waitlist-only venue, e.g. Den)
  → `full` every date with a "waitlist / no online inventory" note.
- Party is chosen AFTER a date → on sold-out venues party can't vary (probe party 2; party-relevant
  only where the post-date flow exposes party-dependent slots).

## Cases handled (ledger)
- ✅ Narisawa (Tokyo) — real mix: open (Jun 10/13, Instant lunch 12:00) vs booked-out (Jun 6/20/24,
  Waitlist) vs closed (Jun 7 Sun, day disabled). Cloudflare → CloakBrowser. Read as OMAKASE mirror.
- ✅ Den (Tokyo) — waitlist-only venue: every June day disabled / no inventory → all `full`.
- ⬜ A venue exposing real Dinner Instant slots (only lunch Instant seen so far).
- ⬜ Party-dependent availability post-date (not yet observed).
