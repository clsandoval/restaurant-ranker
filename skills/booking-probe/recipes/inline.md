# Inline (inline.app) — ⚠️ anti-bot-blocked from datacenter IPs (verified 2026-06-03)

Taiwan-origin reservation engine (also Bangkok, HK). Firebase-backed widget at
`inline.app/booking/<companyId>:<env>/<branchId>?language=en`. **Behind PerimeterX with a
behavioral "Press & Hold" CAPTCHA that fires on first load from datacenter IPs** — neither plain
agent-browser Chrome nor CloakBrowser stealth (native `launch()` + `humanizeBrowser`) cleared it
in this environment. Resolve such venues `unresolved` with the PerimeterX blocker noted until a
session is run from a residential IP or with a pre-warmed `_px*` cookie. **Do NOT automate the
press-and-hold gesture** — that's defeating a human-verification CAPTCHA (out of scope, same line
we hold for OMAKASE login).

## What was verified (L'Atelier de Joël Robuchon Taipei, `-MWTh4C8p24ICmxRZ3Re:inline-live-2`)

- `GET /api/booking-capacitiesV3?companyId=<cid>&branchId=<bid>` → **HTTP 403, `px-captcha`** page
  (not JSON) on plain curl.
- Widget URL via agent-browser Chrome → "Access to this page has been denied / Press & Hold to
  confirm you are a human". Reference ID = PerimeterX.
- Widget URL via **CloakBrowser** native `launch({headless:true})` + `humanizeBrowser` → **same
  Press & Hold wall**. (Cloudflare-grade stealth passes Cloudflare but NOT PerimeterX's behavioral
  challenge from a flagged IP — an important distinction from OMAKASE/TableCheck which CloakBrowser
  DID clear.)

## URL / id structure (for when a read path opens up)

- `inline.app/booking/<companyId>/<branchId>?language=en`; `companyId` carries an env suffix
  (`-LWG..:inline-live-2a466`, `-MWTh..:inline-live-2`), `branchId` is a separate `-L…`/`-M…`/`-N…`
  token. Single-segment legacy `/booking/<companyId>` links are mostly dead 404s — **verify the
  URL live first** (find current links via venue site or `WebSearch "inline.app/booking/-L"`).
- Read endpoint (when reachable): `GET /api/booking-capacitiesV3` → day-level availability with
  min/max party. **Party-relevant** via those bounds. Firebase-fronted; the old API-capture adapter
  (`booking-probe/platforms/inline.py`) documents the JSON shape.

## CloakBrowser setup notes (reusable — first run on a fresh box)

- `npm i cloakbrowser` ships a downloader, not the binary: `require('cloakbrowser').ensureBinary()`
  fetches stealth Chromium (~v146) to `~/.cloakbrowser/`. Native `launch()` needs **`playwright-core`
  installed as a peer dep** (`npm i playwright-core`) or it throws `ERR_MODULE_NOT_FOUND` for
  `playwright-core` from `dist/playwright.js`.
- **CDP-attach loses the stealth** — `buildLaunchOptions()` returns no special chrome args; the
  stealth is injected at the playwright context level by `launch()`/`humanizeBrowser`. So
  `chrome --remote-debugging-port` + `agent-browser connect` runs UNCLOAKED. For real stealth, drive
  via `cb.launch()` in node directly (see `/tmp/cbtest/probe.js` pattern), not over CDP.

## Cases handled (ledger)

- ✅ Robuchon Taipei: PerimeterX Press & Hold on plain Chrome AND CloakBrowser → `unresolved`
  (anti-bot), honest non-bypass.
- ✅ capacities API 403 `px-captcha` on direct curl.
- ✅ CloakBrowser-native-vs-CDP stealth distinction documented.

## Open / unverified cases (need a residential IP or warmed session)

- ⬜ Whether a residential-IP session sees the widget directly (no press-and-hold) → then the normal
  read loop + `booking-capacitiesV3` applies.
- ⬜ Day-level availability + min/max party read on a live, unblocked Inline venue.
- ⬜ Bangkok Inline venues specifically (verification venue was Taipei).
