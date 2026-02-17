"""Fetch Prime Rates from major Hong Kong banks via web scraping.

Verified HTML structures (Feb 2026):
- HSBC: "Hong Kong Dollar Best Lending Rate: 5.00%" in <h2>
  URL: https://www.hsbc.com.hk/investments/market-information/hk/lending-rate/
- DBS: Table with "DBS Prime (% p.a.)" column, rows like ["26-Sep-25", "5.375"]
  URL: https://www.dbs.com.hk/personal/loans/home-loans/home-advice/interestrate.html
- Public Bank: "5.250% p.a." text after "HKD Prime Rate" heading
  URL: https://www.publicbank.com.hk/en/usefultools/rates/hkdprimerates

Removed: BOC (JS-rendered), SCB (no public page), Hang Seng (same as HSBC by definition)
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
PUBLIC_BANK_PRIME_URL = "https://www.publicbank.com.hk/en/usefultools/rates/hkdprimerates"


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


def fetch_public_bank_prime() -> dict:
    """Fetch Public Bank (Hong Kong) HKD Prime Rate.

    Page text: "HKD Prime Rate ... 5.250% p.a."
    Also has history table with "Effective Date | HKD Prime Rate" rows.
    """
    try:
        resp = requests.get(PUBLIC_BANK_PRIME_URL, headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Look for the main rate display: "X.XXX% p.a."
        # Avoid matching time strings like "17:59" by requiring "% p.a."
        full_text = soup.get_text()
        match = re.search(r"(\d+\.\d{2,3})\s*%\s*p\.a\.", full_text, re.IGNORECASE)
        if match:
            rate = float(match.group(1))
            if 3.0 <= rate <= 10.0:
                return {"bank": "Public Bank", "rate": rate}

        # Fallback: look in table rows
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) >= 2:
                    for cell in cells:
                        pct = re.search(r"(\d+\.\d{2,3})\s*%", cell)
                        if pct:
                            rate = float(pct.group(1))
                            if 3.0 <= rate <= 10.0:
                                return {"bank": "Public Bank", "rate": rate}

    except Exception as e:
        logger.error(f"Failed to fetch Public Bank prime rate: {e}")
    return {"bank": "Public Bank", "rate": None}


def fetch_all_prime_rates() -> list[dict]:
    """Fetch prime rates from tracked banks.

    Banks tracked:
    - HSBC (5.00%) — the "big bank" P rate, Hang Seng follows same rate
    - DBS (5.375%) — smaller bank, slightly higher P rate
    - Public Bank (5.250%) — smaller bank

    Not tracked: BOC (JS-rendered), SCB (no public page),
    Hang Seng (same as HSBC by definition), BEA/ICBC/Citi/CCB (JS-rendered)
    """
    fetchers = [fetch_hsbc_prime, fetch_dbs_prime, fetch_public_bank_prime]
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
