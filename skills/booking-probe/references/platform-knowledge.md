# Per-platform DOM / endpoint knowledge

Hard-won knowledge per platform — widget generations, gates, tokens, sold-out signals. Feeds the
clickthrough recipes. (Originally surfaced via an API-capture spike; the recipes use clickthrough,
but the DOM tokens and gate sequences below transfer directly.)

## Anti-bot escalation tier — CloakBrowser + patchright + xvfb

The shared launch primitive for engines that sit behind an **active** anti-bot challenge —
**Cloudflare Turnstile** (DinnerBooking, easyTable), **ALTCHA** proof-of-work (Superb / Formitable),
**DataDome** (OpenTable). Plain `agent-browser` is **TLS-blocked on Managed Agents** (spike 023), and
plain stealth Chromium does not always clear these active challenges. The recipes
`recipes/dinnerbooking.md`, `recipes/superb.md`, `recipes/opentable.md` all reference this section
instead of re-pasting the launch config; each notes only its per-engine deviation.

CloakBrowser is already the established **Cloudflare escalation rung** (Pocket Concierge, OMAKASE).
This adds the **patchright + xvfb** variant for the ACTIVE-challenge engines: `backend="patchright"`
(CDP-signal suppression) is THE key that makes Turnstile and DataDome pass, and
`args=["--ignore-certificate-errors"]` clears the container TLS-MITM.

**Setup (in addition to the base venv):**
```bash
uv pip install --python /tmp/v/bin/python cloakbrowser patchright
/tmp/v/bin/cloakbrowser install        # stealth Chromium (~206 MB)
/tmp/v/bin/patchright install chromium # CDP-signal-suppressed Chromium
which xvfb-run || (apt-get update && apt-get install -y xvfb)
```

**Run HEADED under a virtual display** — headless is flaky for Turnstile / DataDome:
```bash
timeout 240 xvfb-run -a -s "-screen 0 1920x1080x24" /tmp/v/bin/python flow.py
```

**Launch pattern** — native cloakbrowser `launch_context` (NOT `sync_playwright`, NOT `launch()`
which dies under asyncio in a loop). Run as a plain SYNC script:
```python
from cloakbrowser import launch_context
ctx = launch_context(
    headless=False, humanize=True, human_preset="careful",
    backend="patchright",                 # CDP-signal suppression — THE key to Turnstile/DataDome
    ignore_https_errors=True,
    args=["--ignore-certificate-errors"], # clears the container TLS-MITM
)
page = ctx.new_page()
```

**Read-only invariant (non-negotiable):** reading the calendar IS the probe. Never POST / confirm /
book — capture the slot/dates response off the network or DOM and STOP.

## SevenRooms
- `/reservations/<slug>/` widget. Form controls (date/guests/time/search) in a11y tree; **result
  slots in shadow DOM** → eval-read `body.innerText`.
- Day cells are `<td>` with date in `aria-label` ("Sunday, June 7th 2026, Available").
- Search button: `data-test=sr-search-button` (buried; eval-click). Month nav: `aria-label`
  "increment month"/"decrement month" (but carries a masking `data-test` — match combined sig).
- Cookie banner (OneTrust "Accept All Cookies"); clicking the date button also collapses it.
- No reliable month-grid sold-out marks → the post-search slot list is authoritative.
- Verified recipe: `recipes/sevenrooms.md`.

## TableCheck — TWO widget generations
- **OLD (Rails, e.g. Sorn):** gates = tick T&C (`#reservation_confirm_shop_note`) + select party
  (`#reservation_num_people_adult`) + **click a course-menu "Select"** (`.menu-item-order-btn`,
  mandatory — without it availability AJAX errors). Date set via mobiscroll JS instance. Slots in
  `#reservation_start_at_epoch` options.
- **NEW (React SPA, e.g. Nusara):** `/reserve/message` gate → "Confirm and continue"
  (`data-testid="Footer Button"`, MUST wait for hydration before click). Party = stepper
  `data-testid="Counter Select"` (select option 0–8, NOT a button-per-number). Date = month grid by
  `aria-label`. Slots = `data-testid="Landing Time Button"`.
- Detect generation by URL shape / presence of the React footer.

## Chope — TWO widget generations
- rid (e.g. `indulge1804bkk`) from the reserve button; resolve ONCE per venue and cache (re-fetching
  the heavy public page per unit triggers soft-blocks). Fallback: `book.chope.co/booking?restaurant=<slug>`.
