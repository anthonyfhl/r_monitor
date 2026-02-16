"""Fetch Interactive Brokers margin borrowing rates via web scraping."""

import logging
import re

import requests
from bs4 import BeautifulSoup

from src.config import REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)

SCRAPE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# IB margin rates page
IB_RATES_URL = "https://www.interactivebrokers.com/en/trading/margin-rates.php"
IB_BENCHMARK_URL = "https://www.interactivebrokers.com/en/trading/margin-benchmarks.php"


def _parse_rate_table(soup: BeautifulSoup, currency: str) -> dict | None:
    """Parse the IB margin rate table for a specific currency.

    Returns the default (first/lowest) tier rate.
    """
    # Look for tables or sections mentioning the currency
    tables = soup.find_all("table")
    for table in tables:
        header_text = ""
        # Check preceding headers
        prev = table.find_previous(["h2", "h3", "h4", "th", "caption"])
        if prev:
            header_text = prev.get_text(strip=True)

        table_text = table.get_text()
        if currency not in table_text and currency not in header_text:
            continue

        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            row_text = " ".join(c.get_text(strip=True) for c in cells)
            if currency in row_text:
                # Find percentage values in this row
                pct_matches = re.findall(r"(\d+\.?\d*)\s*%", row_text)
                if pct_matches:
                    # Return the rate (typically the spread or total rate)
                    return {"currency": currency, "rate": float(pct_matches[-1])}
    return None


def fetch_ib_margin_rates() -> dict:
    """Fetch IB margin rates for HKD and USD.

    Returns dict like:
        {"HKD": {"benchmark": "HKD HIBOR", "rate": 4.83},
         "USD": {"benchmark": "Fed Funds", "rate": 6.83}}
    """
    result = {"HKD": None, "USD": None}

    try:
        resp = requests.get(IB_RATES_URL, headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Try to find rates in the page
        full_text = soup.get_text()

        # Look for HKD rate
        hkd_match = re.search(
            r"HKD[^%]*?(\d+\.?\d*)\s*%",
            full_text,
            re.IGNORECASE,
        )
        if hkd_match:
            result["HKD"] = {"currency": "HKD", "rate": float(hkd_match.group(1))}

        # Look for USD rate
        usd_match = re.search(
            r"USD[^%]*?(\d+\.?\d*)\s*%",
            full_text,
            re.IGNORECASE,
        )
        if usd_match:
            result["USD"] = {"currency": "USD", "rate": float(usd_match.group(1))}

        # Also try structured table parsing
        for currency in ["HKD", "USD"]:
            if result[currency] is None:
                parsed = _parse_rate_table(soup, currency)
                if parsed:
                    result[currency] = parsed

    except Exception as e:
        logger.error(f"Failed to fetch IB margin rates: {e}")

    # Try benchmark page as fallback/supplement
    try:
        resp2 = requests.get(IB_BENCHMARK_URL, headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp2.raise_for_status()
        soup2 = BeautifulSoup(resp2.text, "lxml")
        text2 = soup2.get_text()

        # Extract benchmark rates
        for currency in ["HKD", "USD"]:
            bm_match = re.search(
                rf"{currency}\s+.*?BM\s*[:=]?\s*(\d+\.?\d*)\s*%",
                text2,
                re.IGNORECASE,
            )
            if bm_match and result.get(currency):
                result[currency]["benchmark_rate"] = float(bm_match.group(1))
    except Exception as e:
        logger.debug(f"Could not fetch IB benchmark rates: {e}")

    return result
