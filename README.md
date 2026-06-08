# restaurant-ranker

Restaurant ranker fuses editorial prestige, Google reviews, and live booking-demand into a
single Bayesian ranking that shows its own uncertainty and never fabricates confidence. It is
**read-only** — it reads availability and reviews to rank, and **never books anything**.

## What it does

One prompt — `rank the best restaurants in <city>` — drives a 5-step pipeline:

1. Corpus (agent `web_search` gathering of editorial prestige venues)
2. Reviews enrichment (Google Places rating + count)
3. Booking engine discovery (agent maps each venue to its reservation platform)
4. Booking demand probe (live HTTP reads — read-only, never books)
5. Bayesian model + rendered board (4-section `<slug>-board.md` with 94% HDI + coverage flags)

Output: a `<slug>-board.md` in the caller's CWD — one markdown file to read and feel the city.
No tab-switching, no raw list of 30 places, no fabricated confidence.

---

## Install (as a Claude Code plugin)

This plugin ships with a local dev marketplace so it loads in-repo without any publish step.

1. Add the local marketplace, pointing at `restaurant-ranker/.claude-plugin/marketplace.json`.
2. Install the plugin named `restaurant-ranker` from that marketplace.

The marketplace entry uses `"source": "./"`, so the plugin root is this directory.

---

## Build the model venv (required)

System `python3` is 3.10 and **cannot run `model.py`** — `import pymc` and `import numpy` both
fail on it. You must build a uv-managed Python 3.12 venv once before the first run.

```bash
# Install uv if absent (uv 0.11.18 verified on the reference machine)
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }

# Create the 3.12 venv
uv venv /tmp/ranker-venv --python 3.12

# Install the model stack
uv pip install --python /tmp/ranker-venv/bin/python pymc arviz numpy h5netcdf
```

All other steps (corpus helpers, reviews, booking, render) use system `python3` and need no venv.
Only Step D (`model.py`) requires the venv interpreter: `/tmp/ranker-venv/bin/python`.

---

## Environment variables

Set these as shell env vars (the plugin never hardcodes paths or keys; never commit a key):

```bash
export GOOGLE_MAPS_API_KEY=<your-key>   # Reviews enrichment (Google Places)
```

**Graceful degradation:** if `GOOGLE_MAPS_API_KEY` is absent, the reviews channel is skipped
rather than erroring out. The model runs on prestige + booking-demand alone, and the board flags
the skip in the honesty note. The ranking is still valid; it just has one fewer signal.

Optional enrichment keys:

```bash
export FOURSQUARE_API_KEY=<your-key>    # Foursquare enrichment
export ORS_API_KEY=<your-key>           # OpenRouteService (routing/isochrones)
export MAPBOX_TOKEN=<your-token>        # Mapbox alternative for routing
```

---

## Usage

### Shipped city (manila)

Manila ships out of the box. Open a Claude Code session and type:

```
rank the best restaurants in manila
```

The orchestrator skill (`skills/restaurant-ranker/SKILL.md`) drives the 5-step pipeline and
produces `manila-board.md` in your CWD. See `skills/restaurant-ranker/SMOKE.md` for the
step-by-step smoke check and expected artifacts.

### Cold city (new city you configure)

To rank a city not yet in `skills/restaurant-ranker/cities/`, author
`skills/restaurant-ranker/cities/<slug>.json` following
`skills/restaurant-ranker/cities/_SCHEMA.md` (CONFIG-02 — no code change needed, only the JSON config). Then invoke:

```
rank the best restaurants in <city>
```

---

## Optional booking-engine escalation

The core flow uses HTTP-only probers for SevenRooms, Eatigo, and CoverManager — **no browser
required** for those engines. `agent-browser`, `cloakbrowser`, `patchright`, and `xvfb` are
only needed if a venue's booking platform uses hard anti-bot protection (Turnstile, DataDome,
ALTCHA). Most cities' booking coverage is achieved without them. See
`skills/booking-probe/references/engine-routing.md` for when escalation applies.

---

## Read-only / never-books invariant

restaurant-ranker only **reads** availability, reviews, and prestige signals. It performs no
action that moves money or commits a reservation. There is no booking-write code path, by
design.

---

## Status

- **Phase 1 — Data pipeline:** DONE. `skills/restaurant-ranker/scripts/corpus.py`,
  `skills/restaurant-ranker/scripts/reviews.py`, `skills/restaurant-ranker/scripts/booking.py`,
  `skills/restaurant-ranker/scripts/cityconfig.py`, plus `skills/restaurant-ranker/cities/*.json`
  configs and the `skills/booking-probe/` recipes.
- **Phase 2 — Bayesian model + ranked report:** DONE. `skills/restaurant-ranker/scripts/model.py`
  (PyMC 4-channel Bayesian fit; 94% HDI intervals),
  `skills/restaurant-ranker/scripts/render.py` (4-section board), 188 automated tests.
- **Phase 3 — Single orchestrator skill:** DONE. `skills/restaurant-ranker/` — one prompt
  drives the full 5-step chain via `SKILL.md` + `references/pipeline.md`.
