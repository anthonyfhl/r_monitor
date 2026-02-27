"""One-time historical data backfill script.

Downloads available historical data from free APIs and stores to CSV.
Run this once when setting up the project, or to fill gaps.

Usage:
    python backfill.py              # Backfill all sources (default 2 years)
    python backfill.py --hibor      # Backfill only HIBOR
    python backfill.py --days 1825  # Backfill 5 years
"""

import logging
import sys
import time
from datetime import datetime, timedelta

import requests

from src.fetchers.fred import fetch_fed_funds_history, fetch_fed_target_history
from src.fetchers.ny_fed import fetch_sofr_history
from src.fetchers.treasury import fetch_treasury_history
from src.storage import append_rows, load_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

HKAB_HIBOR_URL = "https://www.hkab.org.hk/api/hibor"
HIBOR_TENORS = {
    "Overnight": "Overnight",
    "1 Month": "1 Month",
    "3 Months": "3 Months",
    "12 Months": "12 Months",
}


def backfill_hibor(days: int = 730):
    """Backfill HIBOR history from HKAB API (single-day queries)."""
    logger.info(f"Backfilling HIBOR history ({days} days) from HKAB...")

    existing = load_csv("hibor_daily")
    existing_dates = set()
    if not existing.empty and "date" in existing.columns:
        existing_dates = set(existing["date"].astype(str).values)

    end = datetime.now()
    start = end - timedelta(days=days)
    records = []
    skipped = 0
    fetched = 0

    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        if date_str in existing_dates:
            skipped += 1
            current += timedelta(days=1)
            continue

        # Skip weekends
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue

        try:
            resp = requests.get(
                HKAB_HIBOR_URL,
                params={"year": current.year, "month": current.month, "day": current.day},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("isHoliday"):
                current += timedelta(days=1)
                continue

            row = {"date": date_str}
            for hkab_key, display_name in HIBOR_TENORS.items():
                val = data.get(hkab_key)
                if val is not None:
                    row[display_name] = float(val)

            if len(row) > 1:
                records.append(row)
                fetched += 1

        except Exception as e:
            logger.warning(f"HKAB {date_str}: {e}")

        current += timedelta(days=1)

        # Rate limit: ~3 req/sec
        if fetched % 3 == 0:
            time.sleep(0.3)

        if fetched % 50 == 0 and fetched > 0:
            logger.info(f"  HIBOR: fetched {fetched} days so far...")

    if records:
        append_rows("hibor_daily", records)
        logger.info(f"HIBOR: {fetched} new records (skipped {skipped} existing)")
    else:
        logger.info(f"HIBOR: no new records needed (skipped {skipped} existing)")


def backfill_fed_funds(days: int = 730):
    """Backfill Fed Funds Effective Rate history."""
    logger.info(f"Backfilling Fed Funds history ({days} days)...")
    try:
        records = fetch_fed_funds_history(days=days)
        if records:
            append_rows("fed_rates", records)
            logger.info(f"Fed Funds: {len(records)} records fetched")
        else:
            logger.warning("No Fed Funds history returned")
    except Exception as e:
        logger.error(f"Fed Funds backfill failed: {e}")


def backfill_sofr(days: int = 730):
    """Backfill SOFR history."""
    logger.info(f"Backfilling SOFR history ({days} days)...")
    try:
        records = fetch_sofr_history(days=days)
        if records:
            append_rows("sofr", records)
            logger.info(f"SOFR: {len(records)} records fetched")
        else:
            logger.warning("No SOFR history returned")
    except Exception as e:
        logger.error(f"SOFR backfill failed: {e}")


def backfill_treasury():
    """Backfill Treasury yields for current and previous year."""
    current_year = datetime.now().year
    for year in [current_year - 1, current_year]:
        logger.info(f"Backfilling Treasury yields for {year}...")
        try:
            records = fetch_treasury_history(year=year)
            if records:
                append_rows("treasury_yields", records)
                logger.info(f"Treasury {year}: {len(records)} records fetched")
            else:
                logger.warning(f"No Treasury data for {year}")
        except Exception as e:
            logger.error(f"Treasury backfill for {year} failed: {e}")


def main():
    logger.info("=" * 60)
    logger.info("r_monitor - Historical Data Backfill")
    logger.info(f"Run time: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    args = sys.argv[1:]
    days = 730
    if "--days" in args:
        idx = args.index("--days")
        days = int(args[idx + 1])

    # Run specific or all
    targets = [a for a in args if a.startswith("--") and a != "--days"]
    run_all = not targets

    if run_all or "--hibor" in targets:
        backfill_hibor(days)
    if run_all or "--fed" in targets:
        backfill_fed_funds(days)
    if run_all or "--sofr" in targets:
        backfill_sofr(days)
    if run_all or "--treasury" in targets:
        backfill_treasury()

    logger.info("=" * 60)
    logger.info("Backfill complete!")

    for name in ["hibor_daily", "fed_rates", "sofr", "treasury_yields", "prime_rates", "ib_rates"]:
        df = load_csv(name)
        if not df.empty:
            logger.info(f"  {name}: {len(df)} rows, {df['date'].min()} to {df['date'].max()}")
        else:
            logger.info(f"  {name}: empty")


if __name__ == "__main__":
    sys.exit(main())
