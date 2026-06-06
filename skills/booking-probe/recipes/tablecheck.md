# Recipe: TableCheck ✅ verified (OLD Rails widget) · ⏳ new-React widget pending

Read-only availability via agent-browser clickthrough. TableCheck is the dominant Japanese
fine-dining engine (and common in Bangkok). It ships **two widget generations** — detect which.
First verified 2026-05-30 on Florilège Tokyo (OLD Rails): June 7 & 24 FULL, others available.

URL shape: `tablecheck.com/<lang>/shops/<slug>/reserve` or `tablecheck.com/<lang>/<slug>/reserve`.

## OLD Rails widget (plain DOM — no shadow DOM; verified)

Drive entirely via `eval` on the Rails form. Gate sequence (order matters):
1. **T&C:** `#reservation_confirm_shop_note` checkbox → `.click()`.
2. **Party:** set `#reservation_num_people_adult` `.value` + dispatch a native `change` Event.
   (Options are 1–N; respects the venue cap — Florilège caps at 4, so party 6 is unbookable there.)
3. **Course menu (MANDATORY):** click a `.menu-item-order-btn` ("Select"). Registers
   `#reservation_orders_attributes_0_menu_item_id`. Without it the availability AJAX errors.
4. **Date — use the mobiscroll API, NOT raw value, and do NOT dispatch a manual change:**
   `jQuery('#reservation_start_date').mobiscroll('setVal', new Date(y, m-1, d), true, true)` — the
   trailing `true, true` already fire mobiscroll's internal change and repopulate the epoch select.
   **Do NOT dispatch any manual `change` Event afterward** (even a plain native one) — it can submit
   the form → navigate to `about:blank`. Poll `#reservation_start_at_epoch` ~10s until options repopulate.
5. **Read slots** from `#reservation_start_at_epoch` `<option>`s (non-placeholder = available slot).
   **FULL signal = option COUNT, not the `disabled` attribute** — the select shows `disabled:true`
   even on available days. `count == 1` (only the `-- Select Time --` placeholder) = full/closed;
   `count > 1` = available. (Verified: Sushi Masato — its 5 Monday closures render exactly as count==1.)
6. STOP. Never click "Next Step" / submit.

### OLD-widget gotchas (hard-won)
- Setting `#reservation_start_date.value` directly does NOT stick (mobiscroll owns the model). Use `setVal`.
- **Any** `change` dispatch after `setVal` (jQuery `.trigger('change')` OR a plain native Event) can
  **submit the form → about:blank**. Rely on `setVal(date, true, true)` alone; dispatch nothing.
- **One fresh page-open + re-gate per date.** Sequential `setVal` calls within a single loaded page
  corrupt state and navigate to about:blank after ~2 dates — don't loop dates in one page lifecycle.
  After a bad navigation, recover via `close` + `pkill -f agent-browser-chrome` + fresh open.
- The `change` on the date input briefly blocks the CDP runtime (one `Runtime.evaluate` timeout is
  normal) — just re-poll.
- **Do NOT use the body-text `noavail` regex here** — it false-positives on the venue's allergen
  message ("We cannot accommodate…"). Trust the slot-select options / `disabled` state instead.

## NEW React widget ✅ verified (ADHOC Bangkok, 2026-05-30, party 2)

Detect generation: opening `/reserve` **302-redirects to `/reserve/message`** (or `/reserve/landing`),
and the page is full React (`data-testid` attributes everywhere). The actual flow uses **bottom-panel
openers**, NOT the predicted `Counter Select` / month-grid-by-default. Verified gate sequence:

