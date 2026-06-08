---
name: booking-probe
description: Use when probing restaurant booking platforms (TableCheck, SevenRooms, Chope, CoverManager, Hungry Hub, Eatigo, Weeloy, Inline, OpenTable, Resy, Tock) to read table availability for a trip — which dates / times / party sizes are open vs booked out — across a city's restaurants. Read-only: reads the calendar, never makes or confirms a reservation. Drives the real booking widget via the agent-browser CLI, one verified recipe per platform, one browser session per restaurant for sequential/parallel fan-out. Part of the restaurant-ranker plugin.
---

# Booking Probe

Reads **table availability** from restaurant booking widgets by driving the real UI with the
`agent-browser` CLI — snapshot → click → re-snapshot — and recording, per (venue × date ×
party), which time slots are offered vs booked out. Builds a per-city availability dataset for
trip brainstorming. **It is a brainstorming/research tool. It never books anything.**

## THE READ-ONLY LAW (non-negotiable)

**Read availability only. NEVER submit, confirm, or complete a reservation.**

Push through gates to *reach and read* the slot list (accept T&C, set party size, pick a
default course menu, dismiss cookie banners). Then STOP. Reading the offered slots IS the
probe. Clicking a slot, a "Next"/"Book"/"Confirm"/"Complete" button, or entering payment /
deposit details is a FAILURE of the task — it creates a real reservation, blocks a real table,
and violates lakbai's core anti-goal.

**Forbidden, no exceptions:**
- Don't click a time-slot button "just to see what happens" — it advances to checkout.
- Don't fill the final contact/payment form, even with fake data, even if "I'll stop before submit."
- Don't proceed past a deposit / credit-card-hold gate (GOAT, Potong, Samrub, etc.). Record
  the deposit requirement and stop.
- "Verifying it's really bookable" is NOT a reason to click through. Offered slot = the datapoint.

**Red flags — STOP immediately if you think any of these:**
- "Let me click one slot to confirm the flow works."
- "I'll fill the form but not hit submit."
- "The deposit step is fine, I'll just look at the next screen."
- "It's a test reservation, I'll cancel it after."

All of these mean: you are about to create a real booking. Back out. The slot list is enough.

## North-star goal (the verification target)

**200 bookable restaurants per city** — Manila, Bangkok, Tokyo, New York, and beyond — probed
availability-only. Harden this skill **one restaurant at a time** via sequential MA / autopilot
sessions, accumulating edge-case coverage until every platform recipe is **bulletproof against
all cases**. Confidence per restaurant before scaling. Slow and deliberate.

## The hardening loop (RED → GREEN → REFACTOR, one restaurant at a time)

Each restaurant is a **test case** for the skill. Run them one by one:

1. **Probe one restaurant** with its platform recipe (`recipes/<platform>.md`), full target grid
   (every date × party 2/4/6). One `agent-browser --session lakbai-<venue-slug>` per restaurant.
2. **If it resolves cleanly** (every unit → available / full / no-slots, zero `unresolved`/`error`):
   that venue is confirmed; add it to the recipe's "cases handled" ledger; move to the next.
3. **If it fails** (unresolved, wrong data, new widget variant, locale/timezone issue, deposit
   wall, sold-out rendered differently): that's a RED test. Capture the exact failure verbatim,
   fix the recipe to handle it, re-probe until GREEN, and record the new case in the ledger.
4. Recipe is "bulletproof" for a platform when it clears a large, diverse venue set across
   multiple cities with zero unresolved.

Never silently drop a failure. An honest `unresolved` with a blocker note is correct; a fake
`available`/`full` is the worst outcome (it corrupts the dataset — see Common Mistakes).

## How availability is read (the core technique)

agent-browser's accessibility snapshot sees form controls but often NOT the result slots (heavy
widgets render them in **shadow DOM**). The universal pattern: use `agent-browser eval` with a
recursive shadow-root walk to click buried controls and read slots from `document.body.innerText`,
and match elements by a **combined signature** (data-test + aria-label + title + text), never a
single attribute. Full technique + gotchas: `references/clickthrough-technique.md`.

## Per-restaurant fan-out (the MA / autopilot model)

Endgame: one MA/autopilot session per restaurant, each running its platform recipe as a behavior
brief, fanned out across a city's 200 venues. `agent-browser --session lakbai-<venue-slug>` gives
each restaurant an isolated browser. Build up sequentially (one at a time) until confident, then
widen parallelism. A reference driver that codifies a recipe end-to-end: `drivers/drive_sevenrooms.py`.

**Dispatching MA sessions:** use the `autopilot` skill (`/autopilot`, three-gate pipeline) to launch
one Managed Agent per restaurant; monitor via the MA API / `investigate-cma` skill. The full
booking-probe dispatch contract — the read-only-law behavior brief, the zero-unresolved/no-booking
outcome checklist, skill upload, the agent-browser-in-container caveat, and the MA API cheat sheet —
is in `references/ma-dispatch.md`. **Read it before any fan-out.**

## Platform recipes

