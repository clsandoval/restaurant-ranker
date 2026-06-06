# restaurant-ranker

Restaurant ranker fuses editorial prestige, Google reviews, and live booking-demand into a
single Bayesian ranking that shows its own uncertainty and never fabricates confidence. It is
**read-only** — it reads availability and reviews to rank, and **never books anything**.

## Install (as a Claude Code plugin)

This plugin ships with a local dev marketplace so it loads in-repo without any publish step.

1. Add the local marketplace, pointing at `restaurant-ranker/.claude-plugin/marketplace.json`.
2. Install the plugin named `restaurant-ranker` from that marketplace.

The marketplace entry uses `"source": "./"`, so the plugin root is this directory.

## Required environment variables

Set these as env vars (the plugin never hardcodes paths or keys):

- `GOOGLE_MAPS_API_KEY` — Google Places / reviews enrichment.
- `FOURSQUARE_API_KEY` — Foursquare enrichment.

Optional:

- `ORS_API_KEY` — OpenRouteService (routing/isochrones).
- `MAPBOX_TOKEN` — Mapbox alternative.

**Graceful degradation:** when a key is absent, the affected source is skipped rather than
erroring out. The ranking proceeds with whatever signals are available, and the report notes
the reduced coverage.

## External CLI prerequisites

- `agent-browser` — the agentic-browse primitive used for browser-driven reads.
- For the anti-bot booking recipes (Turnstile / DataDome / ALTCHA): `cloakbrowser`,
  `patchright`, and `xvfb`.

## Read-only / never-books invariant

restaurant-ranker only **reads** availability, reviews, and prestige signals. It performs no
action that moves money or commits a reservation. There is no booking-write code path, by
design.

## Status

- **Phase 1 — Data pipeline:** DONE. `scripts/corpus.py`, `scripts/reviews.py`,
  `scripts/booking.py`, `scripts/cityconfig.py`, plus `cities/*.json` configs and the
  `skills/booking-probe/` recipes.
- **Phase 2 — Bayesian model + ranked report:** NOT yet implemented.
- **Phase 3 — Single orchestrator skill:** NOT yet implemented (`skills/restaurant-ranker/`
  is a stub).
