# REPRODUCE — restaurant-ranker Lisbon runbook

Lisbon specialization of `skills/restaurant-ranker/SMOKE.md`. Replace every `manila` token in
SMOKE.md with `lisbon` and apply the Lisbon-specific divergences documented here. This is a
**verified runbook** for a stranger to reproduce the full Lisbon cold-city proof end-to-end.

---

## What the user runs vs. what the agent did

**Agent (autonomous — already complete):**
- Authored `cities/lisbon.json` (the Lisbon city config, discovered automatically by the
  `cities/*.json` glob — no code change required).
- Authored this `examples/lisbon/REPRODUCE.md` runbook.

**User (live run — human-action checkpoint, plan 04-02):**
- The user holds `GOOGLE_MAPS_API_KEY` and the anti-bot-capable local network environment.
- The user drives Steps A–E below inside a Claude Code session from the plugin root.
- After the run completes, the agent commits the output bundle to `examples/lisbon/`.

The live run is the Phase-4 proof (D-04). Do not attempt it without `GOOGLE_MAPS_API_KEY` set —
without the key the reviews channel is skipped and the board is not the locked full-run proof.

---

## Purpose

Confirm that the pipeline — corpus → reviews → booking → model → render — produces:

```
lisbon-corpus.json
lisbon-reviews.json
lisbon-venues.json
lisbon-booking.json
lisbon-results.json
lisbon-board.md
```

...and that `lisbon-board.md` contains the 4 board sections + a coverage line with
`reviews ok` (not `skipped`).

City config lives at `cities/lisbon.json` (single source of truth — do NOT duplicate the JSON here).

---

## Prerequisites

### 1 — Build the model venv (one-time; `/tmp` is ephemeral — rebuild if absent)

`model.py` requires Python 3.12 + pymc/arviz/numpy/h5netcdf. The system `python3` (3.10) does
not have these packages. Build the venv BEFORE running Step D:

```bash
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }
uv venv /tmp/ranker-venv --python 3.12
uv pip install --python /tmp/ranker-venv/bin/python pymc arviz numpy h5netcdf
```

Confirm: `/tmp/ranker-venv/bin/python -c "import pymc; print('venv OK')"` prints `venv OK`.

**If you see `ModuleNotFoundError: No module named 'pymc'` at Step D**, the venv was not built
or was deleted (ephemeral `/tmp`). Rebuild it before retrying.

### 2 — System `python3` available (3.10 is fine for steps B, C', E)

```bash
python3 --version   # 3.10.x or later
```

### 3 — Export `GOOGLE_MAPS_API_KEY` (REQUIRED — set via env var, never paste the key)

The reviews channel is REQUIRED for the Lisbon proof. Set the key in your shell before running:

```bash
export GOOGLE_MAPS_API_KEY=<your-key>
```

**Never paste your API key into any file or command transcript.** Keep it in your shell env only.
The coverage report MUST show `reviews: ran — ok`, NOT `skipped`. If you see `skipped`, the key
was not exported.

### 4 — Working directory: plugin root

All commands below run from the **plugin root** (the directory containing `scripts/` and `cities/`).
Outputs land in the **caller's CWD** with `lisbon-` prefix.

```bash
cd path/to/restaurant-ranker   # the dir with scripts/, cities/, skills/
```

---

## Step-by-step run

Run all commands from the plugin root. Steps B, C', D, and E are shell commands. Steps A and C
require the agent to fill in the seams (web_search + engine discovery).

### Step A — Corpus (Seam 1: agent gathers venues via web_search)

Open a Claude Code session in the plugin root and invoke:

```
rank the best restaurants in lisbon
```

The orchestrator's Step A has the agent run `web_search` for each prestige source in
`cities/lisbon.json`, build corpus rows, call `corpus.dedup()`, and write:

```
lisbon-corpus.json
```

Confirm: "N venues gathered from S sources" checkpoint appears before proceeding.

> **SEAM-1 WARNING:** Do NOT run `python3 scripts/corpus.py` alone to build the corpus.
> `corpus.py:gather_source()` is an intentional stub that returns `[]`. The corpus is filled
> by the agent's in-session `web_search` calls — NOT by shelling the script directly.
> Running `python3 scripts/corpus.py` alone writes an **empty corpus** and silently breaks
> every downstream step.

### Step B — Reviews

```bash
python3 scripts/reviews.py --city lisbon --corpus lisbon-corpus.json
```

Writes `lisbon-reviews.json`. `GOOGLE_MAPS_API_KEY` is **REQUIRED** for the Lisbon proof (D-03).
The coverage report must show `reviews: ran — ok (N/T enriched)`, NOT `skipped`.

If you see `reviews: skipped (GOOGLE_MAPS_API_KEY not set)`, export the key and re-run.

### Step C — Engine map (Seam 2: agent discovers booking engines)

The agent (still in the same session) authors `lisbon-venues.json` — a JSON object mapping
each venue's corpus `slug` to its booking engine and identifier. Example shape:

```json
{
  "belcanto": {"engine": "sevenrooms", "identifier": "belcanto"},
  "boa-bao-lisboa": {"engine": "covermanager", "identifier": "restaurante-boa-bao-lisboa"}
}
```