1. **Anti-bot gate (CRITICAL for this engine's React widget):** agent-browser's own Chrome was
   **hard-stalled** — `document.body` never mounted, `readyState` stuck on `"loading"`, the
   `client.<hash>.js` React bundle was never injected (only head/Sentry scripts present), 0 testids.
   This is an anti-bot signal, NOT "no availability". **Fix: drive CloakBrowser stealth Chromium over
   CDP** (`references/clickthrough-technique.md` → "Anti-bot fallback"). Launch headless with a *fresh*
   `--user-data-dir` (a reused dir restores stale tabs → session jumps to the wrong venue, e.g. a
   leftover hungryhub tab), then `agent-browser --session <s> connect <port>`. Single tab only.
2. **Message gate:** `/reserve/message` shows a venue blurb + `data-testid="Footer Button"`
   ("Confirm and continue"). Wait for hydration (testids present), then `.click()` → `/reserve/landing`.
3. **Landing page** has four opener buttons: `Landing Pax Panel Opener Button` (defaults to "2 Guests"),
   `Landing Date Panel Opener Button` ("Sat May 30" = today), `Landing Time Panel Opener Button`
   ("Select a time"), `Landing Find A Table Button` ("Find availability"). **Party defaults to 2** —
   for party 2 you can skip the pax panel entirely.
4. **Date:** click `Landing Date Panel Opener Button` → a `Bottom Panel` ("Select a date") opens with a
   42/35-cell grid. Day cells are `<button data-testid="day" aria-label="<Weekday> <DayNum>">` (e.g.
   `aria-label="Saturday 6"`). **aria-label has NO month** — disambiguate by grid position. The current
   month page renders next-month days as `disabled`; click `data-testid="Calendar Next Month Button"`
   to page forward (booking horizon is ~7 days, so target dates a week+ out need the next-month page).
   On the next-month page the target month's days become enabled. Click the day → panel auto-closes and
   the date opener echoes "Sat Jun 6" (confirm this echo before trusting the read).
5. **Slots:** click `Landing Time Panel Opener Button` → `Bottom Panel` ("Select a time") shows a
   skeleton of **9 ZWNJ (`‌`) placeholders** while it fetches per-date times, then resolves.
   **MUST wait for the skeleton to clear** — do it in ONE eval: `await new Promise(r=>setTimeout(r,5000))`
   then read. **Do NOT rapid-poll with back-to-back evals** — that starves the fetch and either hangs on
   skeleton forever (`unresolved`) or reads a transient empty (FALSE `full`). Offered times =
   `data-testid="Landing Time Button"` (text like "12:00 pm"), grouped under "Lunch"/"Dinner" headers
   in the panel text. STOP here — never click a time button or "Find availability".

### NEW-widget status classification
| Settled panel state (after ~5s, `skel:false`) | status |
|---|---|
| ≥1 `Landing Time Button` | `available` (one record per slot; 12:00pm=Lunch, evening=Dinner) |
| 0 buttons + explicit "Sorry, there is no reservable time for Jun N" (skeleton cleared) | `full` |
| 0 buttons, panel text just "Select a time", no ZWNJ | `full` |
| ZWNJ skeleton never clears | `unresolved` (fetch hung — re-probe; do NOT call it full) |

**CRITICAL — date-select and time-read must be TWO SEPARATE evals.** Chaining "click date → open
time panel → wait 5s → read" in ONE eval starves the per-date fetch → FALSE empty/full. Do eval A
(select date, verify echo), then eval B (open time panel + own ~7.5s wait + read). After the
/message→/landing pass, all 30 dates can be probed in one page lifecycle (change date, no reload).

### NEW-widget gotchas (hard-won)
- The `Landing Time Button`s seen at <5s can be **pre-fetch default times that get replaced/cleared**
  once the date-specific fetch resolves — always read at the settled state. (ADHOC Jun 7 looked "full"
  on a fast poll but was 5 slots when settled; Jun 6 looked like 5 slots early, briefly went empty
  mid-fetch, then settled back to 5.)
- Reused CloakBrowser `--user-data-dir` restores prior tabs → agent-browser attaches to the wrong page
  (`about:blank` or another venue). Always `mktemp -d` a fresh dir; verify `get url` is the tablecheck tab.
- Date-specific variation is the live-data proof: ADHOC Saturdays = 5 slots (incl. 12pm lunch),
  Wednesdays = 4 dinner-only (no lunch). If every date is identical, suspect a static/pre-fetch read.

## Cases handled (ledger)
- ✅ OLD Rails, Tokyo, party 2 (Florilège) — real FULL days (Jun 7, Jun 24) vs available; sold-out =
  disabled empty slot-select. Venue party cap (4) respected.
- ✅ NEW React widget, Bangkok, party 2 (ADHOC) — bottom-panel opener flow; CloakBrowser-CDP needed
  (agent-browser Chrome anti-bot-stalled); 5s skeleton settle mandatory; date-specific slot variation
  (Sat 5 slots / Wed 4 dinner-only); all 6 target dates available, none booked out.
- ✅ OLD Rails full-30 (Sushi Masato, Bangkok) — 25 available / 5 full; the 5 "full" = weekly Monday
  closures (count==1 placeholder), NOT demand. Full signal = option-count, not `disabled`.
- ✅ NEW React real FULL date (ADHOC, Bangkok) — every Tuesday: explicit "Sorry, there is no reservable
  time" + 0 buttons. 25 available / 5 full over the month. Date-select & time-read must be separate evals.
- ⬜ OLD Rails course-menu variants / prepay gate (e.g. Bangkok Sorn).
- ⬜ NEW React party 4/6 (pax panel opener path).
- ⬜ Distinguishing weekly CLOSURE from genuine sold-out (both render as `full` on TableCheck).
- ⬜ Non-English locale date formats.
