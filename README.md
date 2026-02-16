# r_monitor

Daily automated tracker for HKD and USD interest rates. Generates an HTML report and sends it via Telegram.

## Rates Tracked

### HKD Rates
- **HIBOR** (O/N, 1W, 1M, 2M, 3M, 6M, 12M) — HKMA API
- **HKMA Base Rate** — HKMA API
- **Prime Rate** (HSBC, BOC, SCB, Hang Seng) — bank websites
- **IB HKD Margin Rate** — Interactive Brokers

### USD Rates
- **Fed Funds Rate** (effective + target range) — FRED API
- **SOFR** — NY Fed API
- **US Treasury Yields** (1M–30Y) — Treasury.gov
- **IB USD Margin Rate** — Interactive Brokers

### Market Expectations
- **CME FedWatch** — FOMC meeting rate probabilities
- **HKD Forward Rates** — HKMA API

## Setup

1. Clone the repo
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in your keys:
   - `FRED_API_KEY` — free from [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html)
   - `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `TELEGRAM_CHAT_ID` — your chat/group ID
4. Run backfill to load historical data: `python backfill.py`
5. Run daily report: `python main.py`

## GitHub Actions

The workflow runs automatically at **12:00 HKT** (04:00 UTC) on weekdays.

Set these secrets in your GitHub repo settings:
- `FRED_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

You can also trigger manually via the **Actions** tab → **Run workflow**.

## Project Structure

```
├── main.py              # Daily report entry point
├── backfill.py          # One-time historical data download
├── src/
│   ├── config.py        # Configuration & env vars
│   ├── fetchers/        # Data source fetchers
│   │   ├── hkma.py      # HIBOR, Base Rate, Forward Rates
│   │   ├── banks.py     # Bank prime rates (web scraping)
│   │   ├── ib_rates.py  # Interactive Brokers margin rates
│   │   ├── fred.py      # Fed Funds Rate (FRED API)
│   │   ├── treasury.py  # US Treasury yields
│   │   ├── ny_fed.py    # SOFR (NY Fed API)
│   │   └── fedwatch.py  # CME FedWatch probabilities
│   ├── storage.py       # CSV-based historical storage
│   ├── report.py        # HTML report generator
│   └── telegram_sender.py
├── data/                # Historical CSV data (auto-committed)
├── .github/workflows/   # GitHub Actions cron job
└── requirements.txt
```
