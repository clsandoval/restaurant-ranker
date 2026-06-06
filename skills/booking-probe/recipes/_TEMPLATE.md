# Recipe: <Platform> ⏳ pending

Read-only availability via agent-browser clickthrough. See `../references/clickthrough-technique.md`
for the shadow-DOM eval pattern and combined-signature matching. See
`../references/platform-knowledge.md` for known tokens/gates for this platform.

## Reservation URL shape
`<host/path pattern, e.g. https://www.opentable.com/r/<slug>>`

## Steps (one venue × date × party) — fill in as discovered
1. `open <url>` ; wait for hydration.
2. Dismiss cookie/consent banner if present.
3. Pass gates (T&C / party / course menu / deposit-aware) — DO NOT pass a payment step.
4. Select the target date (calendar or stepper).
5. Set party size.
6. Trigger the slot search/read (eval-click if shadow-DOM).
7. Read the slot list (a11y snapshot OR eval `body.innerText`). Dedup. STOP before any slot click.

## Classification
- slots parsed → `available` · gates passed, empty → `full` · closed/out-of-window → `no-slots`
- gate unpassable (incl. payment-gated calendar) → `gated` · unreadable/timeout → `unresolved`

## Party dimension
- [ ] party-relevant (probe 2/4/6)  OR  [ ] party-independent (probe 2 only) — decide from the widget.

## Cases handled (ledger — append as venues clear)
- ⬜ first verified venue + date/party + slot count

## Open / unverified cases
- ⬜ widget generations? · ⬜ sold-out rendering? · ⬜ deposit gate? · ⬜ locale/timezone?
