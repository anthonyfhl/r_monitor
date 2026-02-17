"""Fetch Prime Rates from major Hong Kong banks via web scraping.

Hong Kong has two tiers of Prime Rate:
- 細P (Small P / 5.00%): HSBC, BOC(HK), Hang Seng — the big local banks
- 大P (Big P / 5.375%): SCB, BEA, DBS — other major banks

We track one representative bank from each tier:
- HSBC for 細P (5.00%)
- DBS for 大P (5.375%)

Verified HTML structures (Feb 2026):
- HSBC: "Hong Kong Dollar Best Lending Rate: 5.00%" in <h2>
  URL: https://www.hsbc.com.hk/investments/market-information/hk/lending-rate/
- DBS: Table with "DBS Prime (% p.a.)" column, rows like ["26-Sep-25", "5.375"]
  URL: https://www.dbs.com.hk/personal/loans/home-loans/home-advice/interestrate.html
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

# Verified URLs (Feb 2026)
HSBC_PRIME_URL = "https://www.hsbc.com.hk/investments/market-information/hk/lending-rate/"
DBS_PRIME_URL = "https://www.dbs.com.hk/personal/loans/home-loans/home-advice/interestrate.html"


def fetch_hsbc_prime() -> dict:
    """Fetch HSBC HK Best Lending Rate (Prime Rate).

    Page contains: "Hong Kong Dollar Best Lending Rate: 5.00%"
    """
    try:
        resp = requests.get(HSBC_PRIME_URL, headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        text = resp.text

        # Primary: look for "Best Lending Rate: X.XX%"
        match = re.search(
            r"(?:Hong Kong Dollar\s+)?Best Lending Rate[:\s]*(\d+\.?\d*)\s*%",
            text,
            re.IGNORECASE,
        )
        if match:
            rate = float(match.group(1))
            if 3.0 <= rate <= 10.0:
                return {"bank": "HSBC", "rate": rate}

        # Fallback: parse with BeautifulSoup
        soup = BeautifulSoup(text, "lxml")
        for el in soup.find_all(["h1", "h2", "h3", "p", "span", "div"]):
            el_text = el.get_text(strip=True)
            if "best lending rate" in el_text.lower():
                pct = re.search(r"(\d+\.?\d*)\s*%", el_text)
                if pct:
                    rate = float(pct.group(1))
                    if 3.0 <= rate <= 10.0:
                        return {"bank": "HSBC", "rate": rate}

    except Exception as e:
        logger.error(f"Failed to fetch HSBC prime rate: {e}")
    return {"bank": "HSBC", "rate": None}


def fetch_dbs_prime() -> dict:
    """Fetch DBS Hong Kong HKD Prime Rate.

    Page has table: "Last 5 updates of DBS HKD Prime"
    Rows: ["26-Sep-25", "5.375"]
    First data row is the current rate.
    """
    try:
        resp = requests.get(DBS_PRIME_URL, headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for table in soup.find_all("table"):
            table_text = table.get_text().lower()
            if "prime" not in table_text and "dbs" not in table_text:
                continue

            rows = table.find_all("tr")
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) >= 2:
                    # Second cell should be the rate like "5.375"
                    try:
                        rate = float(cells[1])
                        if 3.0 <= rate <= 10.0:
                            return {"bank": "DBS", "rate": rate}
                    except ValueError:
                        continue

    except Exception as e:
        logger.error(f"Failed to fetch DBS prime rate: {e}")
    return {"bank": "DBS", "rate": None}


def fetch_all_prime_rates() -> list[dict]:
    """Fetch prime rates from tracked banks.

    Banks tracked (two tiers of HK Prime Rate):
    - HSBC (5.00%) — 細P (Small P), same as BOC(HK) & Hang Seng
    - DBS (5.375%) — 大P (Big P), same as SCB & BEA
    """
    fetchers = [fetch_hsbc_prime, fetch_dbs_prime]
    results = []
    for fn in fetchers:
        try:
            result = fn()
            results.append(result)
            if result.get("rate") is not None:
                logger.info(f"{result['bank']} prime rate: {result['rate']}%")
            else:
                logger.warning(f"{result['bank']} prime rate: not available")
        except Exception as e:
            logger.error(f"Error in {fn.__name__}: {e}")
    return results
