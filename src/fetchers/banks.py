"""Fetch Prime Rates from major Hong Kong banks via web scraping.

Verified HTML structures (Feb 2026):
- HSBC: <h2> containing "Hong Kong Dollar Best Lending Rate: X.XX%"
  URL: https://www.hsbc.com.hk/investments/market-information/hk/lending-rate/
- BOC: JavaScript-rendered page, no static HTML (use HKMA proxy)
- SCB: No public prime rate page (removed)
- Hang Seng: div.rwd-showRates-rates after <h2> "HKD Prime rate"
  Note: HKD field is sometimes empty on their site
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

# Correct URLs (verified Feb 2026)
HSBC_PRIME_URL = "https://www.hsbc.com.hk/investments/market-information/hk/lending-rate/"
HANGSENG_PRIME_URL = "https://www.hangseng.com/en-hk/personal/banking/rates/prime-rates/"


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


def fetch_hangseng_prime() -> dict:
    """Fetch Hang Seng Bank HKD Prime Rate.

    Page has sections for HKD, USD, RMB prime rates.
    HTML structure: <h2><span>HKD Prime rate</span></h2>
    followed by <div class="rwd-showRates-rates">X.XX% p.a.</div>

    Note: The HKD field is sometimes empty on their website.
    In that case, we return None rather than picking up USD/RMB rates.
    """
    try:
        resp = requests.get(HANGSENG_PRIME_URL, headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Look for HKD Prime rate section specifically
        for h2 in soup.find_all("h2"):
            h2_text = h2.get_text(strip=True).lower()
            if "hkd" in h2_text and "prime" in h2_text:
                # Find the rate container after this heading
                parent = h2.parent
                if parent:
                    rate_div = parent.find("div", class_="rwd-showRates-rates")
                    if rate_div:
                        rate_text = rate_div.get_text(strip=True)
                        pct = re.search(r"(\d+\.?\d*)\s*%", rate_text)
                        if pct:
                            rate = float(pct.group(1))
                            if 3.0 <= rate <= 10.0:
                                return {"bank": "Hang Seng", "rate": rate}

                # Also try siblings
                next_el = h2.find_next("div", class_="rwd-showRates-rates")
                if next_el:
                    rate_text = next_el.get_text(strip=True)
                    pct = re.search(r"(\d+\.?\d*)\s*%", rate_text)
                    if pct:
                        rate = float(pct.group(1))
                        if 3.0 <= rate <= 10.0:
                            return {"bank": "Hang Seng", "rate": rate}

        # Fallback: broader search for HKD prime in full text
        full_text = soup.get_text()
        match = re.search(r"HKD\s+Prime\s+rate[^%]*?(\d+\.?\d*)\s*%", full_text, re.IGNORECASE)
        if match:
            rate = float(match.group(1))
            if 3.0 <= rate <= 10.0:
                return {"bank": "Hang Seng", "rate": rate}

    except Exception as e:
        logger.error(f"Failed to fetch Hang Seng prime rate: {e}")
    return {"bank": "Hang Seng", "rate": None}


def fetch_all_prime_rates() -> list[dict]:
    """Fetch prime rates from tracked banks.

    Note: BOC (JavaScript-rendered) and SCB (no public page) are excluded.
    """
    fetchers = [fetch_hsbc_prime, fetch_hangseng_prime]
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
