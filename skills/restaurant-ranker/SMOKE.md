# SMOKE — restaurant-ranker manila runbook

Manual smoke check for the orchestrator: one cold run on `manila` (the shipped city) that
confirms the full 5-step chain produces all artifacts. No automated harness exists for a
SKILL.md; this is the runbook to run before each wave merge or release.

---

## Purpose

Confirm that the pipeline — corpus → reviews → booking → model → render — produces:

```
manila-corpus.json
manila-reviews.json
manila-venues.json
manila-booking.json
manila-results.json
manila-board.md
```

...and that `manila-board.md` contains the 4 board sections + a coverage line.

The Phase 3 gate is board existence (`manila-board.md` produced by the chain). A full
live cold-city run on a non-manila city is Phase 4's job; do NOT require it here.

---

## Prerequisites

1. **Model venv built** (see README). Specifically:
   - `uv` installed (0.11.18 or later)
   - `/tmp/ranker-venv/bin/python` exists with pymc, arviz, numpy, h5netcdf

2. **System `python3`** available (3.10 is fine for all steps except D).

3. **`GOOGLE_MAPS_API_KEY`** is **optional** for this smoke. Without it, the reviews
   channel is skipped and flagged in the board's honesty note. That is the normal
   SKILL-04 ran-vs-skipped path — eyeball the coverage report to confirm the skip is
   flagged correctly, not silently dropped.

   To smoke WITH reviews:
   ```bash
   export GOOGLE_MAPS_API_KEY=<your-key>
   ```

4. Working directory: **plugin root** (the directory containing `scripts/` and `cities/`).

---

## Step-by-step run

Run all commands from the plugin root. Steps B, C', D, and E are shell commands; Steps A and
C require the agent to fill in the seams (web_search + engine discovery).

### Step A — Corpus (Seam 1: agent gathers venues via web_search)

Open a Claude Code session in the plugin root and invoke:

```
rank the best restaurants in manila
```

The orchestrator's Step A has the agent run `web_search` for each prestige source in
`cities/manila.json`, build corpus rows, call `corpus.dedup()`, and write:

```
manila-corpus.json
```

Confirm: "N venues gathered from S sources" checkpoint appears before proceeding.

### Step B — Reviews

```bash
python3 scripts/reviews.py --city manila --corpus manila-corpus.json
```

Writes `manila-reviews.json`. If `GOOGLE_MAPS_API_KEY` is absent, the script prints
`reviews: skipped (GOOGLE_MAPS_API_KEY not set)` and writes the file with
`{"status": "skipped", ...}`. Either outcome is valid — note which path ran.

### Step C — Engine map (Seam 2: agent discovers booking engines)

The agent (still in the same session) authors `manila-venues.json` — a JSON object mapping
each venue's corpus `slug` to its booking engine and identifier. Example shape:

```json
{
  "helm": {"engine": "sevenrooms", "identifier": "helmbgc"},
  "toyo-eatery": {"engine": "eatigo", "identifier": "12345"}
}
```

Confirm: "engines resolved per venue" checkpoint appears before running booking.

### Step C' — Booking

```bash
python3 scripts/booking.py --city manila --venues manila-venues.json
```

Writes `manila-booking.json`. Prints `=== FILL EVIDENCE ===` table and
`Off-platform / no-signal venues: K/total`. Read-only — confirm no reservation was made.

### Step D — Model (requires venv python)

```bash
/tmp/ranker-venv/bin/python scripts/model.py \
  --city manila \
  --corpus manila-corpus.json \
  --reviews manila-reviews.json \
  --booking manila-booking.json
```

Writes `manila-results.json` and `manila-posterior.nc`. Prints
`venues: N (R/T readable)` and `divergences: D`. Fit takes a few minutes.

**Never run model.py with `python3`** — it will raise ImportError. Always use the venv path.

### Step E — Render

```bash
python3 scripts/render.py --city manila --results manila-results.json
```

Writes `manila-board.md`. The board contains:
- §1 coverage line (N/T read live)
- §2 ranked list with 94% HDI intervals
- §3 honesty note (reviews-skipped notice if applicable, β_b verdict, off-platform flags)
- §4 diagnostics (divergences, rhat_max, ess_min)

---

## File-existence asserts

After the full run, confirm all artifacts exist and the board has the expected shape.
Copy-paste this bash one-liner from the plugin root:

```bash
for f in manila-corpus.json manila-reviews.json manila-venues.json manila-booking.json manila-results.json manila-board.md; do
  [ -f "$f" ] && echo "OK  $f" || echo "MISSING $f"
done && grep -qE "coverage|read live|HDI|divergences" manila-board.md && echo "board OK" || echo "board shape FAIL"
```

Expected output: six `OK` lines followed by `board OK`.

---

## Structural pre-checks (automated — run before smoke)

These tests do NOT require the model venv or live HTTP; they validate the board-shape contract
and script interfaces that the orchestrator skill depends on. Run them first to confirm the
baseline is clean before the live run.

### Per-task (fast, no venv needed)

```bash
python3 scripts/test_render.py
```

Validates the board-shape contract: render.py produces all 4 sections, coverage line,
honesty note, β_b verdict. If this fails, the board the orchestrator would render is broken —
fix before proceeding.

### Per-wave-merge (full suite; model tests need venv)

```bash
# System python3 — all tests except model tests
python3 -m unittest discover -s scripts -p 'test_*.py'

# Model tests (require the venv)
/tmp/ranker-venv/bin/python -m unittest scripts/test_model.py
```

188 tests total across corpus, reviews, booking, model, render, cityconfig. Full suite is the
wave-merge gate. Per-task, `test_render.py` alone is sufficient.

---

## Smoke gate

Phase 3 gate: `manila-board.md` exists and the board-shape contract is satisfied
(`python3 scripts/test_render.py` passes).

Phase 4 gate (not here): a live cold-city run on a non-manila city.