- THREE generations (detect by booking redirect host): OLD jQuery (`book.chope.co/booking`, native
  slots `<li>`, `full` class = sold out); plain `booking.chope.co/booking_index` (NEW front that may
  **proxy to the real engine** — SEEN BKK → TableCheck via `utm_source=chope_api`); hash-routed
  `booking.chope.co/widget/#/booking_index` (**NEW Vue SPA**, own widget).
- NEW Vue SPA (verified Jhol BKK 2026-06-03): read = index-screen Time-picker buttons per date
  (party steppers + Select-Date calendar by aria-label). Render-only-bookable (gap in service = filled).
  **Next = checkout/contact form, NO slot-grid screen — never click it.** JSON APIs (bookings/check,
  get_section_timeslots, check_need_to_pay) are request-signed → UI-driven read only. recipes/chope.md.
- Clickthrough gotchas (Escape probe): load `chope.co/bangkok-restaurants/restaurant/<slug>` **without**
  `?lang=` (the lang variant client-redirects to about:blank in headless). Chope pages **may not fire
  `load`** (trackers) → if `open` times out the page may still be there; verify via `get title` / body
  poll, not the exit code (Vertigo 2026-06-03 loaded clean, so intermittent). **Delisted venue = real
  404** (`body` has "404 Page not Found"); also `book.chope.co/?restaurant=<slug>` 307-redirects to
  `/singapore-restaurants` for invalid ids → classify `unresolved`/delisted, NEVER `full`.
- **Live slot-read VERIFIED (Vertigo BKK 2026-06-03):** rid = `window.rid` global on the public page.
  Widget inner APIs (replay same-origin via eval-fetch, primary read): `POST /inner_api/get_calendar_info`
  (party-aware day grid; `data` is a JSON string — double-parse) + `POST /inner_api/get_times`
  (date `D-M-YYYY`; slots in `return_str` HTML, `value='6:00 pm'` attrs; empty `return_str` = full day;
  `price_to_charge`/`reservation_charge` = deposit signal). UI fallback gotchas: hidden `#date` lags
  `#date-field`; time-dropdown `<li>` list holds a hidden 24h template — filter `offsetParent` while
  dropdown open; `full` day cells reject clicks. A trailing all-full block: check next month to split
  sold-out (`full`) vs booking-window cutoff (`no-slots`). Full recipe: `recipes/chope.md`.

## CoverManager (verified live 2026-06-03, Supra BCN + DiverXO MAD)
- Live module is **Angular** (`/reserve/module_restaurant/<slug>/<lang>`), not the spike's jQuery-UI
  gen. Day states unchanged: `""` open, `complete` full, `close_date` closed (**past days also read
  `complete`** — mask them). Invalid slug → highlight returns `[]` → `unresolved`.
- **Cross-slug probing**: one module page open = probe any venue. `POST /reservation/highlight`
  (month map) + `GET /Reserve/change_day/<slug>/<date>/<party>/english` (per-meal
  `{complete, close, hours}`; available meal = object keyed by party — **all parties 1–15 in one
  call**; full meal = `hours` flips to empty array). Slots render-only-bookable → service-grid
  fill inference. Stripe card iframes live in the module (deposit venues) — probe stops in step 1.
  Full recipe: `recipes/covermanager.md`.

## Hungry Hub (verified live 2026-06-03, Lamaya Bangkok)
- "Packages" (buffet/set-menu) with per-package booking; slots DO have a time grid (hourly buttons)
  in the rebuilt Astro SPA drawer. Numeric restaurant id ≠ URL slug (`/restaurant_id=(\d+)/` in page
  HTML). **Drawer calendar is package-scoped — can disable dates the restaurant still has**; use
  restaurant-level `internal-api.hungryhub.com` v5 POSTs (`minor_version: 4`, `client_type=web`) or
  union across packages for true day status. Per-slot `seat_left`/`quantity_available`; per-date
  `booked_seat` demand signal. Old widget IDs (`#adult`/`#date`/`#start_time`) are gone.
  Full recipe: `recipes/hungryhub.md`.

## Eatigo
- Nuxt SSR; the whole ~30-day slot window (with per-slot % discount) is in the hydration payload.
- **Party-independent** at read time → probe party 2 only. Capture discount into `extra`.

## Weeloy — ⚠️ DEFUNCT for consumer bookings (verified 2026-06-03)
- SPA router redirects ALL venue deep-links to a Singapore food-ordering homepage; www.weeloy.com
  pivoted to B2B SaaS (`weeloy_io`). No booking widget reachable. fullinfo API still answers with
  stale `is_bookable:1` — **API liveness ≠ bookability**. Weeloy-routed venues → `unresolved`,
  re-route via the venue's own site. Parser-stall fix (trustlogo.comodo.com +
  stackpath.bootstrapcdn.com → /etc/hosts blackhole) recorded in `recipes/weeloy.md` — transfers
  to any site with dead third-party scripts.

