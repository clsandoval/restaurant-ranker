---
name: restaurant-ranker
description: >
  Rank a city's restaurants from one prompt — "rank the best restaurants in {city}",
  "which restaurants in {city} are worth it", "best places to eat in {city}", "top
  restaurants in {city}". Fuses editorial prestige + Google reviews + LIVE booking-demand
  into a Bayesian ranking with honest uncertainty intervals. Read-only — reads reservation
  calendars to measure demand, never books anything. Orchestrates the full pipeline:
  corpus → reviews → booking → model → render.
---

# restaurant-ranker

Fuses four independent signals — editorial prestige (best-of lists, Michelin), Google reviews
(rating + count), live booking-demand (revealed preference read off reservation calendars), and
booking friction (phone-only / lottery gate level) — into a single Bayesian latent-quality
ranking. Produces a `<slug>-board.md` with the ranked list, 94% HDI uncertainty intervals,
per-channel coverage flags, and honest treatment of off-platform venues. Read-only; it never
books anything.

Mechanical chain detail: `references/pipeline.md`.

---

## THE READ-ONLY LAW (non-negotiable)

**Read availability only. NEVER submit, confirm, or complete a reservation.**

Push through gates to *reach and read* the slot list (accept T&C, set party size, pick a
default course menu, dismiss cookie banners). Then STOP. Reading the offered slots IS the
probe. Clicking a slot, a "Next"/"Book"/"Confirm"/"Complete" button, or entering payment /
deposit details is a FAILURE of the task — it creates a real reservation, blocks a real table,
and violates lakbai's core anti-goal.

**Forbidden, no exceptions:**
- Don't click a time-slot button "just to see what happens" — it advances to checkout.
- Don't fill the final contact/payment form, even with fake data, even if "I'll stop before submit."
- Don't proceed past a deposit / credit-card-hold gate. Record the deposit requirement and stop.
- "Verifying it's really bookable" is NOT a reason to click through. Offered slot = the datapoint.

**Red flags — STOP immediately if you think any of these:**
- "Let me click one slot to confirm the flow works."
- "I'll fill the form but not hit submit."
- "The deposit step is fine, I'll just look at the next screen."
- "It's a test reservation, I'll cancel it after."

All of these mean: you are about to create a real booking. Back out. The slot list is enough.

