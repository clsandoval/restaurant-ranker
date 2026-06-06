# CoverManager — availability probe recipe

Status: ✅ verified (Supra Barcelona + DiverXO + StreetXO, 2026-06-03, 36-unit grid, zero unresolved).
The live module is an **Angular widget** (`/reserve/module_restaurant/<slug>/<lang>`), not the
jQuery-UI generation the spike captured — but the legacy read endpoints still answer.

## Read path (primary = same-origin API replay)

**One module page open = probe ANY CoverManager venue.** Both read endpoints accept any slug
cross-venue from one page origin — open one module page per session, then fan slugs through it.

1. Open `covermanager.com/reserve/module_restaurant/<any-slug>/english` (the `/reservation/...`
   spelling also resolves). Body hydrates ~6s (Angular; ~650 chars when ready, 48 = not yet).
2. **Month map** — `POST /reservation/highlight` (form-encoded + `X-Requested-With: XMLHttpRequest`):
   `language=english&restaurant=<slug>&month=06&year=2026&vip=0&skip_blocked_tables=false&people=2`
   → `{"YYYY-MM-DD": [bookable_bool, "<state>"]}` where state `""` = open, `"complete"` = FULL,
   `"close_date"` = non-service day. **Invalid slug → `[]`** (empty array) → `unresolved`, never full.
   **Past days also render `complete`** — mask out dates < today before reading.
3. **Per-date slots** — `GET /Reserve/change_day/<slug>/<YYYY-MM-DD>/<party>/english`
   → JSON with `hours: {Lunch: {complete, close, hours}, Dinner: {...}}`:
   - available meal: `hours` is an OBJECT keyed by party size (**every party 1–15 in one
     response** — `hours["2"].all = [{value: "HH:MM", zone: []}]`); one call covers party 2/4/6.
   - fully-booked meal: `complete: true` and `hours` is an empty ARRAY (type flips — guard it).
   - top-level `not_avaible` message: "Fully booked. Try another day."
   - `zones`/`have_zones`: table-zone variants (empty on both verified venues — open case).
4. Classify per (date, party): slots → `available`; `close_date` → `no-slots`; `complete` (day or
   all meals) → `full`; missing date / `[]` slug → `unresolved`. Per-meal split is REAL data —
   record meal on each slot (DiverXO Jun 3: Lunch complete, Dinner exactly one 20:30 slot).
5. Throttle ~400ms. Legacy `POST /reservation/update_hours/0` (old adapter) still exists but
   `change_day` is what the live widget uses.

## Slot-fill model correction

CoverManager slots are **render-only-bookable** (filled times are ABSENT from `change_day`, not
greyed). The `complete` class from the spike applies to **day cells**, not slot buttons. → Infer
per-slot fill via `service_grid − offered` (`finalize_fill.py`), same as SevenRooms/TableCheck.

## UI clickthrough fallback (cross-check)

- Angular module: party `<select>` (1–15 people), 12-day date strip (`load_date` spans;
  `active_day bcolor bocolor` = selected), slot buttons under LUNCH/DINNER headings —
  parent class `button_hour ... bcolor step1`. All in the a11y tree (no shadow DOM).
- "Waiting List" / "Group request" pseudo-slots appear after real times — don't parse as slots.
- Slot counts vary by date (Supra: Wed 40 from 13:15, Sat 56 from 10:00) — the strip read is live.

## Read-only boundary

The module embeds **live Stripe card iframes** (per-person ticket/guarantee venues — Supra). The
4-step wizard is Find → Information → Additional → Confirmation. **The probe lives and dies in
step 1 (Find).** Never click a time button, Next/step-2, or anything near the Stripe card field.

## Cases handled (ledger)

- ✅ **Supra Barcelona** (`restaurante-suprabarcelona`), 2026-06-03: 18-unit grid, zero unresolved,
  all open; per-date slot variation (49–56 slots, Sat brunch from 10:00); deposit venue (Stripe).
- ✅ **DiverXO** (`diverxo`, Madrid 3*), 2026-06-03: 18-unit grid, zero unresolved — `close_date`
  Sat–Mon, `complete` every open probed date ("Fully booked. Try another day."), plus the
  Jun 3 per-meal partial (Lunch full / Dinner one 20:30 table) seen during verification.
- ✅ **StreetXO** month map: nearly all `complete` (hot-venue full-month case).
- ✅ Invalid slug (`restaurante-diverxo`) → highlight returns `[]` → `unresolved` marker.
- ✅ Cross-slug probing from a single module page (highlight + change_day both honor it).
- ✅ `hours` array-vs-object type flip on complete meals.
- ✅ Past days marked `complete` in the month map (mask dates < today).

## Open / unverified cases

- ⬜ A venue with `have_zones: true` (zone-split slot lists).
- ⬜ Party-size-dependent availability (both venues returned identical sets for 2/4/6).
- ⬜ Waiting-list flow signals (`hours_waiting`, `people_waiting_list`) on a WL-enabled venue.
- ⬜ A `/reservation/module_restaurant/` (old-path) venue confirming path equivalence at scale.
