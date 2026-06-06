# Engine routing — direct sites → known engine

Most restaurants that book on their "own website" actually **embed or redirect to a known
engine**. Resolve the engine, then run that engine's recipe. Only genuinely bespoke forms or
phone/LINE-only venues fall outside the recipe library.

## Detection method (per venue)

1. WebSearch `"<name> <city> reservation booking"`; open the official site.
2. Find the "Reserve / Book a table" button; follow it; read the **final** host:
   - `sevenrooms.com/reservations/<slug>` → **sevenrooms**
   - `*.tablecheck.com/.../reserve` → **tablecheck**
   - `book*.chope.co/booking?rid=<id>` → **chope**
   - `covermanager.com/reservation/...` → **covermanager**
   - `*.hungryhub.com` → **hungryhub** · `eatigo.com/.../branches/<id>` → **eatigo**
   - `restaurants.weeloy.com/...` → **weeloy** · `inline.app/booking/...` → **inline**
   - `opentable.com/r/<slug>` → **opentable** · `resy.com/cities/.../<slug>` → **resy**
   - `exploretock.com/<slug>` → **tock**
   - `omakase.in/<lang>/r/<rid>` → **omakase** (Tokyo high-end; Cloudflare + login-gated, usually `gated`)
   - `pocket-concierge.jp/<lang>/restaurants/<id>` → **pocket-concierge** (Japan fine-dining; day-level, waitlist venues read `full`)
   - own custom form (email/inquiry) → **own-widget** (often not live-bookable). A common
     recognizable class: the WordPress **"Five Star / Restaurant Reservations" (themeisle)** plugin
     — `rtb-`-prefixed form, a **"Request Booking"** submit, `rtb_pickadate` config. It has NO live
     inventory (free-text date, emails a request back) → always resolves **`gated`** (El Mercado, Phrom Phong).
   - phone / LINE / IG only → **phone-line-only** (no online inventory — a valid datapoint)
3. Capture the final reservation URL + any deposit / credit-card-hold requirement.

## Mirror-engine rule (rescues login-walled venues)

A venue often lists on **multiple engines** — and one may be readable while another is walled.
**When the official engine is OMAKASE (login-gated → `gated`), check for a readable mirror before
giving up:** the same venue is frequently on **Pocket Concierge** (anonymous calendar) or TABLEALL.
Verified: Narisawa's OMAKASE calendar is login-walled, but its Pocket Concierge listing exposed real
open/full/closed availability. Always prefer the readable mirror; only mark `gated` if no mirror exists.

## Deposit / payment gates (READ-ONLY boundary)

Some venues gate the calendar behind a deposit or CC hold (GOAT 50% hold; Potong 1,000 THB/guest;
Samrub full prepay; Chef's Table, Aksorn no-show fees). **Record the requirement and STOP before
the payment step.** If slots are only visible *after* payment details, mark `gated` with the
deposit noted — do NOT enter card details.

## Bangkok direct-site map (validated 2026-05-30)

21 Michelin/fine-dining venues that came in name-only resolved as: **16 fold into existing
recipes**, 2 need new engines, 3 don't book online.

| Engine | Venues |
|---|---|
| SevenRooms | Côte by Mauro Colagreco, Aksorn, Blue by Alain Ducasse, Inddee, Sühring |
| TableCheck | Gaa, Coda, GOAT, Wana Yook, Nawa, Samrub Samrub Thai |
| Chope | Resonance, Avant, Gen (Sukhumvit 63), Potong |
| Hungry Hub | Maison Dunand |
| OpenTable (new) | Chef's Table by Vincent Thierry |
| Tablein (new) | Baan Tepa |
| phone/walk-in | Jay Fai |
| email form | Chim by Siam Wisdom |
| eRestaurants (niche) | Akkee |

Takeaway for any city: build the big-engine recipes first (they absorb most direct sites too),
then add long-tail engines as specific venues demand them.
