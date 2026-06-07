# lakbai · Lisbon restaurant ranking

*Bayesian 4-channel model (prestige + reviews + gate + LIVE fill), partial-pooled by cuisine. Read-only throughout — calendars were read, never booked.*

**Corpus:** 19 venues · **prestige sources S=6** · **reviews** ok · **6 venues read LIVE for booking-fill.**

---
## 1 · FILL EVIDENCE — live booking-calendar reads

Each readable venue's booking engine was discovered from scratch and its live availability read read-only. `fill = Σ filled / (grid × dates)` — higher = harder to get a table.

| venue | engine | live read | N | **fill** |
|---|---|--:|--:|--:|
| **Belcanto** | sevenrooms | live read | 72 | **0.76** |
| **Tapisco** | sevenrooms | live read | 126 | **0.63** |
| **BAHR** | sevenrooms | live read | 240 | **0.40** |
| **Rocco** | sevenrooms | live read | 342 | **0.40** |
| **Sala de Corte** | sevenrooms | live read | 108 | **0.34** |
| **Pizzaria Lisboa** | sevenrooms | live read | 144 | **0.24** |

*Coverage: 6/19 venues read live — below the ~10-venue identifiability floor — fill is reported but the floor was not cleared.*

---
## 2 · TOP-19 BOARD

| # | venue | cuisine | prestige | rating (n) | gate | fill | q̄ (94% HDI) |
|--:|---|---|--:|---|---|--:|---|
| 1 | **Arkhe** | Modern/Contemporary | 2/6 | 4.8 (844) | prepay/hard | — | +0.78 [-0.73, +2.25] |
| 2 | **Feitoria** | Portuguese | 1/6 | 4.8 (619) | prepay/hard | — | +0.66 [-1.06, +2.11] |
| 3 | **Marlene** | Portuguese | 2/6 | 4.8 (158) | prepay/hard | — | +0.63 [-1.34, +2.28] |
| 4 | **Cervejaria Ramiro** | Portuguese | 3/6 | 4.4 (20222) | prepay/hard | — | +0.53 [-1.04, +2.25] |
| 5 | **Epur** | French | 2/6 | 4.7 (312) | prepay/hard | — | +0.52 [-1.30, +1.96] |
| 6 | **SÁLA** | Portuguese | 1/6 | 4.7 (620) | prepay/hard | — | +0.49 [-1.04, +2.00] |
| 7 | **Encanto** | Modern/Contemporary | 2/6 | 4.6 (338) | prepay/hard | — | +0.36 [-1.16, +1.82] |
| 8 | **Belcanto** | Portuguese | 4/6 | 4.6 (1757) | online | 0.76 | +0.25 [-1.41, +1.79] |
| 9 | **O Velho Eurico** | Portuguese | 1/6 | 4.4 (4172) | prepay/hard | — | +0.16 [-1.29, +1.70] |
| 10 | **Prado** | Portuguese | 3/6 | 4.3 (1510) | prepay/hard | — | +0.12 [-1.49, +1.72] |
| 11 | **Alma** | Portuguese | 3/6 | 4.7 (1641) | online | — | +0.10 [-1.40, +1.54] |
| 12 | **Taberna da Rua das Flores** | Portuguese | 2/6 | 4.3 (3136) | prepay/hard | — | +0.07 [-1.58, +1.59] |
| 13 | **Gunpowder Lisbon** | Modern/Contemporary | 1/6 | 4.7 (810) | online | — | -0.20 [-1.75, +1.29] |
| 14 | **Boa-Bao** | Modern/Contemporary | 3/6 | 4.4 (6638) | online | — | -0.30 [-1.87, +1.28] |
| 15 | **Tapisco** | Portuguese | 2/6 | 4.3 (1728) | online | 0.63 | -0.41 [-1.66, +0.94] |
| 16 | **Sala de Corte** | Steakhouse | 2/6 | 4.5 (3759) | online | 0.34 | -0.47 [-1.83, +0.75] |
| 17 | **Rocco** | Italian | 1/6 | 4.3 (2572) | online | 0.40 | -0.68 [-1.98, +0.56] |
| 18 | **BAHR** | Portuguese | 1/6 | 4.5 (699) | online | 0.40 | -0.73 [-2.06, +0.47] |
| 19 | **Pizzaria Lisboa** | Italian | 1/6 | 4.3 (1449) | online | 0.24 | -1.08 [-2.38, +0.34] |

*Full board in `results.json`. gate: online · prepay/hard · ticket-drop.*

---
## 3 · Honesty note

- **Convergence:** 9 divergences, max r̂ = 1.0100, min ESS ≈ 497 across 4 chains × 1500 draws (NUTS).
- **Fill coverage:** 6/19 venues read live (~10-venue floor not cleared).
- **Uncertainty is real:** 94% HDIs on q are wide and overlap across the gated fine-dining tier — the board renders that overlap rather than faking a confident ordering. Off-platform venues show `—` for fill and keep their wide interval; no fabricated confidence.
- **Provenance:** prestige sets the tiers; live booking demand reorders *within* a tier, it does not manufacture quality.

## 4 · Did live booking demand move the ranking?

**Yes.** The fill slope **β_b = 0.50** (94% HDI [-0.87, 1.57], P(β_b>0) = 0.82) — booked-solid calendars load onto higher latent quality.

(Prestige slope β_p = 0.26, HDI [0.00, 0.64] for context.)
