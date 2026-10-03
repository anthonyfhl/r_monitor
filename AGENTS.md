# Interest-rate monitor

- `\r_monitor_daily` is the only bank-data writer (12:00 Hong Kong time). The GitHub Actions schedule is retired; never enable a second writer.
- Family saves run synchronously through the authenticated hub and `save_registration.py`. No family-sync scheduled task. The short registration lock is independent of the daily bank lock; acknowledge only a verified commit. Repeated request tokens are idempotent.
- Every outbound request goes through `src/http_client.py`; refusal cooldowns and call caps apply to collection, Telegram, and repair probes. Never clear them to get a green result.
- Use each bank's own rate. The operator's HSBC Wealth Portfolio Lending spread is 1-month Hong Kong Interbank Offered Rate plus 0.5 percentage points; Hang Seng Asset Link is Hang Seng prime minus 1.75 percentage points. Definitions and notifications live in `src/loans.py`.
- Existing-customer DBS eSaver only. Discover published page data; never guess monthly PDF URLs or accept incomplete dates/rates. Family state and personal loan history are local, gitignored and included in the machine backup.
- Telegram sends text for changes/new promotions and repair outcomes. HTML attachment delivery is retired.
- Telegram links display only a clickable 🔗 emoji; keep the URL in the HTML anchor and disable previews.
- IB borrowing uses published IBKR Pro HKD/USD tiers from `src/fetchers/ib_rates.py`; validate complete contiguous coverage, notify all tier changes via `src/ib_margin.py`. The calculator must use portions of the balance and disclose special large-loan terms.
- Dah Sing saves use the same authenticated hub handler with an independent record lock. Each month binds one immutable terms revision; overlapping offers never stack. Sundays/Hong Kong public holidays use the preceding nonholiday balance, including across months; ordinary Saturdays count. Missing balance/calendar/rate data stays visible. Historical sources and setup: `README.md`.
- Web assets are in `web/`, published to `reports/app/` behind the existing hub owner login. Do not add another server or weaken authentication.
- Validate with `python -m pytest tests -q --basetemp logs/pytest-r-monitor` and `node --test tests/test_web_guard.cjs tests/test_margin.cjs tests/test_registration_save.cjs tests/test_dsb.cjs`; `python main.py --build-only` makes no outbound calls. Import scripts treat workbook content as data.
