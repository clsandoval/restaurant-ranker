# City Config Schema

Every city the ranker supports is described by **one JSON file** in this directory:
`cities/<slug>.json`. To add a new city, copy the template below, edit the values,
and save the file. No code change is required — the loader discovers cities by globbing
`*.json`.

---

## Top-level keys

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `city` | string | yes | Human-readable display name (e.g. `"Manila"`, `"Bangkok"`) |
| `slug` | string | yes | Filename stem; lowercase, hyphen-separated, ASCII only (e.g. `"manila"`) |
| `country` | string | yes | Country name used to disambiguate Places API queries (e.g. `"Philippines"`) |
| `prestige_sources` | array | yes | Editorial best-of / award lists that define venue prestige for this city |
| `cuisine_taxonomy` | array | yes | Ordered list of coarse cuisine buckets + substring match tokens |
| `booking_platforms` | object | yes | Booking platform token lists — drives gatedness + fill-rate channels |

---

## `prestige_sources`

Array of objects. Each entry names one editorial source used when building the
prestige corpus (web_search step). The length of this list becomes the prestige
denominator: a venue appearing on K of the N sources gets prestige = K/N.

```json
"prestige_sources": [
  {"name": "Asia's 50 Best Restaurants"},
  {"name": "Michelin Guide Philippines"},
  {"name": "Tatler Asia Best Restaurants"}
]
```

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Exact name used in web_search queries and provenance labels |

---

## `cuisine_taxonomy`

Ordered array of bucket objects. The loader walks the list top-to-bottom and
assigns the **first** bucket whose tokens appear as substrings in the raw cuisine
string (case-insensitive). The final entry — `Modern/Contemporary` — acts as the
fallthrough default (tokens can be empty).

```json
"cuisine_taxonomy": [
  {"bucket": "Japanese",   "tokens": ["japanese", "sushi", "omakase", "kaiseki", "kappo"]},
  {"bucket": "Italian",    "tokens": ["italian"]},
  {"bucket": "French",     "tokens": ["french"]},
  {"bucket": "Spanish",    "tokens": ["spanish", "basque", "mediterranean"]},
  {"bucket": "Steakhouse", "tokens": ["steak"]},
  {"bucket": "Chinese",    "tokens": ["chinese", "cantonese", "dimsum"]},
  {"bucket": "Filipino",   "tokens": ["filipino"]},
  {"bucket": "Modern/Contemporary", "tokens": []}
]
```

| Key | Type | Description |
|-----|------|-------------|
| `bucket` | string | Coarse label used for cuisine pooling in the Bayesian model |
| `tokens` | array of strings | Substring tokens to match against the raw cuisine label (any match → bucket assigned) |

**Rules:**
- Order matters — more specific buckets go first.
- The fallthrough bucket (`Modern/Contemporary` or equivalent) must be last with `tokens: []`.
- Thin buckets with fewer than 4 venues are merged into the fallthrough at model time
  (the model collapses small groups; keep them in config for corpus labelling).

---

## `booking_platforms`

Object with two lists of lowercase substring tokens. The assembler checks each
venue's booking engine string against these lists to classify its data channel.

```json
"booking_platforms": {
  "online_engines": [
    "sevenrooms", "eatigo", "tablecheck", "opentable", "tock",
    "autoreserve", "dishcult", "oddle", "covermanager"
  ],
  "readable_engines": [
    "sevenrooms", "eatigo"
  ]
}
```

### `online_engines`

Tokens that indicate the venue exposes an **online booking calendar** (`g_i = 0`).
Any venue whose engine string contains one of these tokens is treated as online-bookable.
Everything else is gated (`g_i = 1`) — phone/IG/deposit/lottery.

Source: `assemble.py ONLINE_ENGINE_TOKENS` union `gate_ladder.py ONLINE_INVENTORY`
plus `covermanager` (read by `probe100.py`).

### `readable_engines`

Subset of `online_engines` whose booking endpoints can be **read over plain HTTP**
without a browser (JSON endpoints, no anti-bot). These are the venues for which a
live fill-rate observation is possible.

Source: `assemble.py READABLE_ENGINE_TOKENS` (spike 026 validated: SevenRooms +
Eatigo both return slot JSON on Managed Agents with no agent-browser needed).

**Rule:** `readable_engines` must be a subset of `online_engines`. A readable engine
that is not also listed in `online_engines` would be a bug.

---

## Adding a new city — checklist

1. Copy `manila.json` to `cities/<slug>.json` (e.g. `cities/bangkok.json`).
2. Set `city`, `slug`, `country`.
3. Replace `prestige_sources` with the city's relevant editorial lists.
4. Update `cuisine_taxonomy` for local cuisine diversity (add/rename buckets as needed;
   keep the `Modern/Contemporary` fallthrough last).
5. Update `booking_platforms.online_engines` with any booking engines active in that
   market that are not already in the list.
6. Update `booking_platforms.readable_engines` with only the engines whose JSON
   endpoints have been spike-validated for that market.
7. Verify: `python -c "from scripts.cityconfig import load_city; print(load_city('<slug>')['city'])"`.
8. That's it — no code changes needed.

---

## Worked example

See `manila.json` for the full reference implementation: 7 cuisine buckets ported from
`spikes/013-ranker-data-assembly/assemble.py`, prestige sources from `spikes/026` Step 2,
and booking platform tokens reconciled from `assemble.py` + `gate_ladder.py`.