This law governs the booking step (Step C') and any delegation to the `booking-probe` sibling
skill. It is a security invariant (T-03-01).

---

## Setup (run once, before first use)

**Model venv (required — system python3 cannot run model.py):**

```bash
# Install uv if absent
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }

# Create the 3.12 venv
uv venv /tmp/ranker-venv --python 3.12

# Install the model stack
uv pip install --python /tmp/ranker-venv/bin/python pymc arviz numpy h5netcdf
```

System `python3` is 3.10 and has no pymc/numpy — `model.py` raises `ImportError` on it. All
other steps use system `python3`. See `references/pipeline.md` §VENV SETUP for detail.

**API key (optional — reviews channel degrades gracefully if absent):**

Load from the uploaded `.env` file if present, then fall back to whatever is already in env:

```bash
[ -f /mnt/session/uploads/.env ] && set -a && source /mnt/session/uploads/.env && set +a
```

If the key is absent, the reviews channel is skipped and flagged in the coverage report. The
ranking still runs on prestige + booking-demand alone.

---

## THE WORKFLOW

Each step is a single action; do not batch. Observe the outcome of each step before proceeding.
Run all commands from **this skill's own directory** (the directory containing `scripts/` and `cities/`).

### Step A — Corpus (Seam 1: agent gathers venues via web_search)

**Warning: do NOT just shell `python3 scripts/corpus.py --city <city>`.** Its `gather_source()`
returns `[]` in the stdlib environment — running it alone writes an empty corpus.

The agent assembles the corpus itself:

1. Load the city config to find `prestige_sources`:
   ```python
   import sys; sys.path.insert(0, "scripts")
   from cityconfig import load_city
   cfg = load_city("<city>")
   ```
   If `UnknownCityError` is raised, STOP (see Checkpoint 1 below).

2. For each source in `cfg["prestige_sources"]`, run `web_search("<source_name> best restaurants <city>")` and collect venues. Build one row per venue:
   ```python
   row = {
       "venue": str,                     # canonical name
       "area": str | None,               # neighbourhood, or None
       "cuisine_raw": str,               # raw editorial cuisine label
       "prestige_sources": [str, ...],   # which source(s) named it
   }
   ```

3. Dedup and score:
   ```python
   from corpus import dedup, bucket_cuisine, normalize_name, _venue_slug
   deduped = dedup(rows)   # adds prestige_score, sources_n (NOT slug, NOT cuisine — add those explicitly after)
   for v in deduped:
       v["slug"] = _venue_slug(v["venue"])
       v["cuisine"] = bucket_cuisine(v.get("cuisine_raw"), cfg["cuisine_taxonomy"])
   ```

   **Why this loop is required:** `dedup()` returns records without `slug` or `cuisine`. `model.prepare_model_data` filters `[r for r in corpus if r.get("slug")]`, so any corpus record missing `slug` is silently discarded — meaning zero venues would be modeled without this loop. The `cfg` variable is already bound above by `cfg = load_city("<city>")`.

4. Write `deduped` to `<slug>-corpus.json` in the caller's CWD.

**Checkpoint 2:** Report "N venues gathered from S sources" before proceeding.

---

### Step B — Reviews

```bash
python3 scripts/reviews.py --city <city> --corpus <slug>-corpus.json
```

Writes `<slug>-reviews.json`. If `GOOGLE_MAPS_API_KEY` is absent, the channel is skipped and
flagged (`status: "skipped"`, reason: key not set). No action needed — proceed to Step C.

---

### Step C — Engine map (Seam 2: agent discovers booking engines)

The agent authors `<slug>-venues.json`. No script produces this file.

For each venue in `<slug>-corpus.json`, discover its booking engine and engine-specific
identifier. Delegate hard/anti-bot engines (TableCheck, Chope, OpenTable, etc.) to the
`booking-probe` sibling skill's `references/engine-routing.md`.

**File shape:**
```json
{
  "helm":        {"engine": "sevenrooms", "identifier": "helmbgc"},
  "toyo-eatery": {"engine": "eatigo",     "identifier": "12345"}
}
```

**CRITICAL — slug mismatch silently zeros fill:** keys MUST be the `slug` field from each
record in `<slug>-corpus.json` (the `_venue_slug` output), never the display name. A slug
mismatch causes the booking join to fail — every mismatched venue appears as missing fill in
the model, producing wide uncertainty that the data does not support. Always copy the `slug`
value verbatim from the corpus JSON.

Valid engines: `sevenrooms`, `eatigo`, `covermanager` (booking.py PROBERS), or any engine
listed in `cities/<slug>.json` under `booking_platforms`. Venues with no online booking engine
are simply omitted — `booking.py` flags them `gated`/`off_platform=True` with `fill=None`
(honesty rail BOOK-03). Never fabricate a fill value.

**Checkpoint 3:** Report engines resolved per venue before running booking.

---

### Step C' — Booking

```bash
python3 scripts/booking.py --city <city> --venues <slug>-venues.json
```

Writes `<slug>-booking.json`. HTTP-only, read-only. Prints `=== FILL EVIDENCE ===` table
and `Off-platform / no-signal venues: K/total`. THE READ-ONLY LAW applies here.

---

### Step D — Model

**Checkpoint 4 (before running):** Confirm "corpus + reviews + booking ready; X readable venues.
Fitting the Bayesian model now (this takes a few minutes)."

```bash
/tmp/ranker-venv/bin/python scripts/model.py \
  --city <city> \
  --corpus <slug>-corpus.json \
  --reviews <slug>-reviews.json \
  --booking <slug>-booking.json
```

**Never run model.py with `python3`** — it will raise ImportError. Always use the venv interpreter.

Writes `<slug>-results.json` and `<slug>-posterior.nc`. Prints `venues: N (R/T readable)` and
`divergences: D`. Aim for ≥10 readable venues so the booking-demand coefficient (β_b) is cleanly
identified. Fewer than 10 readable is still valid — the board reports this honestly
(`render.py _COVERAGE_FLOOR`).

---

### Step E — Render

```bash
python3 scripts/render.py --city <city> --results <slug>-results.json
```

Writes `<slug>-board.md`. The board already contains the §1 coverage line (N/T read live),
§3 honesty note (reviews-skipped notice, β_b verdict, off-platform flags), and
identifiability-floor status.

**Checkpoint 5:** Present the board path and the coverage report (see below).

---

## STEP DISCIPLINE (SKILL-03)

**Each step is a single action; do not batch.** Observe the outcome before acting again. This is
the snapshot → reason → act → re-snapshot loop — not autonomous multi-step automation.

Read-only steps (B, C', E) proceed without a y/n permission gate, but each is still a discrete
action whose output is observed before the next. The 5 named checkpoints require a confirmation
or report before proceeding:

| # | When | Action |
|---|------|--------|
| 1 | After city config loaded | If `UnknownCityError`: relay the actionable error (name the exact `cities/<slug>.json` path and `cities/_SCHEMA.md` reference) and **STOP**. Do not proceed to corpus. |
| 2 | After corpus assembled | Report "N venues gathered from S sources." Proceed to reviews. |
| 3 | After engine map built | Report engines resolved per venue. Proceed to booking. |
| 4 | Before model fit | Confirm "corpus + reviews + booking ready, X readable; fitting now." Proceed to model. |
| 5 | After render | Present board path + coverage report. Done. |

Narrate progress between checkpoints. Do NOT add a y/n gate before every micro-action. Do NOT
batch multiple steps without observing intermediate output.

---

## COVERAGE REPORT (SKILL-04)

After Step E, emit a one-line-per-channel ran-vs-skipped table built from each step's
already-emitted status signals. The render board (§1 + §3) already bakes the honest coverage
— this chat summary mirrors it. No new code required.

```
Channel    | Status
-----------|-----------------------------------------------------------------
corpus     | ran — N venues (S sources)
reviews    | ran — ok (N/T enriched)         OR  skipped (GOOGLE_MAPS_API_KEY not set)
booking    | ran — K/T off-platform; readable=R
gate       | ran — always present (derived from corpus/booking metadata)
model      | ran — R/T readable; divergences=D; rhat_max=X
render     | ran — board: <slug>-board.md; coverage floor (≥10) cleared / not cleared
```

Signals come from each step's existing stdout:

- **corpus:** `venues: N (deduped)` + len of corpus JSON. N == 0 → Seam 1 not done.
- **reviews:** `channel_status` printed as `reviews: ok|skipped (n/T enriched)`. Skipped reason names `GOOGLE_MAPS_API_KEY` (REV-02).
- **booking:** `=== FILL EVIDENCE ===` table + `Off-platform / no-signal venues: K/total`. Per-record `channel ∈ {readable, online-noslots, blocked-here, gated}`.
- **model:** `results.json.channel_coverage` = `{readable, total, reviews_status}`; `diagnostics` = `{divergences, rhat_max, ess_min}`. Printed as `venues: N (R/T readable)` + `divergences: D`.
- **render:** `<slug>-board.md` §1 coverage line + §3 honesty note contain N/T-read-live, reviews-skipped notice, and ≥10 identifiability-floor cleared/not.

---

## Related

- `skills/booking-probe/` — engine discovery recipes + THE READ-ONLY LAW origin; delegate hard engines here.
- `references/pipeline.md` — exact invocation chain, both seam contracts, venv setup detail.
