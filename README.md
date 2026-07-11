# Flight watcher

Self-hosted flight-deal alerting, free to run. Watches routes you configure and
sends Telegram alerts from four signals, in priority order:

1. **📉 Price anomalies (primary, pre-publication)** — polls Google Flights on a
   schedule, builds its own price history per route, and alerts when a fare is
   ≥30% below the rolling median (or under a per-route price cap). This is the
   channel that can catch an error fare before deal sites publish it.
2. **🗣 FlyerTalk chatter (all routes)** — watches the Mileage Run Deals and
   Premium Fare Deals forum RSS. Every new thread is decoded by Claude
   (`claude-haiku-4-5`, pennies/month) into structured data — routes, cabin,
   price, error fare vs fuel dump vs mileage run — and alerted, worldwide.
   Threads touching your watched routes get a ⭐. Without an Anthropic key it
   falls back to keyword matching.
3. **⛽ Fuel-dump (3X) probes** — you maintain candidate strike segments (from
   FlyerTalk threads); the scanner prices each watched return with vs without
   the strike appended as a multi-city itinerary and alerts when the total
   drops. Off by default until you add strikes.
4. **📰 Public deal feeds (late signal)** — Secret Flying / Fly4Free RSS matched
   to your routes, tagged `[public]` because everyone already knows.

Everything runs on GitHub: Actions cron does the scanning and commits price
history back to the repo; GitHub Pages serves the dashboard/config site. No
servers, no database.

## Setup (~15 minutes, once)

### 1. Create the GitHub repo

Push this directory to a **public** repo named `flight-watcher` (public =
free unlimited Actions minutes + free Pages; only routes and prices are
visible, never your keys). Private works too but Pages then needs GitHub Pro.

```sh
gh repo create flight-watcher --public --source . --push
```

### 2. Telegram bot

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → pick a name →
   copy the **bot token**.
2. Message your new bot anything (this opens the chat).
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy
   `message.chat.id` — that's your **chat id**.

### 3. Anthropic API key (optional but recommended)

1. Go to [console.anthropic.com](https://console.anthropic.com) → sign up.
2. Billing → add a payment method, load ~$5 prepaid (lasts months here).
3. API Keys → Create Key → name it `flight-watcher` → copy the `sk-ant-…`
   value (shown once). Skip this step to run keyword-matching only.

### 4. Actions secrets

Repo → Settings → Secrets and variables → Actions → *New repository secret*:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | from step 2 |
| `TELEGRAM_CHAT_ID` | from step 2 |
| `ANTHROPIC_API_KEY` | from step 3 (optional) |

### 5. Enable Pages + fine-grained token

1. Repo → Settings → Pages → Source: **GitHub Actions**.
2. github.com → Settings → Developer settings → Fine-grained tokens →
   Generate: repository access = only `flight-watcher`; permissions =
   **Contents: read/write** and **Actions: read/write**.
3. Open `https://<username>.github.io/flight-watcher/` → Settings tab →
   paste the token and `username/flight-watcher` → Save connection.
   (The token lives only in that browser's localStorage.)

### 6. First run

Site → **Scan now** (or repo → Actions → scan → Run workflow). You should get
FlyerTalk alerts on the first run; price-anomaly alerts start once ~8
observations of history exist for a route (a few days of scans).

## Using it

- **Add a route**: site → Watches → origin/destination (IATA or metro codes:
  `LON`, `KUL`, `SIN`, `BKK`…), trip types, optional max price, and keywords
  (city/country names) so feed matching works for the new destination.
- **Add a strike**: site → Strikes, when a FlyerTalk thread hints at a fuel
  dump. Enable probing there too. Always re-verify a probe hit manually
  (ITA Matrix / Google Flights) before booking — dumps die fast and
  Google's multi-city pricing is not the final booking price.
- **Tune**: site → Settings for drop threshold, query budget, cooldown.
- Scans run every 6 hours (edit the cron in `.github/workflows/scan.yml`).

## Local development

```sh
python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m scanner --dry-run          # full run, alerts printed
.venv/bin/python -m scanner --dry-run --module flyertalk
.venv/bin/python -m pytest scanner/tests/
.venv/bin/python -m http.server 8901           # then open localhost:8901/site/
```

`--dry-run` prints alerts instead of sending, but still writes history/state
under `data/`.

## Notes and limits

- **Google Flights has no official API** — prices come via the
  [fast-flights](https://github.com/AWeirdDev/flights) protobuf approach, plus
  a consent-cookie bypass and tolerant parser in
  `scanner/sources/google_flights.py`. If Google changes internals, the
  scanner sends a 🚨 health alert (once/day) instead of failing silently.
- Query budget is deliberately small (60/run with jitter) to stay polite from
  GitHub runner IPs. If runs start failing there, run the same scanner from a
  home machine via cron — the code is host-agnostic.
- Fuel-dump *discovery* stays a human job: the FlyerTalk decoder surfaces the
  threads; you feed candidate strikes back into the Strikes tab.
- History files grow slowly (capped); the Actions job commits `data/` back
  after each run, which is the entire persistence layer.
