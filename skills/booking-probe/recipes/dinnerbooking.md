# Recipe: DinnerBooking ✅ verified

Read-only availability via CloakBrowser clickthrough. DinnerBooking is a Cloudflare-Turnstile-walled
Danish/Nordic booking engine. **easyTable is the same Turnstile family** — it shares this recipe
(discover its per-venue widget URL + slots endpoint the same way: inspect the booking iframe + the
network tab). Verified on **AOC Copenhagen (iter3)** — Turnstile cleared, slots read with dates incl.
waitlist-only days.

## Anti-bot — use CloakBrowser (NOT plain agent-browser)

Active **Cloudflare Turnstile** (interaction-only) challenge gates the booking widget; plain
`agent-browser` is TLS-blocked on Managed Agents (spike 023) and plain stealth Chromium does not
reliably clear the challenge. Use the **patchright + xvfb escalation tier** documented in
`../references/platform-knowledge.md` (§ Anti-bot escalation tier — CloakBrowser + patchright + xvfb):
run a plain SYNC `launch_context(headless=False, humanize=True, human_preset="careful",
backend="patchright", ignore_https_errors=True, args=["--ignore-certificate-errors"])` under
`xvfb-run -a -s "-screen 0 1920x1080x24"`. `backend="patchright"` is THE key — with it the Turnstile
token issues in <1s. No per-engine deviation from the shared launch config.

Engine fingerprint: interaction-only Turnstile (sitekey e.g. `0x4AAAAAAANghrZGVRYnOyan`, action
`pax`), callback `enableBookPaxButton` that ungates the Next button.

## Reservation URL shape
`book.dinnerbooking.com/dk/en-US/book/table/pax/{venueId}/1`

## Steps (one venue × date × party)
1. **Accept the Cookiebot banner FIRST:** click
   `#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll`.
2. **Clear Turnstile:** human mouse-move + click the `.cf-turnstile` bounding box. With
   `backend="patchright"` the token issues in **<1s** (≈837-char `cf-turnstile-response`) — no long
   wait needed.
3. **Set party size on the REAL jQuery-UI spinner:** click `button.ui-spinner-up` ×2 → pax=2. Do NOT
   force-click a disabled Next; let the `enableBookPaxButton` callback drop the `disabled` attr.
4. **Poll the Next button:** poll `#submit-pax-next-step` until it loses `disabled` / the
   `disabled-button` class, then click it (never force-click — the callback ungates it naturally).
5. **Capture the network JSON:** `GET /dk/en-US/times/index/{venueId}/1/{pax}.json` returns
   `{"openTimes":..., "waitingTimes":[{"Time":{"time":"18:00:00"}}, ...]}`. Walk the calendar grid by
   selecting dates. **STOP at the read — never POST / confirm / book.**

## Classification
- `openTimes` entries = bookable → `available`.
- `openTimes:null` + populated `waitingTimes` = fully booked / waitlist-only → counts as `full`
  (filled=grid for fill math).
- Unreadable / token never issues / nav timeout → `unresolved` with a blocker note (never `full`).

## Cases handled (ledger)
- ✅ AOC Copenhagen (iter3) — Turnstile cleared via patchright, slots read with dates incl.
  waitlist-only days.

## Open / unverified cases
- ⬜ easyTable concrete venue (same Turnstile family — verify widget URL + slots endpoint).
- ⬜ multi-meal grid (lunch vs dinner per date).
