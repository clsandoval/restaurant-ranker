# Recipe: SevenRooms ✅ verified

Read-only availability via agent-browser clickthrough. Reference driver: `../drivers/drive_sevenrooms.py`.
First verified 2026-05-30 (Le Normandie June 7 / party 2 = 9 slots; 3-venue full-June grids).

## Steps (one venue × date × party)

1. `open https://www.sevenrooms.com/reservations/<slug>/` ; wait ~4s for hydration.
2. eval-click "Accept All Cookies" if present (best-effort; the date button also collapses it).
3. eval-click the **date display button** (BUTTON whose text ends "Date", len>5).
4. eval-click **"increment month"** (match COMBINED signature) until a day cell with the target
   `aria-label` ("June 7th 2026") is present (max ~12 hops).
5. eval-click the **day cell** (`<td>`) whose `aria-label` matches the target day.
6. Set party: eval-click **"increment Guests"** `(party − 2)` times (default is 2).
7. eval-click **`data-test=sr-search-button`** (shadow DOM). Wait ~8s.
8. eval-read `document.body.innerText`, split on "Select a time", regex `(\d{1,2}:\d{2})\s*(Lunch|Dinner|...)?`.
9. **Dedup by time** (prefer labeled meal — drops the echoed request-time). STOP. Never click a slot.

## Widget variants (detect which)
- **Classic** (`/reservations/<slug>/`): day cells are `<td>` with full date in `aria-label`;
  shadow-DOM `sr-search-button` after date+party (steps above).
- **"Explore"** (`/explore/<venue>/reservations/create/search/`, e.g. Geranium, Peppina, Akira Back):
  calendar is **react-day-picker**. The Date trigger is a BUTTON with whitespace-collapsed text that
  VARIES by venue (`Date30May`, `30 May`, or `230 MayAll Times` = party+date+time-filter) and has no
  `data-test` → open it by matching a combined-signature element, not a fixed string. The panel may
  render **ONE `.rdp-month` (Akira Back) OR TWO side-by-side (Geranium, Peppina)** — either way, scope
  the day-click to the `.rdp-month` whose `.rdp-caption_label` reads the target month ("June 2026");
  click `Calendar`/"next month" until that panel is present; match `.rdp-day` by numeric `textContent`,
  excluding `.rdp-day_outside` / `.rdp-day_disabled`.
  **No `sr-search-button`** — selecting the day auto-fires the search.
  **Read slots from `data-test="reservation-timeslot-button-<HH:MM>"` buttons** (walk shadow roots) —
  NOT `body.innerText` (its time list overlaps the Time-filter options and is unreliable here).
  **Echo anchor:** verify the requested date against the leaf `^(Date)?\d{1,2} June 2026$` element —
  NOT the collapsed Date trigger, which keeps showing the stale "30 May" summary while the picker is
  open. Read echo and slots in **separate polled evals** (same-tick read gives count 0). An empty read
  with a blank echo is a timing flake → re-probe, don't call it `full`.
- **⚠️ Classic `/reservations/<slug>` can 302-REDIRECT to Explore** (Akira Back). Detect the variant by
  the **post-load URL**, not the input URL. `drive_sevenrooms.py` only implements the classic widget →
  it fails on Explore-redirecting venues (needs the Explore path added).
- **Anti-bot:** agent-browser's bundled Chrome may self-redirect the Explore widget to `about:blank`
  (~10s after load / after the date click) → use the CloakBrowser-CDP fallback. Serialize all calls.
- **`Alert Me` / `Other dates with availability` is a PERMANENT UI element — NOT a full-signal.** Only
  "There is no availability that meets your search criteria." means `full`.

## Classification
- Parsed slots → `available` (one record per slot, with `meal`).
- **`full` signal = the leaf text "There is no availability that meets your search criteria."**
  An **"Add me to waitlist"** button accompanies full days — but waitlist can ALSO appear alongside
  available slots, so the no-availability *message* is the authoritative full-signal, not the button.
- Day cell absent / nav timeout / unreadable → `unresolved` (note the blocker).

## Cases handled (the hardening ledger — append as venues are cleared)
- ✅ Classic widget, hotel SevenRooms (Le Normandie, China House, Terrace Rim Naam) — lunch+dinner.
- ✅ Direct-site venue delegating to SevenRooms (Sühring) — June 7/p2 = 6 slots.
- ✅ Day cells are `<td>` not `<button>` (match by aria-label, any tag).
- ✅ Month-nav button's `data-test` masks its `aria-label` → combined-signature matching.
- ✅ Request-time echo leaks a bare duplicate time → dedup-by-time.
- ✅ Transient "could not click day" → resumable retry (re-probe just that unit).
- ✅ **"Explore" widget variant** (Geranium, Copenhagen) — react-day-picker, no `sr-search-button`.
- ✅ **Explore full-30, Bangkok** (Peppina 30/30 + Akira Back 30/30 available, party 2) — single-panel
  (Akira) and two-panel (Peppina) calendars both handled; classic URL→Explore redirect; echo-anchor fix.
- ✅ **Genuinely sold-out / full day** (Geranium: 5/6 dates full) — "no availability…" message;
  Jun 20 surfaced a single 12:30 lunch table → discriminating live data confirmed.
- ✅ **CET locale/timezone** (Copenhagen). ✅ Deposit-model venue (Geranium DKK 1,500/guest prepay) —
  read slots, stop before the deposit step.

## Open / unverified cases (turn these GREEN as you hit them)
- ⬜ Multi-experience venues (a venue exposing several seating "experiences" before the calendar).
- ⬜ Non-English (JP/locale) SevenRooms day-label formats.
- ⬜ A SevenRooms venue that gates the calendar itself behind login/deposit (so far slots were
  always anonymously visible; deposit only at the end) → would be `gated`.
