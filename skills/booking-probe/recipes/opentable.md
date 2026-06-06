# Recipe: OpenTable ✅ verified

Read-only availability via CloakBrowser clickthrough. OpenTable sits behind a **DataDome** anti-bot
wall. Verified on a **Copenhagen venue (iter3)** — DataDome cleared, `RestaurantsAvailability` GraphQL
slots read. (This **promotes** OpenTable from the prior "⏳ new engines" stub.)

## Anti-bot — use CloakBrowser (NOT plain agent-browser)

Active **DataDome** challenge gates the restaurant page; plain `agent-browser` is TLS-blocked on
Managed Agents (spike 023). Use **CloakBrowser** per the shared `../references/platform-knowledge.md`
(§ Anti-bot escalation tier). **Per-engine deviation:** plain cloakbrowser **humanize** clears DataDome
— `backend="patchright"` is **NOT required** (but harmless). The DataDome `dapi/fe/human` call returns
200 once humanize behavior runs.

## Reservation URL shape
`opentable.com/r/{slug}` (or `opentable.dk`).

**Caveat:** an OpenTable listing can be **informational-only** and route to the real engine (e.g.
Sézanne's OpenTable page → OMAKASE). Verify the page actually shows slots before classifying.

## Steps (one venue × date × party)
1. Navigate the restaurant page with cloakbrowser **humanize**.
2. The DataDome `dapi/fe/human` call returns **200** (challenge cleared).
3. The `RestaurantsAvailability` GraphQL response carries the real slots (DOM shows the time-picker
   buttons, e.g. 6:30–7:30 PM). **Capture that GraphQL response body off the network** for the clean
   signal; fall back to reading the rendered slot buttons. **STOP at the read — never click a slot /
   Reserve / payment.**

## Classification
- GraphQL / DOM slots parsed → `available`.
- Cleared + empty → `full`.
- Informational-only listing / DataDome not cleared → `unresolved` (note the blocker), **never
  `full`**.

## Cases handled (ledger)
- ✅ Copenhagen venue (iter3) — DataDome `dapi/fe/human` 200, `RestaurantsAvailability` slots read.

## Open / unverified cases
- ⬜ informational-only vs real-engine routing.
- ⬜ Resy / Tock siblings.
