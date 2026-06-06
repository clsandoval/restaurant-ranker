# Chope — availability probe recipe

Status: ✅ verified OLD jQuery widget (Vertigo Bangkok, 2026-06-03, 18-unit grid, zero unresolved);
✅ verified NEW Vue widget read path (Jhol Bangkok, 2026-06-03 — per-date variation + filled gaps).

## THREE generations (detect by the booking redirect host)

Resolve rid (see below), then `book.chope.co/booking?rid=<rid>&source=chope.com.sg` and follow
the redirect:
- stays `book.chope.co/booking` → **OLD jQuery** (native slots, inner_api replay — section below).
- `booking.chope.co/booking_index?...` (plain) → NEW front that may **proxy to the real engine**
  (SEEN BKK → `tablecheck.com/...?utm_source=chope_api` at the Next step → route to TableCheck recipe).
- `booking.chope.co/widget/#/booking_index?...` (hash-routed) → **NEW Vue SPA** (own widget — section below).

## Read path (OLD jQuery widget, `book.chope.co/booking`)

**Primary read = same-origin API replay from the widget page (like Eatigo's payload-read).**
The widget itself drives two inner APIs on every interaction — replay them with `fetch()` via
`agent-browser eval` instead of fighting the datepicker UI:

1. Resolve rid ONCE per venue (cache it):
   - Open `chope.co/bangkok-restaurants/restaurant/<slug>` (**no `?lang=`** — redirects to
     about:blank headless). `window.rid` global on the public page IS the rid
     (e.g. `vertigobanyantree1509bkk`). Also present in `book.chope.co/booking?...rid=` script hits.
2. Open `book.chope.co/booking?rid=<rid>&source=chope.com.sg` (loads fine, fires `load`).
3. Day grid (party-aware) — `POST /inner_api/get_calendar_info` with form body
   `rid=<rid>&s_date=2026-6-1&e_date=2026-6-30&adults=2&children=0&reservation_id=0&source=chope.com.sg&country_code=BANGKOK&event_campaign_id=`
   → `data` is a JSON **string** (double-parse): `{day_N: {status: past|open|full, note, waitlist, has_normal_time}}`.
   Full days carry `note: "Please contact the restaurant directly"`.
4. Per-date slots — `POST /inner_api/get_times` with form body
   `rid=<rid>&date=<D-M-YYYY>&selected_time=6%3A15+pm&adults=N&children=0&reservation_id=0&confirmationCode=0&source=chope.com.sg&smart=1&smart_level=1&event_campaign_id=`
   → `{data: {waitlist, now_avaliable (sic), return_str: "<li ... value='6:00 pm'>..."}}`.
   Parse times with `/value='([^']+)'/g`. Each `<li>` also carries `price_to_charge` /
   `reservation_charge` (deposit signal — capture into `extra` if non-zero).
   **Full/blocked day → empty `return_str`** (no waitlist/now_avaliable keys) → `full`.
   Headers: `Content-Type: application/x-www-form-urlencoded` + `X-Requested-With: XMLHttpRequest`.
   **Date format is D-M-YYYY** (`10-6-2026`), no zero-padding seen.
5. Throttle ~400ms between calls; probe party 2/4/6 (both APIs take `adults` — Chope is party-aware,
   even when a high-capacity venue returns identical sets; `#max_party_size` hidden input = venue cap).

## UI clickthrough fallback (cross-check)

- Datepicker day `<td>` classes: `past` | `day` (open) | `full`. **`full` cells reject clicks**
  (date stays unchanged — detect by re-reading `#date-field`).
- The time dropdown `<li>` list contains a hidden 24h template; **only `li` with a non-null
  `offsetParent` (visible while dropdown is OPEN) are the offered slots**. Sold-out times get a
  `full` class. The dropdown collapses on date change — re-open it before reading.
- **Hidden `#date` input LAGS the visible `#date-field`** — trust `#date-field` (the textbox) for
  "which date am I reading"; hidden `#date` only syncs later in the flow.
- Useful hidden inputs: `#available`, `#time_is_full`, `#wait_list`, `#max_party_size`, `#adults`.

## NEW Vue widget (`booking.chope.co/widget/#/booking_index`) — verified read path

UI clickthrough on the **index screen** (no clean API replay — the JSON endpoints are request-signed):
1. Party: `Adults`/`Children` stepper buttons (+/- around a spinbutton).
2. Date: `Today` / `Tomorrow` quick buttons, or a `Select Date` button → calendar of
   `button[aria-label="Weekday, Month D, YYYY"]` (past/closed days `disabled`).
3. **Slots = the index-screen Time picker buttons** (`button "H:MM am/pm"`, visible ones only).
   This list IS the per-date bookable-slot read. Real per-date variation verified (Jhol: same-day
   Jun 3 = only 9:30pm left; Jun 6 = full 17-slot grid). **Slots are render-only-bookable** — a gap
   inside a service window = booked/filled (Jhol Jun 6 missing 6:45–8:15pm inside 5:30–10:30
   dinner). Infer fill via service_grid (`finalize_fill.py`).
4. **READ-ONLY BOUNDARY (NEW widget): `Next` jumps STRAIGHT to the contact-details/checkout form**
   (First/Last name, email, mobile) — there is **NO intermediate slot-grid screen**. The time you
   pick on the index screen IS the selection. **Never click Next as a probe** — the index Time
   picker is the whole read.
- **CRITICAL hash-route gotcha (caused fake data — verified 2026-06-03):** the Vue widget is
  hash-routed on ONE path (`booking.chope.co/widget/#/booking_index?rid=...`). `agent-browser open`
  to a new rid changes only the hash → the SPA does **NOT re-boot**; it keeps the PREVIOUS venue and
  serves its slots under the new rid. Four venues all returned Jhol's exact 17-slot grid before this
  was caught. **Fix: `open about:blank` then `open <rid-url>` to force a full document load.**
  Integrity guard: after boot, read the `<h4>` venue name and confirm it matches the rid before
  trusting any slots. (Driver: `/tmp/vue_probe.sh` — about:blank reset + venue-name echo + per-date
  native Select-Date→day-button→read-Time-picker.)
- Synthetic DOM events (`.click()` / dispatched MouseEvents) do NOT open the calendar — the lib
  ignores untrusted events. Use agent-browser **native `click @ref`** (real CDP pointer events).
- `[]` time list on a clickable date = `full` (the date is offerable in the calendar but resolves
  to "This date is no longer available. Please select another date.").
- Date-stepper gotcha: after you pick a date, the `Select Date` trigger **relabels to the chosen
  date** (e.g. "Sat 6 Jun"), so re-opening can't match on "Select Date" — grab the Date-row button
  one line after "Tomorrow" in the snapshot.
- Signed APIs (reference only, not used — 401 without the widget's signature): `api.chope.co/bookings/check`
  (`A100` = table available), `openapi.chope.co/availability/get_section_timeslots` (per-section epoch
  slots), `api.chope.co/deposit/check_need_to_pay` (`need_to_pay` + deposit fields). `localStorage.token`
  alone (`samsung:...`) is NOT sufficient auth.

## Read-only boundary (OLD widget)

The slot list + day grid IS the probe. **Never click a time `<li>`, never click `Next`
(`#btn_sub`)** — Next advances toward the confirm page. `reservation_charge`/`price_to_charge` > 0
= deposit venue: record and stop. (NEW Vue widget boundary is stricter — see above.)

## Confidence checks

- The Jun-15→30 contiguous `full` block looked like a booking-window cutoff — it wasn't: July came
  back fully `open`, proving per-date truth. **Always check the next month before reading a
  trailing full-block as sold-out vs window-cutoff.** If next month is ALSO all full → suspect
  window cutoff → classify `no-slots` (outside window), not `full`.
- Cross-check `get_times` emptiness against `get_calendar_info` day status — they must agree.

## Cases handled (ledger)

- ✅ **Vertigo (Banyan Tree, Bangkok)** rid `vertigobanyantree1509bkk`, 2026-06-03: 18-unit grid
  (Jun 6/7/10/13/20/24 × party 2/4/6), zero unresolved. Jun 6–13 open (13 dinner slots
  6:00–9:00pm @15min, party-invariant, max_party 19), Jun 20/24 `full` (whole 15–30 block full,
  note "Please contact the restaurant directly"; July open). API replay verified against UI
  clickthrough + captured live XHR traffic.
- ✅ rid via `window.rid` global on public venue page (no button-attr scraping needed).
- ✅ Full-day `get_times` → empty `return_str` (response shape loses waitlist/now_avaliable keys).
- ✅ Hidden `#date` lag / visible `#date-field` authoritative (UI fallback gotcha).
- ✅ Hidden 24h li template vs visible offered slots (offsetParent filter, dropdown must be open).

## Cases handled — NEW Vue widget (ledger)

- ✅ **Jhol** (`jhol2002bkk`, modern Indian Khlong Toei) NEW Vue SPA, 2026-06-03: read path verified
  on 2 contrasting dates — Jun 3 same-day = only 9:30pm left; Jun 6 = 17-slot grid (lunch 12:00–1:30,
  dinner 5:30–6:30 & 8:30–9:30) with mid-dinner booked-out gap. No deposit. Read-only boundary
  established: Next = checkout form, not a slot grid.
- ✅ Three-generation detection by booking redirect host (OLD jQuery / proxy / NEW Vue SPA).
- ✅ Chope→TableCheck proxy at Next (`utm_source=chope_api`) — SEEN BKK; route to TableCheck.
- ✅ NEW-widget date-stepper relabel gotcha.

## Open / unverified cases

- ⬜ NEW Vue full multi-date × multi-party grid (deferred to city sweep; needs robust date-stepper
  + party-variance check — APIs are signed so it's UI-driven).
- ⬜ A NEW-widget full/sold-out day (how a fully-booked date renders the Time picker — empty? waitlist?).
- ⬜ NEW-widget deposit venue (`check_need_to_pay.need_to_pay` > 0) read via UI.
- ⬜ A venue with a per-slot `full` class on the OLD widget (sold-out times within an open day) — Vertigo never showed one.
- ⬜ A deposit venue (`price_to_charge`/`reservation_charge` > 0) — e.g. Potong delegates to Chope.
- ⬜ Waitlist day (`waitlist: true` / `allow_waitlist`).
- ⬜ Soft-block behavior under per-unit public-page re-fetch (avoided by rid caching — keep it that way).
