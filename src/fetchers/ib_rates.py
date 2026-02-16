"""Fetch Interactive Brokers margin borrowing rates via web scraping.

Verified HTML structure (Feb 2026):
Table rows look like:
  <tr>
    <td>USD</td>
    <td>0 ≤ 100,000</td>
    <td><span class="text-price">5.140%</span> (BM + <span>1.5%</span>)</td>
    <td><span class="text-price">6.140%</span> (BM + <span>2.5%</span>)</td>
  </tr>

We want the FIRST percentage in the IBKR Pro column (3rd cell) = total rate.
NOT the BM spread which appears later.
"""

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

IB_RATES_URL = "https://www.interactivebrokers.com/en/trading/margin-rates.php"


def _extract_rate_from_cell(cell) -> float | None:
    """Extract the total rate (first percentage) from an IB rate cell.

    Cell format: "5.140%(BM +1.5%)" or "<span class='text-price'>5.140%</span> (BM +...)"
    We want 5.140, NOT 1.5.
    """
    # Try text-price span first (most reliable)
    price_span = cell.find("span", class_="text-price")
    if price_span:
        match = re.search(r"(\d+\.?\d*)\s*%", price_span.get_text(strip=True))
        if match:
            return float(match.group(1))

    # Fallback: first percentage in the cell text
    cell_text = cell.get_text(strip=True)
    match = re.search(r"(\d+\.?\d*)\s*%", cell_text)
    if match:
        return float(match.group(1))

    return None


def fetch_ib_margin_rates() -> dict:
    """Fetch IB margin rates for HKD and USD (IBKR Pro, lowest tier).

    Returns dict like:
        {"HKD": {"currency": "HKD", "rate": 4.25},
         "USD": {"currency": "USD", "rate": 5.14}}
    """
    result = {"HKD": None, "USD": None}

    try:
        resp = requests.get(IB_RATES_URL, headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Find the margin rates table
        # It has headers: Currency, Tier, Rate Charged: IBKR Pro, Rate Charged: IBKR Lite
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            # Check this is the right table
            if not any("currency" in h for h in headers):
                continue
            if not any("rate" in h or "pro" in h.lower() for h in headers):
                continue

            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue

                currency_text = cells[0].get_text(strip=True)

                for target_ccy in ["USD", "HKD"]:
                    if currency_text == target_ccy and result[target_ccy] is None:
                        # cells[2] = IBKR Pro rate (total rate)
                        rate = _extract_rate_from_cell(cells[2])
                        if rate and 0.5 < rate < 20.0:
                            result[target_ccy] = {"currency": target_ccy, "rate": rate}
                            logger.info(f"IB {target_ccy} margin rate: {rate}%")

            # Found the right table, stop searching
            if result["USD"] is not None or result["HKD"] is not None:
                break

    except Exception as e:
        logger.error(f"Failed to fetch IB margin rates: {e}")

    return result
