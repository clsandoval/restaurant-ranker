# Recipe: Superb / Formitable ✅ verified

Read-only availability via CloakBrowser clickthrough. **Superb is the engine behind Formitable
widgets.** Availability sits behind an **ALTCHA proof-of-work** challenge — a *lighter* wall than
Cloudflare Turnstile / DataDome. Verified on **Copenhagen (iter3)** — ALTCHA cleared HEADLESS, dates
endpoint read.

## Anti-bot — use CloakBrowser (NOT plain agent-browser)

Active **ALTCHA proof-of-work** gates the availability endpoint; plain `agent-browser` is TLS-blocked
on Managed Agents (spike 023). Use **CloakBrowser stealth** per the shared
`../references/platform-knowledge.md` (§ Anti-bot escalation tier). **Per-engine deviation:** the
ALTCHA proof-of-work is solved transparently by plain cloakbrowser stealth **HEADLESS** —
`backend="patchright"` is harmless but **NOT required**, so the patchright + xvfb tier is **optional**
here; plain cloakbrowser stealth headless suffices.

Engine fingerprint: availability behind `api-gx.superbexperience.com/availability/dates` (the
ALTCHA-gated endpoint).

## Reservation URL shape
Venue widget (Superb / Formitable embed) → availability behind
`api-gx.superbexperience.com/availability/dates`.

## Steps (one venue × date × party)
1. Load the venue widget with cloakbrowser stealth (headless OK here).
2. The **ALTCHA proof-of-work is solved transparently** by the stealth browser — no manual gesture.
3. Read the `/availability/dates` response off the network for the dates grid. **STOP at the read —
   never POST / confirm / book.**

## Classification
- Dates with slots → `available`.
- Cleared but empty → `full`.
- ALTCHA never clears / endpoint 403 → `unresolved` (with a blocker note; never `full`).
- **Party dimension:** decide from the widget — mark as unverified until a concrete venue confirms.

## Cases handled (ledger)
- ✅ Copenhagen iter3 — ALTCHA cleared headless via cloakbrowser, dates endpoint read.

## Open / unverified cases
- ⬜ concrete venue slug + party behavior.
- ⬜ per-slot fill detail.