| Platform | Recipe | Status |
|---|---|---|
| SevenRooms | `recipes/sevenrooms.md` | ✅ verified (driver + 3×90-unit grids, zero unresolved) |
| TableCheck | `recipes/tablecheck.md` | ✅ verified OLD Rails (Florilège); ✅ verified new-React (ADHOC Bangkok, party 2, CloakBrowser-CDP) |
| Chope | `recipes/chope.md` | ✅ verified OLD jQuery (Vertigo BKK, inner_api replay) + NEW Vue SPA read path (Jhol BKK, UI clickthrough — Next=checkout boundary); proxy-to-TableCheck case noted |
| Eatigo | `recipes/eatigo.md` | ✅ verified (Glass House + Goji, party-independent, per-slot discount; payload-read primary, picker-click fallback) |
| Hungry Hub | `recipes/hungryhub.md` | ✅ verified (Lamaya BKK live widget — new-SPA drawer flow, per-slot seat_left, real full + partial days; package-vs-restaurant scoping) |
| CoverManager | `recipes/covermanager.md` | ✅ verified (Supra BCN + DiverXO MAD — cross-slug API replay, month map + per-meal change_day; deposit boundary held) |
| Weeloy | `recipes/weeloy.md` | ⚠️ DEFUNCT (2026-06-03) — consumer portal dead, API orphaned; re-route venues to their current engine |
| Inline | `recipes/inline.md` | ⚠️ anti-bot-blocked (PerimeterX Press&Hold; plain Chrome + CloakBrowser both walled from datacenter IP) → `unresolved` until residential IP/warmed session |
| Pocket Concierge | `recipes/pocket-concierge.md` | ✅ verified (Narisawa real open/full/closed; CloakBrowser; Instant-vs-Waitlist) — readable OMAKASE mirror |
| OMAKASE | `references/platform-knowledge.md` | ⚠️ login-gated → `gated` (check Pocket Concierge mirror first); CloakBrowser-CDP |
| DinnerBooking | `recipes/dinnerbooking.md` | ✅ verified (AOC Copenhagen — Cloudflare Turnstile cleared via CloakBrowser+patchright; easyTable same family) |
| Superb / Formitable | `recipes/superb.md` | ✅ verified (Copenhagen iter3 — ALTCHA proof-of-work cleared headless via CloakBrowser) |
| OpenTable | `recipes/opentable.md` | ✅ verified (Copenhagen iter3 — DataDome cleared via CloakBrowser humanize; RestaurantsAvailability GraphQL slots) |
| Resy · Tock · Toreta | — | ⏳ new engines (build on demand) |

Build order follows venue count + Michelin coverage: TableCheck → Chope → Hungry Hub → the rest →
new engines. To add a platform, copy `recipes/_TEMPLATE.md`. Prior DOM/endpoint knowledge per
platform (tokens, gates, widget generations) is in `references/platform-knowledge.md`. The **anti-bot
escalation tier** — the tiered CloakBrowser playbook (patchright + xvfb + humanize) for the
Turnstile / ALTCHA / DataDome / CDP walls, plus the "403 means wrong tier, not blocked" rule and the
loop for cracking an engine with no recipe yet — is the **`cloakbrowser` sibling skill**
(`../cloakbrowser/SKILL.md`). Read it before probing any anti-bot engine.

## Finding which engine a restaurant uses

Many restaurants book on their own website but **delegate to a known engine** (Sühring → SevenRooms,
Potong → Chope, Gaa → TableCheck). Resolve direct sites to an engine, then route to its recipe.
Engine-detection method + the Bangkok direct-site map + deposit/phone-only handling:
`references/engine-routing.md`.

## Output location

Per-venue JSON, one file per restaurant (no write contention when fanning out), under the
**caller's CWD**: `./<city>-booking-probe/clickthrough/<venue-slug>.json`. Never hard-code an
absolute path. Each unit record: `{date, party_size, status, slots:[{time, meal, state}], note}`
where each slot's `state` ∈ `available | filled`. Day-level `status` ∈ available | full | no-slots |
gated | unresolved | error is a ROLLUP (any available slot → available; all filled → full).

## Slot-fill distribution (which times are taken) — the real signal

Don't reduce a date to available/full. Capture **every seating time with its per-slot state** so the
dataset shows *which* times are gone (e.g. 19:00 filled, 21:00 open).

- **Widgets that render the full grid with greyed/disabled slots** (OpenTable/Resy/Tock time-bars):
  read EVERY slot element incl. disabled ones → disabled/greyed = `filled`, enabled = `available`.
  Do not drop the greyed ones. (CoverManager's `complete` class is a DAY-cell state, not a greyed
  slot — verified 2026-06-03; its slots are render-only-bookable, see next bullet.)
- **Widgets that render only bookable slots** (SevenRooms, TableCheck, Eatigo, CoverManager,
  Hungry Hub — they omit filled
  times): there's no greyed element. Capture the offered times per date, then **infer fill from the
  service grid**: `service_grid` = union of all times the venue ever offers across the probed window;
  per date, `filled = service_grid − offered_that_date`. The full 30-day grid is what makes this sound.
  `finalize_fill.py` computes this from the per-date offered slots — run it after a venue's grid completes.

## Common mistakes

- **Faking resolution.** Returning `available`/`full` when the read actually failed. A failed read
  is `unresolved` with a blocker note — always. Silent empties poison the dataset.
- **Trusting day-grid "Available" as slot truth.** Day-level marks are a cross-check; the authoritative
  read is the per-date slot list after search.
- **Keeping agent-browser refs across actions.** Refs are ephemeral — re-snapshot (or re-query) after
  every state change.
- **Single-attribute matching.** A non-empty `data-test` masks the `aria-label`; always match the
  combined signature.
- **Probing party 4/6 on party-independent platforms** (Eatigo, Weeloy, Inline read day/open-hours,
  not per-party) — probe party 2 only there; party 2/4/6 only where the API/UI varies by party.
