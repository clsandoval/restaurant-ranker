# Recipe: Hungry Hub ✅ verified (Lamaya Bangkok, 2026-06-03, 18-unit grid, zero unresolved)

Read-only availability via agent-browser clickthrough on the rebuilt **Astro + Cloudflare-Pages SPA**
(`web.hungryhub.com`). Verified on a live bookable venue with real per-date variation (sold-out day,
partially-booked day, per-slot seat counts).

## Stale-URL guard (do this FIRST)
Old `/en/restaurants/<slug>[/web]` deep-links are often **dead** (search engines still index them).
**Do NOT rely on curl `301 → /en/bangkok` as the stale signal** — live venues also 301 at the edge
(proven: `coppe-bangkok` is live but 301s). **Authoritative test = client-side SPA navigation:** a
LIVE slug keeps its URL + real venue title and fires a restaurant API call; a DELISTED slug
client-redirects to `/en/bangkok/web` (generic title) with **no** restaurant API call (the
slug-resolver returns `success:false "can not identify your requested restaurant"`). To resolve the
current slug, read the hydrated `/en/bangkok` listing (`a[href*='/restaurants/']`) or drive the
in-site search. A never-existed slug returns 404.

## Clickthrough (lead with this — NOT the API)

1. The SPA may not fire `load` → if `agent-browser open` times out, navigate via
   `eval "location.href='<url>'"` and **poll** `readyState` / `body.innerText.length`. Allow ~8s
   hydration after nav.
2. Venue page (`/en/restaurants/<slug>/web`) lists **packages** (buffet/set-menu cards), each with a
   `Book` button wrapped in an `<a href="/en/restaurants/<slug>/package/<pkgId>/web">`. The OLD
   widget IDs (`#adult`, `#date` Pikaday, `#start_time`, `#book-btn`) are GONE. Navigate to a
   package page (pick a generic per-person package, not a fixed-size "for N people" pack).
3. On the package page click **"BOOK NOW"** (gate — opens the booking drawer, commits nothing).
   Drawer flow, all in the a11y tree (no shadow DOM):
   - **Party steppers**: two spinbuttons (adults, kids) with +/- buttons; "Select Date & Time" stays
     `disabled` until adults > 0. Click + to the target party.
   - **Date grid**: month of `button "NN"` elements — **`disabled` = past OR unavailable** for this
     package. Click an enabled day.
   - **Time slots render as `button "HH:MM"`** below the calendar after a date is picked. Reading
     them IS the probe.
4. **STOP at the slot list.** Never click a time button, "Confirm date & time", or "Checkout" — a
   credit-card step follows. Reading rendered times is the datapoint.
5. Classify: time buttons rendered → `available`; day button `disabled` (non-past) → `full` at
   package level (see scoping below); zero enabled days all month → zero-inventory venue → `full`
   per date (Roast case).

## Package-level vs restaurant-level scoping (the big gotcha)

The drawer calendar is **package-scoped**: it can disable dates the restaurant still has (proven:
Unlimited Tapas Buffet disabled Jun 12/13 while restaurant-level offered 20:15 on Jun 13). For
trip-brainstorming truth ("can I get a table at all") use the **restaurant-level** API read, or
union across packages. Record which scope a unit was read at.

## API read (restaurant-level; same-origin from the SPA page via eval-fetch)

Host: `https://internal-api.hungryhub.com` (CORS-open to the SPA; plain curl works too but returns
`"Something went wrong"` without the right body — always POST JSON). Numeric `restaurant_id` ≠ slug;
find it in the venue page HTML (`/restaurant_id=(\d+)/`, e.g. lamaya-bangkok → 5974).

- `POST /api/v5/restaurants/<id>/find_available_start_times.json?&client_type=web&locale=en`
  body `{"adult":2,"kids":0,"date":"YYYY-MM-DD","minor_version":4,"for_dine_in":true,"for_delivery":false,"is_order_now":false}`
  → `data: [{start_time, availability, seat_left, quantity_available}]` — **per-slot seat counts**;
  `availability:false` slot = `filled`. Empty data on an unavailable day.
- `POST /api/v5/restaurants/<id>/find_available_dates.json?&client_type=web&locale=en`
  body same minus `date` → per-date `{availability, seat_left, min_seat, max_seat, booked_seat}`.
  `booked_seat` > 0 = live demand signal. `availability:false, seat_left:0` = full/closed day.
- `minor_version` is now **4** (was 3 on the old site). Throttle ~350ms.

## Cases handled (ledger)

- ✅ **Lamaya Bangkok** (id 5974, Phrom Phong rooftop), 2026-06-03: 18-unit grid
  (Jun 6/7/10/13/20/24 × party 2/4/6), zero unresolved. 6 slots/day 17:15–22:15 hourly,
  seat_left=10; **Jun 13 partially booked (only 20:15 left)**; **Jun 16 full at restaurant level**
  (`availability:false`); booked_seat>0 on Jun 3/6/7/21. Clickthrough cross-checked against
  captured live SPA traffic + API replay.
- ✅ Package-vs-restaurant scope divergence (buffet calendar disabled Jun 12/13; restaurant open).
- ✅ New-SPA drawer flow (steppers → date buttons → time buttons); old `#adult`/`#date`/`#start_time`
  IDs are gone — recipe rewritten.
- ✅ Zero-inventory venue (Roast, EmQuartier) — `find_available_dates` all `availability:false,
  seat_left:0` across the month → all `full`. Authoritative (real per-date records, not static).
- ✅ Stale-URL guard (Sushi Seki dead deep-link; coppe-bangkok live-but-301).

## Open / unverified cases

- ⬜ A per-slot `availability:false` mixed inside an available day (Lamaya omitted filled times
  from the response instead — Jun 13 returned ONLY the open 20:15 → treat as render-only-bookable
  platform: infer fill via service_grid, run `finalize_fill.py`).
- ⬜ Kids-count effect on availability (`kids` param probed at 0 only).
- ⬜ A deposit/prepaid package gate before the time read.
