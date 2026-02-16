"""One-time historical data backfill script.

Downloads available historical data from free APIs and stores to CSV.
Run this once when setting up the project.
"""

import logging
import sys
from datetime import datetime

from src.fetchers.hkma import fetch_hibor_history, fetch_hkma_base_rate_history
from src.fetchers.fred import fetch_fed_funds_history, fetch_fed_target_history
from src.fetchers.ny_fed import fetch_sofr_history
from src.fetchers.treasury import fetch_treasury_history
from src.storage import append_rows, save_csv, load_csv

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def backfill_hibor(days: int = 730):
    """Backfill HIBOR history (default 2 years)."""
    logger.info(f"Backfilling HIBOR history ({days} days)...")
    try:
        records = fetch_hibor_history(days=days)
        if records:
            append_rows("hibor_daily", records)
            logger.info(f"HIBOR: {len(records)} records fetched")
        else:
            logger.warning("No HIBOR history returned")
    except Exception as e:
        logger.error(f"HIBOR backfill failed: {e}")


def backfill_hkma_base_rate():
    """Backfill full HKMA Base Rate history."""
    logger.info("Backfilling HKMA Base Rate history...")
    try:
        records = fetch_hkma_base_rate_history()
        if records:
            append_rows("hkma_base_rate", records)
            logger.info(f"HKMA Base Rate: {len(records)} records fetched")
        else:
            logger.warning("No HKMA Base Rate history returned")
    except Exception as e:
        logger.error(f"HKMA Base Rate backfill failed: {e}")


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

    backfill_hibor()
    backfill_hkma_base_rate()
    backfill_fed_funds()
    backfill_sofr()
    backfill_treasury()

    logger.info("=" * 60)
    logger.info("Backfill complete!")

    # Print summary
    for name in ["hibor_daily", "hkma_base_rate", "fed_rates", "sofr", "treasury_yields"]:
        df = load_csv(name)
        if not df.empty:
            logger.info(f"  {name}: {len(df)} rows, date range: {df['date'].min()} to {df['date'].max()}")
        else:
            logger.info(f"  {name}: empty")


if __name__ == "__main__":
    sys.exit(main())
