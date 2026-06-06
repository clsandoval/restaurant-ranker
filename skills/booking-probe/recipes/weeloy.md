# Weeloy — ⚠️ consumer booking portal DEFUNCT (verified 2026-06-03)

**Do not classify Weeloy-routed venues from this platform.** As of 2026-06-03 the consumer portal
is dead for booking purposes; venues that historically delegated to Weeloy must be re-routed to
their CURRENT engine via their own website (engine-routing.md detection method).

## What was verified

- `restaurants.weeloy.com` Angular SPA boots (after un-stalling the parser, see below) but the
  router **client-redirects every restaurant deep link to a Singapore food-ordering homepage**
  ("Order Your Favourite Restaurant Dishes Online", takeaway/delivery CTAs). Tried:
  `/restaurant/bangkok/mia-restaurant`, `.../booknow`, `/restaurant/<slug>`,
  `/booking/<CODE>` — all 200 (SPA shell) → all render the homepage. No booking widget reachable.
- `www.weeloy.com` 302s to `weeloy_io/home` — a **B2B restaurant-management SaaS** site. The
  consumer marketplace is gone (company pivot).
- The data API still answers plain curl with the full booking model:
  `GET https://restaurants.weeloy.com/api/restaurantfullinfo/<CODE>` (CODE like
  `TH_BK_R_MiaRestaurant`, derivable as `TH_BK_R_` + PascalCase(slug)) → `is_bookable: "1"`,
  per-weekday `openhours`, tz. **This is STALE/orphaned** — `is_bookable` cannot be trusted when
  no public widget exists to honor it.

## Classification rule

A venue whose only known engine is Weeloy → `unresolved` with note
`"weeloy consumer portal defunct (2026-06-03) — re-route via venue's own site"`. Never emit
`available` from `openhours` alone: capacity was only ever checked at Weeloy's confirm step, and
now there's no widget at all.

## Lesson recorded (transfers to all platforms)

**An engine can die while its JSON API keeps answering.** API liveness ≠ bookability. The widget
(or its live per-date XHR) is the source of truth; a static "bookable" flag from an orphaned API
is not a datapoint.

## Parser-stall fix (transfers to any site with dead third-party scripts)

The SPA shell hangs in `readyState: "loading"` forever because of **parser-blocking `<script>`
tags pointing at dead hosts** — here `trustlogo.comodo.com` (Comodo trustlogo, connection hangs)
and `stackpath.bootstrapcdn.com` (StackPath CDN shut down). Symptoms: body empty, resource-timing
shows later bundles *fetched* (preloader) but never *executed*, `document.scripts`' LAST entry is
the dead script. Fix: blackhole the dead hosts in `/etc/hosts` (`127.0.0.1 trustlogo.comodo.com`)
and **fully restart the browser** (`close` + `pkill -f agent-browser-chrome`) — connection-refused
fails fast and the parser proceeds. Diagnose with: last entry of `document.scripts` + tiny
`document.documentElement.outerHTML.length` (parse truncated at the dead tag).

## Cases handled (ledger)

- ✅ MIA Restaurant + ENOTECA (Bangkok): fullinfo API live (`is_bookable:1`, openhours) but NO
  reachable widget → defunct verdict, `unresolved` rule above.
- ✅ trustlogo.comodo.com + stackpath.bootstrapcdn.com parser stalls → /etc/hosts blackhole fix.
- ✅ Router redirect-to-homepage as the delisted signal (all paths 200 — HTTP code useless).

## Re-check trigger

If a future Bangkok venue's own site actively embeds/links a working Weeloy widget, reopen this
recipe and re-verify — until then the platform stays out of the routing table.
