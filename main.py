"""r_monitor - Daily Interest Rate Monitor

Entry point that orchestrates: fetch → store → report → send
"""

import logging
import sys
from datetime import datetime

from src.config import DATA_DIR, REPORTS_DIR
from src.fetchers.hkma import (
    fetch_hibor_latest,
    fetch_hkd_forward_rates,
)
from src.fetchers.banks import fetch_all_prime_rates
from src.fetchers.ib_rates import fetch_ib_margin_rates
from src.fetchers.fred import fetch_fed_funds_rate
from src.fetchers.treasury import fetch_treasury_yields
from src.fetchers.ny_fed import fetch_sofr_latest
from src.fetchers.fedwatch import fetch_fedwatch_probabilities
from src.fetchers.dbs_esaver import fetch_esaver_current
from src.storage import append_row, append_rows
from src.report import generate_report
from src.telegram_sender import send_message, send_document, build_summary
from src.health import record_fetch_result, get_alerts, check_staleness

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def fetch_all() -> dict:
    """Fetch all rates from all sources. Gracefully handles per-source failures."""
    data = {}

    # --- HKD Rates ---
    logger.info("Fetching HIBOR...")
    try:
        data["hibor"] = fetch_hibor_latest()
        logger.info(f"HIBOR: {data['hibor']}")
        record_fetch_result("hibor", True)
    except Exception as e:
        logger.error(f"HIBOR fetch failed: {e}")
        data["hibor"] = {}
        record_fetch_result("hibor", False)

    logger.info("Fetching bank Prime Rates...")
    try:
        data["prime_rates"] = fetch_all_prime_rates()
        logger.info(f"Prime Rates: {data['prime_rates']}")
        record_fetch_result("prime_rates", True)
    except Exception as e:
        logger.error(f"Prime Rates fetch failed: {e}")
        data["prime_rates"] = []
        record_fetch_result("prime_rates", False)

    logger.info("Fetching IB Margin Rates...")
    try:
        data["ib_rates"] = fetch_ib_margin_rates()
        logger.info(f"IB Rates: {data['ib_rates']}")
        record_fetch_result("ib_rates", True)
    except Exception as e:
        logger.error(f"IB Rates fetch failed: {e}")
        data["ib_rates"] = {}
        record_fetch_result("ib_rates", False)

    # --- USD Rates ---
    logger.info("Fetching Fed Funds Rate...")
    try:
        data["fed_funds"] = fetch_fed_funds_rate()
        logger.info(f"Fed Funds: {data['fed_funds']}")
        record_fetch_result("fed_funds", True)
    except Exception as e:
        logger.error(f"Fed Funds fetch failed: {e}")
        data["fed_funds"] = {}
        record_fetch_result("fed_funds", False)

    logger.info("Fetching SOFR...")
    try:
        data["sofr"] = fetch_sofr_latest()
        logger.info(f"SOFR: {data['sofr']}")
        record_fetch_result("sofr", True)
    except Exception as e:
        logger.error(f"SOFR fetch failed: {e}")
        data["sofr"] = {}
        record_fetch_result("sofr", False)

    logger.info("Fetching Treasury Yields...")
    try:
        data["treasury"] = fetch_treasury_yields()
        logger.info(f"Treasury: {len(data['treasury'])} maturities")
        record_fetch_result("treasury", True)
    except Exception as e:
        logger.error(f"Treasury fetch failed: {e}")
        data["treasury"] = {}
        record_fetch_result("treasury", False)

    # --- Forecasts ---
    logger.info("Fetching FedWatch Probabilities...")
    try:
        data["fedwatch"] = fetch_fedwatch_probabilities()
        logger.info(f"FedWatch: {len(data['fedwatch'])} meetings")
        record_fetch_result("fedwatch", True)
    except Exception as e:
        logger.error(f"FedWatch fetch failed: {e}")
        data["fedwatch"] = []
        record_fetch_result("fedwatch", False)

    logger.info("Fetching HKD Forward Rates...")
    try:
        data["hkd_forwards"] = fetch_hkd_forward_rates()
        logger.info(f"HKD Forwards: {len(data['hkd_forwards'])} tenors")
        record_fetch_result("hkd_forwards", True)
    except Exception as e:
        logger.error(f"HKD Forwards fetch failed: {e}")
        data["hkd_forwards"] = []
        record_fetch_result("hkd_forwards", False)

    logger.info("Fetching DBS eSaver Promotion...")
    try:
        data["esaver"] = fetch_esaver_current()
        logger.info(f"DBS eSaver: {data['esaver']}")
        record_fetch_result("esaver", True)
    except Exception as e:
        logger.error(f"DBS eSaver fetch failed: {e}")
        data["esaver"] = {}
        record_fetch_result("esaver", False)

    return data


