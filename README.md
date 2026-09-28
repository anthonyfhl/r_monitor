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

## Where it runs (since 2026-09-28)

**The local Windows task `\r_monitor_daily` (12:00 HKT daily) is the only writer of
`data/*.csv` and the only sender of the Telegram report** (weekly, Sundays). After
`main.py` it commits the day's data (`run_daily.bat`, local-only / gitignored), and the
machine-wide hourly git sync (MachineWatchDog `git_sync.py`, task `\MachineGitSync`)
pushes it — so GitHub keeps the data archive.

Why: until 2026-09-28 the GitHub Actions workflow below ALSO wrote the same CSVs and
committed them, while the local task wrote them without committing — two writers, so the
local checkout sat 211 commits behind. The Action had no Telegram secrets (it never sent a
report) and its FRED fetch had stopped at 2026-02-27. The two histories were merged once
by date (commit `e9e4abe`).

## GitHub Actions (schedule disabled)

`daily_report.yml` is **disabled** (`gh workflow disable`). To run it in the cloud again —
e.g. if this machine is retired — first stop the local task, set the secrets below, then
`gh workflow enable "Daily Interest Rate Report" -R anthonyfhl/r_monitor`. Never run both:
they write the same files.

Secrets it needs:
- `FRED_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

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
