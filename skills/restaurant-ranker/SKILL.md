---
name: restaurant-ranker
description: Single-prompt orchestrator for restaurant-ranker. WILL wire the corpus → reviews → booking → model → render pipeline into one ranked report with honest uncertainty. Read-only, never books. WIP — not yet implemented.
---

# restaurant-ranker (orchestrator) — WIP STUB

This skill is the intended single-prompt entrypoint for the restaurant-ranker plugin.
When complete, it will run the full pipeline end to end and emit one ranked report.

**This is a placeholder. The orchestrator is NOT yet implemented.** Do not assume any
behavior described below already works — the sections marked NOT IMPLEMENTED have no code.

## What this plugin does (when complete)

Fuse editorial prestige, Google reviews, and live booking-demand into one Bayesian
ranking that shows its own uncertainty and never fabricates confidence. Read-only;
it never books anything.

## Status

### Phase 1 — Data pipeline — IMPLEMENTED

The pipeline scripts live under `scripts/`:

- `scripts/corpus.py` — build the candidate corpus (prestige/editorial fusion + dedup).
- `scripts/reviews.py` — Google reviews enrichment.
- `scripts/booking.py` — HTTP-only booking-demand probers (read-only).
- `scripts/cityconfig.py` — glob-based city config loader (`cities/*.json`).

City configs live under `cities/` (see `cities/_SCHEMA.md`).

### Phase 2 — Bayesian model + ranked report — NOT IMPLEMENTED

No model code exists yet. The Bayesian fusion of prestige + reviews + booking-demand
into a ranked report with honest uncertainty is still a TODO.

### Phase 3 — This orchestrator skill — NOT IMPLEMENTED

This skill does not yet wire the phases together. It is a stub.

## Related

- Sibling skill: `skills/booking-probe/` — the booking-demand probing recipes and
  reference docs used by `scripts/booking.py`.
- Pipeline scripts: `scripts/`.
