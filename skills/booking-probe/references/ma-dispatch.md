# MA dispatch — one Managed Agent session per restaurant

How the booking probe fans out: each restaurant becomes one **Claude Managed Agent (MA)** session
that runs its platform recipe autonomously via agent-browser and commits a per-venue JSON. Build
up **sequentially** (one at a time) until a recipe is bulletproof, then widen parallelism.

## Two ways to dispatch

- **Preferred: the `autopilot` skill** (`/autopilot`). It enforces the three-gate pipeline
  (credentials + outcome checklist + behavior brief) and refuses to launch with a gate unfilled.
  Use it; don't hand-roll the API unless you need something it doesn't cover.
- **Raw MA API** (for monitoring/scripting): see the cheat sheet below. For investigating what a
  session actually did, use the `investigate-cma` skill — the MA API is the source of truth.

## MA API conventions (curl via Bash)

```bash
set -a; source .env; set +a            # ANTHROPIC_API_KEY is canonical from .env; Bash state doesn't persist
curl -sS https://api.anthropic.com/v1/{endpoint} \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "anthropic-beta: managed-agents-2026-04-01" \
  -H "content-type: application/json"
# uploading the booking-probe skill to the agent: add  -H "anthropic-beta: skills-2025-10-02"
```

| What | Method + Path |
|---|---|
| Create agent (per job) | `POST /v1/agents` (updates need a `version` field — optimistic concurrency) |
| Get session status | `GET /v1/sessions/{id}` — check **`stop_reason`** |
| Session events (paginated) | `GET /v1/sessions/{id}/events?limit=200` (limit max 100–200) |
| Live tail | `GET /v1/sessions/{id}/events/stream` |

**`stop_reason`:** `end_turn` = done · `requires_action` = blocked, waiting on `ask_user`
(surface the question, answer it, resume). Filter out `agent.thinking` events when displaying.

## The brief for a booking-probe dispatch (the three gates)

**Gate 1 — Credentials.** The probe is **anonymous and read-only** — it needs NO booking-site
login or payment credentials (that's the point). The only requirement is the runtime: the agent
container must have **agent-browser + its Chrome** installed (`npm i -g agent-browser` →
`agent-browser install --with-deps`). Put that in the brief's setup. (No booking creds is itself a
safety property — the agent literally cannot complete a paid booking.)

**Gate 2 — outcome.md (self-verifiable done-criteria):**
- Produced `./<city>-booking-probe/clickthrough/<venue-slug>.json` with one record per
  (date × party) over the target grid.
- **Every unit resolved** to available / full / no-slots — zero `unresolved`/`error` (retry the
  recipe on any hole until clean, or report the specific blocker if truly impossible).
- **NO reservation was created** — the agent confirms it never clicked a slot / Next / Confirm /
  payment. This is the top line of the checklist; the agent self-attests to it.

**Gate 3 — behavior.md (the path):**
- Front-load **THE READ-ONLY LAW** verbatim from SKILL.md (forbidden actions + red flags).
- The platform recipe steps (`recipes/<platform>.md`) — or instruct the agent to read the
  uploaded booking-probe skill and follow the matching recipe.
- One `agent-browser --session lakbai-<venue-slug>` for this restaurant.
- Stop conditions: slot list read → record → done; deposit/payment gate → record `gated`, STOP;
  unreadable after retries → `unresolved` with the blocker; never fabricate a status.

**Upload the booking-probe skill to the agent** (skills-2025-10-02 beta) so its recipes +
references travel with the job — the agent's expertise = this skill.

## Environment caveat (important)

The MA container routes outbound traffic through an **HTTP/HTTPS proxy — no direct TCP.** Chrome's
HTTPS works through the proxy, so agent-browser should function, but **verify on the first dispatch**
(open a known venue, snapshot — a stripped tree = proxy/anti-bot block, not "no availability").
If a platform is blocked in-container, fall back to CloakBrowser or run that platform locally.

## Persistence & collection

Git is the MA persistence layer — the agent commits the per-venue JSON to an `autopilot/<slug>`
branch as it works. Collect results via `/autopilot status` (PRs are created by the orchestrator;
`gh` doesn't run in-container). The per-venue-file layout means N restaurant sessions never contend
on one file.

## Sequencing (the one-at-a-time rule)

Dispatch **one** restaurant, watch it to `end_turn`, confirm zero-unresolved + no-booking, fold any
new failure into the recipe (`recipes/<platform>.md` ledger). Only after a recipe clears a diverse
venue set do you fan out many sessions of that platform in parallel.
