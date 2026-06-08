# Lisbon cold-city proof — channel coverage report

Per-channel ran-vs-skipped record for the full Lisbon pipeline run (D-03 full keyed run).
Mirrors the `lisbon-board.md` §1/§3 honesty surface. One line per channel.

| Channel | Status |
|---------|--------|
| corpus  | ran — 19 venues deduped from 6 prestige sources |
| reviews | ran — ok (19/19 enriched with Google rating + count) |
| booking | ran — 6/19 readable (live SevenRooms fill); 13/19 off-platform / no-signal |
| gate    | ran — ordinal booking-friction gate derived per venue (online · prepay/hard) |
| model   | ran — 6/19 readable; divergences=9; r̂_max=1.01; min ESS ≈ 497 (4 chains × 1500 draws) |
| render  | ran — board: `lisbon-board.md`; identifiability floor (≥10 readable) NOT cleared (6/19) |

## Notes

- **reviews = ok (NOT skipped):** the run was made with `GOOGLE_MAPS_API_KEY` set, so the board
  carries real Google ratings + review counts (D-03 — the true blog experience, not the degraded path).
- **Live booking signal (bonus):** 6 SevenRooms venues returned real availability —
  Belcanto 0.76, Tapisco 0.63, BAHR 0.40, Rocco 0.40, Sala de Corte 0.34, Pizzaria Lisboa 0.24.
  β_b = +0.50 (94% HDI [-0.87, 1.57], P(β_b>0) = 0.82): booked-solid calendars load onto higher latent quality.
- **Off-platform honesty rail (required):** 13/19 venues render `—` for fill and keep their wide HDI —
  no fabricated confidence. This includes genuine off-platform institutions: **Cervejaria Ramiro**,
  **Taberna da Rua das Flores**, and **O Velho Eurico** (phone/walk-in / no-reservations), plus
  prepay/hard fine-dining (Arkhe, Feitoria, Marlene, Epur, SÁLA, Encanto, Prado) and online venues
  whose calendars returned no readable slots at probe time (Alma, Gunpowder Lisbon, Boa-Bao).
- **Convergence surfaced, not gated (D-06):** 9 divergences / r̂_max 1.01 are reported honestly in
  the board §3; per the phase pass bar these are diagnostics to disclose, not a strict gate.
- **Read-only law (BOOK-04):** booking probes read availability only — no reservation was created,
  confirmed, or cancelled.

## Reproduce

See `REPRODUCE.md` in this directory for the exact end-to-end commands. The city config is the
single source of truth at `cities/lisbon.json` (not duplicated here).
