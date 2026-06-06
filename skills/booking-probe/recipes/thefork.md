# TheFork (lafourchette) — ⚠️ DataDome anti-bot-blocked from datacenter IPs (2026-06-03)

Major EU/global reservation aggregator (`thefork.com/restaurant/<slug>-r<id>`). Would be a big
force-multiplier (Cocina Hermanos Torres + many EU venues route here), BUT:

- Plain agent-browser Chrome → empty body (`innerText.length 0`, title stuck "thefork.com").
- Direct curl → **HTTP 403 + captcha** (DataDome).
- **CloakBrowser native stealth → also blank shell** (DataDome silent-blocks: serves a non-hydrated
  shell rather than a visible captcha; `title` never becomes the venue name).

→ TheFork venues resolve **`unresolved` (anti-bot / DataDome)** from a datacenter IP until a
residential IP or a warmed DataDome cookie is available. Do NOT solve the captcha. Same class as
Inline (PerimeterX). CloakBrowser clears Cloudflare (OMAKASE/Pocket Concierge) but NOT DataDome.

## If a venue is on TheFork, look for a mirror first
Top venues usually list on multiple engines — check the venue's own site for a CoverManager/
SevenRooms iframe (often present alongside the TheFork link) before classifying blocked.

## Open
- ⬜ Residential-IP / warmed-cookie pass; then TheFork's availability GraphQL becomes readable.
