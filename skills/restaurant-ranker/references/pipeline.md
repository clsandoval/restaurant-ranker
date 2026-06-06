# Pipeline Reference — restaurant-ranker

Mechanical detail for the `restaurant-ranker` orchestrator. The SKILL.md links here for the exact
invocation chain, data contracts, and venv setup. All commands run from the **plugin root** (the
directory containing `scripts/` and `cities/`). All outputs land in the **caller's CWD** with
`<slug>-` prefixes — every script defaults `--out` to `os.getcwd()/<slug>-<artifact>`.

---

## THE EXACT INVOCATION CHAIN

| Step | Command | Reads | Writes | Env needed |
|------|---------|-------|--------|------------|
| A. corpus | *(agent web_search gathering — see Seam 1)* | `cities/<slug>.json` + agent `web_search` | `<slug>-corpus.json` | none |
| B. reviews | `python3 scripts/reviews.py --city <city> --corpus <slug>-corpus.json` | `<slug>-corpus.json` | `<slug>-reviews.json` | `GOOGLE_MAPS_API_KEY` (optional; absent → channel skipped) |
| C. engine map | *(agent discovery — see Seam 2)* | `<slug>-corpus.json` + agent engine discovery | `<slug>-venues.json` | none |
| C'. booking | `python3 scripts/booking.py --city <city> --venues <slug>-venues.json` | `<slug>-venues.json` + live HTTP | `<slug>-booking.json` | none (HTTP-only) |
| D. model | `/tmp/ranker-venv/bin/python scripts/model.py --city <city> --corpus <slug>-corpus.json --reviews <slug>-reviews.json --booking <slug>-booking.json` | all three JSONs | `<slug>-results.json`, `<slug>-posterior.nc` | uv 3.12 venv (pymc/arviz/numpy/h5netcdf) |
| E. render | `python3 scripts/render.py --city <city> --results <slug>-results.json` | `<slug>-results.json` | `<slug>-board.md`, `<slug>-results.json` | none |

**Steps B, C', and E use system `python3`.** Step D REQUIRES the uv 3.12 venv (see Venv Setup below).

---

## DATA-FLOW JOIN KEY

Every record in the pipeline is keyed by `slug` — the URL-safe lowercase identifier produced by
`corpus.py:_venue_slug`. `model.prepare_model_data` joins `<slug>-corpus.json`,
`<slug>-reviews.json`, and `<slug>-booking.json` on the `slug` field via `_index_by_slug`.

**Load-bearing warning:** the `<slug>-venues.json` keys authored in Seam 2 MUST use the corpus
`slug` (the `slug` field from each record in `<slug>-corpus.json`), never the display name. A slug
mismatch causes booking records to fail the join silently — every mismatched venue appears as
missing fill in the model, producing wide uncertainty that the data does not actually justify.
Always copy the `slug` value verbatim from the corpus JSON when building the venues map.

---

## SEAM 1 — Corpus gathering (agent fills this gap)

`corpus.py:gather_source()` returns `[]` in the stdlib environment (it prints a stderr NOTE:
"live web_search not available — Override gather_source() in an agent context"). Running
`python3 scripts/corpus.py --city <city>` alone writes an empty corpus. **Do NOT rely on the bare
CLI for venues.**

The agent assembles corpus rows itself via `web_search`, then calls the corpus helper functions
directly:

**Corpus row shape (what the agent builds per venue):**
```python
row = {
    "venue":           str,           # canonical venue name (first-seen)
    "area":            str | None,    # neighbourhood/area, or None
    "cuisine_raw":     str,           # raw editorial cuisine label
    "prestige_sources": [str, ...],   # which source(s) listed this venue
}
```

**Agent procedure:**
1. Load the city config so the cuisine taxonomy is available:
   ```python
   import sys; sys.path.insert(0, "scripts")
   from cityconfig import load_city
   cfg = load_city("<city>")
   ```
2. For each `prestige_sources[].name` in `cities/<slug>.json`, run `web_search` to gather venues.
3. Build one row per venue using the shape above (note: `cuisine_raw`, not `cuisine`).
4. Import and call from `scripts/corpus.py`:
   ```python
   from corpus import dedup, bucket_cuisine, normalize_name, _venue_slug
   deduped = dedup(rows)   # adds prestige_score, sources_n (NOT slug, NOT cuisine — add those explicitly after)
   for v in deduped:
       v["slug"] = _venue_slug(v["venue"])
       v["cuisine"] = bucket_cuisine(v.get("cuisine_raw"), cfg["cuisine_taxonomy"])
   ```
5. Write `deduped` (the list returned by `dedup`, now with `slug` and `cuisine` on every record) to `<slug>-corpus.json`.

**`gather_source()` is left AS-IS and must NOT be implemented.** This is a locked design decision
(A3): the agent fills the seam via `web_search`; the stdlib-safe `gather_source` stub is
intentional. The functions `dedup`, `bucket_cuisine`, `normalize_name`, and `_venue_slug` are
fully implemented and available via import.

---

## SEAM 2 — Venue-to-engine map (agent fills this gap)

No script produces `<slug>-venues.json`. `booking.py --venues` requires it. The agent discovers
each venue's booking engine and engine-specific identifier, then authors the file.

**Venues map shape:**
```json
{
  "helm":        {"engine": "sevenrooms", "identifier": "helmbgc"},
  "toyo-eatery": {"engine": "eatigo",     "identifier": "12345"},
  "suhring":     {"engine": "covermanager", "identifier": "suhring-bkk"}
}
```

- Keys MUST be the corpus `slug` (see Data-Flow Join Key above).
- `engine` must be one of `booking.py`'s `PROBERS` (`sevenrooms`, `eatigo`, `covermanager`) or any
  engine listed in `cities/<slug>.json` under `booking_platforms`.
- For engine discovery method and hard/anti-bot engines (TableCheck, Chope, OpenTable, etc.),
  delegate to the `booking-probe` sibling skill's `references/engine-routing.md`.
- Venues with no online booking engine are simply **omitted** from the map (or mapped to an
  unknown engine). `booking.py` flags them `gated` / `off_platform=True` with `fill=None` — the
  honesty rail (BOOK-03). Never fabricate a fill value.

---

## VENV SETUP (run once, before Step D)

System `python3` is 3.10 with no scientific stack (`import numpy` fails; `import pymc` fails).
`scripts/model.py` CANNOT run on system python3 — it will raise `ImportError` on numpy/pymc.
All other steps (corpus/reviews/booking/render) use system `python3` and are fine.

**Create the model venv (one-time setup):**
```bash
# Install uv if absent (already present at 0.11.18 on the reference machine)
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }

# Provision the 3.12 venv
uv venv /tmp/ranker-venv --python 3.12

# Install the model stack
uv pip install --python /tmp/ranker-venv/bin/python pymc arviz numpy h5netcdf
```

`h5netcdf` is required so `model.fit()` can save `<slug>-posterior.nc` (engine `h5netcdf`). The
save is wrapped in a best-effort `try/except`, so a missing `h5netcdf` degrades to "no .nc saved"
rather than a crash — but install it so re-render without re-fit works.

**Step D invocation (verbatim):**
```bash
/tmp/ranker-venv/bin/python scripts/model.py \
  --city <city> \
  --corpus <slug>-corpus.json \
  --reviews <slug>-reviews.json \
  --booking <slug>-booking.json
```

Never invoke model.py with `python3`. The venv interpreter path is the only supported way.