Confirmed readable engines in Lisbon: **SevenRooms** (Belcanto, Alma, Tapisco, Rocco, Pizzaria
Lisboa, Gunpowder, BAHR) and **CoverManager** (Boa-Bao, Time Out Market Lisboa, and others).

> **SEAM-2 WARNING:** Keys in `lisbon-venues.json` MUST be the corpus `slug` verbatim (as
> produced by `corpus.py:_venue_slug` and written into `lisbon-corpus.json`). Never use a
> display name as a key. A slug mismatch silently zeros the booking fill for that venue —
> it appears as missing fill (wide uncertainty the data does not justify) even when the booking
> endpoint is live and readable.
>
> Copy the `slug` field from `lisbon-corpus.json` for each venue, then author the map.

> **OFF-PLATFORM REQUIREMENT (D-06 honesty flag):** Include at least one genuine off-platform
> Lisbon venue in the corpus — for example, **Cervejaria Ramiro** (phone/walk-in, no online
> booking), **Taberna da Rua das Flores**, or **O Velho Eurico** (no reservations). Omit these
> from `lisbon-venues.json` (or map to an unknown engine). `booking.py` will flag them as
> `gated`/`off_platform=True`, `fill=None`, and the board renders `—` in the fill column with
> a wide HDI interval.

Confirm: "engines resolved per venue" checkpoint appears before running booking.

### Step C' — Booking

```bash
python3 scripts/booking.py --city lisbon --venues lisbon-venues.json
```

Writes `lisbon-booking.json`. Prints `=== FILL EVIDENCE ===` table and
`Off-platform / no-signal venues: K/total`. Read-only — confirm no reservation was made.

### Step D — Model (requires venv python — NEVER system python3)

```bash
/tmp/ranker-venv/bin/python scripts/model.py \
  --city lisbon \
  --corpus lisbon-corpus.json \
  --reviews lisbon-reviews.json \
  --booking lisbon-booking.json
```

Writes `lisbon-results.json` and `lisbon-posterior.nc`. Prints
`venues: N (R/T readable)` and `divergences: D`. Fit takes a few minutes.

> **NEVER run `model.py` with system `python3`** — it will raise `ImportError: No module named 'pymc'`.
> Always use `/tmp/ranker-venv/bin/python`. If the venv is absent, rebuild it (see Prerequisites).

### Step E — Render

```bash
python3 scripts/render.py --city lisbon --results lisbon-results.json
```

Writes `lisbon-board.md`. The board contains:
- §1 coverage line (N/T read live)
- §2 ranked list with 94% HDI intervals
- §3 honesty note (β_b verdict, off-platform flag, reviews-skipped notice ONLY if skipped — must
  be ABSENT in the Lisbon full-key run)
- §4 diagnostics (divergences, rhat_max, ess_min)

---

## File-existence asserts

After the full run, confirm all artifacts exist and the board has the expected shape.
Copy-paste this bash one-liner from the plugin root:

```bash
for f in lisbon-corpus.json lisbon-reviews.json lisbon-venues.json lisbon-booking.json lisbon-results.json lisbon-board.md; do
  [ -f "$f" ] && echo "OK  $f" || echo "MISSING $f"
done && grep -qE "coverage|read live|HDI|divergences" lisbon-board.md && echo "board OK" || echo "board shape FAIL"
```

Expected output: six `OK` lines followed by `board OK`.

---

## Structural pre-checks (automated — run before the live run)

These tests do NOT require the model venv or live HTTP; they validate the board-shape contract
and script interfaces that the orchestrator skill depends on. Run them first to confirm the
baseline is clean before the live run.

### Per-task (fast, no venv needed)

```bash
python3 scripts/test_render.py
```

Validates the board-shape contract: `render.py` produces all 4 sections, coverage line,
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

## D-06 acceptance grep block

After the live run, verify the board satisfies the Phase-4 pass bar:

```bash
grep -q "## 2 · TOP-" lisbon-board.md                              # (1) ranked list present
grep -qE "\[\+?-?[0-9].*,.*[0-9]\]" lisbon-board.md               # (2) q̄ [94% HDI] present
grep -q "Off-platform" lisbon-board.md || grep -q "—" lisbon-board.md  # (3) off-platform honesty flag
grep -q "reviews\*\* ok" lisbon-board.md                           # D-03: reviews ran (not skipped)
echo "D-06 board checks passed"
```

All four greps must succeed. If any fails:
- `(1)` fails: board shape broken — run `python3 scripts/test_render.py` and fix before re-running.
- `(2)` fails: model did not produce HDI intervals — check `lisbon-results.json` for schema issues.
- `(3)` fails: no off-platform venue in corpus or all venues were mapped in `lisbon-venues.json` —
  ensure at least one off-platform venue (Cervejaria Ramiro / Taberna da Rua das Flores / O Velho
  Eurico) was included in the corpus but omitted from `lisbon-venues.json`.
- `(4)` fails: `GOOGLE_MAPS_API_KEY` was not exported — export it and re-run from Step B.

---

## Smoke gate

Phase 4 gate: `lisbon-board.md` exists, the board-shape contract is satisfied
(`python3 scripts/test_render.py` passes), and the D-06 acceptance grep block above returns all
four matches (ranked list + HDI + off-platform flag + reviews ran).