## Inline (anti-bot-blocked from datacenter IPs, verified 2026-06-03)
- `/booking/<companyId>:<env>/<branchId>?language=en` (Firebase-fronted). **PerimeterX behavioral
  "Press & Hold" CAPTCHA on first load** — plain agent-browser Chrome AND CloakBrowser native
  stealth both walled; `booking-capacitiesV3` returns 403 `px-captcha` on direct curl. → `unresolved`
  (do NOT automate the gesture). Day-level availability + min/max party (**party-relevant**) only
  readable from a residential IP / warmed `_px*` session. Many single-segment legacy links are dead
  404 — verify live first. Note: CloakBrowser clears Cloudflare (OMAKASE/TableCheck) but NOT
  PerimeterX behavioral from a flagged IP. Full recipe: `recipes/inline.md`.

## OMAKASE (omakase.in) — Tokyo high-end (verified gated 2026-05-30, Sézanne)
- `omakase.in/<lang>/r/<rid>`. **Cloudflare-protected → plain agent-browser is hard-blocked;
  use the CloakBrowser-over-CDP fallback** (see clickthrough-technique.md).
- Per-date slot calendar is **behind a login wall** — "reserve" 302-redirects anonymous users to
  `/sign_in`. No anonymous slot view → resolve **`gated`**, do NOT create an account.
- Public page still exposes: active reservation window ("until <date>"), timed reservation-round
  releases ("next round opens …"), seat fee (~390 JPY), strict cancellation, closed days. Capture those.
- Corroborated on 2 venues (Sézanne `rz444182`, L'Effervescence `tm207964`) — both `gated`.
  CloakBrowser cold `launch()` is slow (~60–90s) — run detached and poll. Reservation button is
  `a.ui.button.primary.big.fluid` → `/r/<id>/reservations/new` → `/users/sign_in`.
- **Only path to read slots:** a user-supplied logged-in CloakBrowser **persistent** session
  (OMAKASE account), then drive the post-auth calendar and STOP before the Stripe fee step. Until
  credentials are provided, OMAKASE venues are correctly `gated` — never bypass.

## Pocket Concierge (pocket-concierge.jp) — Japan fine-dining (verified 2026-05-30, Den)
- `pocket-concierge.jp/<lang>/restaurants/<id>`. Amex-owned. React SPA — wait ~6s for hydration.
- Booking entry = a **"Select date" button** → React date-picker (aria-label "Previous/Next Month").
  **Day cells are `<button>` with numeric text; `disabled` = unavailable.** No per-day time grid and
  no "Available" labels — availability IS the day-button disabled state.
- Party size chosen AFTER a date → on sold-out venues party can't vary (probe party 2, party-irrelevant).
- **Waitlist venues** show a global "No seats are available" banner + all-disabled calendar →
  classify every date `full` with a "waitlist / no online inventory" note (Den is this case all June).

## DinnerBooking — Cloudflare Turnstile (verified, AOC Copenhagen iter3)
- Widget `book.dinnerbooking.com/dk/en-US/book/table/pax/<venueId>/1`. Interaction-only Turnstile
  (sitekey e.g. `0x4AAAAAAANghrZGVRYnOyan`, action `pax`), callback `enableBookPaxButton` ungates the
  Next button. Slots: `GET /dk/en-US/times/index/<venueId>/1/<pax>.json` (`openTimes` + `waitingTimes`).
  Cleared via the anti-bot escalation tier (CloakBrowser + patchright + xvfb). **easyTable is the same
  Turnstile family.** Full recipe: `recipes/dinnerbooking.md`.

## Superb / Formitable — ALTCHA (verified, Copenhagen iter3)
- ALTCHA-gated availability endpoint `api-gx.superbexperience.com/availability/dates`; Superb is the
  engine behind Formitable widgets. Lighter wall — cleared HEADLESS via plain cloakbrowser stealth
  (patchright optional). Full recipe: `recipes/superb.md`.

## New engines (recipes TBD)
- **OpenTable** — ✅ now verified, see `recipes/opentable.md` (DataDome cleared via CloakBrowser
  humanize; `dapi/fe/human` 200, `RestaurantsAvailability` GraphQL slots). NOTE a listing can still be
  **informational-only** and route to the real engine (Sézanne's OpenTable page → OMAKASE) — verify it
  actually shows slots.
- **Resy** (`resy.com/cities/.../<slug>`), **Tock** (`exploretock.com/<slug>`), **Toreta** —
  standard widgets; build recipes when a target venue requires them.