def store_data(data: dict) -> None:
    """Store fetched data to CSV files for historical tracking."""
    today = datetime.now().strftime("%Y-%m-%d")

    # HIBOR
    hibor = data.get("hibor", {})
    if hibor:
        row = {"date": hibor.get("date", today)}
        row.update({k: v for k, v in hibor.items() if k != "date"})
        append_row("hibor_daily", row)

    # Prime Rates
    prime_rates = data.get("prime_rates", [])
    if prime_rates:
        row = {"date": today}
        for pr in prime_rates:
            if pr.get("rate") is not None:
                row[pr["bank"]] = pr["rate"]
        if len(row) > 1:
            append_row("prime_rates", row)

    # IB Rates
    ib = data.get("ib_rates", {})
    ib_row = {"date": today}
    if ib.get("HKD") and ib["HKD"].get("rate") is not None:
        ib_row["hkd_rate"] = ib["HKD"]["rate"]
    if ib.get("USD") and ib["USD"].get("rate") is not None:
        ib_row["usd_rate"] = ib["USD"]["rate"]
    if len(ib_row) > 1:
        append_row("ib_rates", ib_row)

    # Fed Funds
    fed = data.get("fed_funds", {})
    if fed.get("effective") is not None:
        append_row("fed_rates", {
            "date": fed.get("date", today),
            "rate": fed["effective"],
            "target_upper": fed.get("target_upper"),
            "target_lower": fed.get("target_lower"),
        })

    # SOFR
    sofr = data.get("sofr", {})
    if sofr.get("rate") is not None:
        append_row("sofr", {"date": sofr.get("date", today), "rate": sofr["rate"]})

    # Treasury Yields
    treasury = data.get("treasury", {})
    if treasury and treasury.get("date"):
        row = {k: v for k, v in treasury.items()}
        append_row("treasury_yields", row)

    # DBS eSaver - upsert by promo_month
    esaver = data.get("esaver", {})
    if esaver.get("promo_month"):
        _upsert_esaver(esaver)


def _upsert_esaver(esaver: dict) -> None:
    """Update or insert an eSaver promotion row by promo_month."""
    from src.storage import load_csv, save_csv
    import pandas as pd

    df = load_csv("esaver_history")
    month = esaver["promo_month"]

    if not df.empty and "promo_month" in df.columns:
        mask = df["promo_month"].astype(str) == str(month)
        if mask.any():
            # Update existing row with any new non-None values
            idx = df[mask].index[0]
            for k, v in esaver.items():
                if v is not None and k in df.columns:
                    df.at[idx, k] = v
            save_csv("esaver_history", df)
            logger.info(f"Updated eSaver row for {month}")
            return

    # Append new row
    new_row = pd.DataFrame([esaver])
    df = pd.concat([df, new_row], ignore_index=True)
    df = df.sort_values("promo_month").reset_index(drop=True)
    save_csv("esaver_history", df)
    logger.info(f"Added new eSaver row for {month}")


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("r_monitor - Interest Rate Monitor")
    logger.info(f"Run time: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    # 1. Fetch all data
    logger.info("Step 1: Fetching rates from all sources...")
    data = fetch_all()

    # 1b. Check for persistent fetch failures
    alerts = get_alerts(threshold=3)
    if alerts:
        alert_msg = "\u26a0\ufe0f <b>Fetch Alert</b>\n\nThe following sources have failed 3+ consecutive days:\n"
        for src in alerts:
            alert_msg += f"  \u2022 {src}\n"
        logger.warning(f"Fetch alerts: {alerts}")
        send_message(alert_msg)

    # 1c. Check for stale data
    stale = check_staleness(threshold_days=3)
    if stale:
        stale_msg = "\u26a0\ufe0f <b>Stale Data Warning</b>\n\n"
        for name, last_date, gap in stale:
            stale_msg += f"  \u2022 {name}: last update {last_date} ({gap}d ago)\n"
        logger.warning(f"Stale data: {stale}")
        send_message(stale_msg)

    # 2. Store to CSV
    logger.info("Step 2: Storing data to CSV...")
    store_data(data)

    # 3. Generate HTML report & send (weekly only — default Sunday)
    now = datetime.now()
    weekly = "--weekly" in sys.argv or now.weekday() == 6  # Sunday
    if weekly:
        logger.info("Step 3: Generating HTML report (weekly)...")
        html = generate_report(data)

        report_path = REPORTS_DIR / f"{now.strftime('%Y-%m-%d')}.html"
        report_path.write_text(html, encoding="utf-8")
        logger.info(f"Report saved to {report_path}")

        # 4. Send via Telegram
        logger.info("Step 4: Sending via Telegram...")
        summary = build_summary(data)
        msg_ok = send_message(summary)
        doc_ok = send_document(report_path, caption="Interest Rate Monitor Report")
        ok = msg_ok and doc_ok
        if ok:
            logger.info("Telegram report sent successfully!")
        else:
            logger.warning("Telegram send had issues — check logs above")
    else:
        logger.info("Step 3: Skipping report (not weekly run day). Use --weekly to force.")

    logger.info("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
