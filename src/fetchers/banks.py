"""Fetch Prime Rates from major Hong Kong banks via web scraping."""

import logging
import re

import requests
from bs4 import BeautifulSoup

from src.config import BANK_URLS, REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)

SCRAPE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _find_rate_in_text(text: str) -> float | None:
    """Extract a percentage rate from text like '5.00%' or 'P = 5.875%'."""
    matches = re.findall(r"(\d+\.?\d*)\s*%", text)
    if matches:
        return float(matches[0])
    return None


def fetch_hsbc_prime() -> dict:
    """Fetch HSBC HK Best Lending Rate (Prime Rate)."""
    try:
        resp = requests.get(BANK_URLS["HSBC"], headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        # Look for prime rate / best lending rate text
        for text_block in soup.stripped_strings:
            lower = text_block.lower()
            if "best lending rate" in lower or "prime rate" in lower or "blr" in lower:
                rate = _find_rate_in_text(text_block)
                if rate and 3.0 < rate < 10.0:
                    return {"bank": "HSBC", "rate": rate}
        # Fallback: search all text for patterns like "P = 5.875%"
        full_text = soup.get_text()
        match = re.search(r"(?:best lending rate|prime rate|BLR)[^%]*?(\d+\.?\d*)\s*%", full_text, re.IGNORECASE)
        if match:
            return {"bank": "HSBC", "rate": float(match.group(1))}
    except Exception as e:
        logger.error(f"Failed to fetch HSBC prime rate: {e}")
    return {"bank": "HSBC", "rate": None}


def fetch_boc_prime() -> dict:
    """Fetch Bank of China (Hong Kong) Prime Rate."""
    try:
        resp = requests.get(BANK_URLS["BOC"], headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        full_text = soup.get_text()
        match = re.search(r"(?:prime|best lending)[^%]*?(\d+\.?\d*)\s*%", full_text, re.IGNORECASE)
        if match:
            return {"bank": "BOC", "rate": float(match.group(1))}
        # Try table cells
        for td in soup.find_all("td"):
            text = td.get_text(strip=True)
            rate = _find_rate_in_text(text)
            if rate and 3.0 < rate < 10.0:
                return {"bank": "BOC", "rate": rate}
    except Exception as e:
        logger.error(f"Failed to fetch BOC prime rate: {e}")
    return {"bank": "BOC", "rate": None}


def fetch_scb_prime() -> dict:
    """Fetch Standard Chartered HK Prime Rate."""
    try:
        resp = requests.get(BANK_URLS["SCB"], headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        full_text = soup.get_text()
        match = re.search(r"(?:prime|best lending)[^%]*?(\d+\.?\d*)\s*%", full_text, re.IGNORECASE)
        if match:
            return {"bank": "SCB", "rate": float(match.group(1))}
    except Exception as e:
        logger.error(f"Failed to fetch SCB prime rate: {e}")
    return {"bank": "SCB", "rate": None}


def fetch_hangseng_prime() -> dict:
    """Fetch Hang Seng Bank Prime Rate."""
    try:
        resp = requests.get(BANK_URLS["Hang Seng"], headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        full_text = soup.get_text()
        match = re.search(r"(?:prime|best lending)[^%]*?(\d+\.?\d*)\s*%", full_text, re.IGNORECASE)
        if match:
            return {"bank": "Hang Seng", "rate": float(match.group(1))}
    except Exception as e:
        logger.error(f"Failed to fetch Hang Seng prime rate: {e}")
    return {"bank": "Hang Seng", "rate": None}


def fetch_all_prime_rates() -> list[dict]:
    """Fetch prime rates from all tracked banks."""
    fetchers = [fetch_hsbc_prime, fetch_boc_prime, fetch_scb_prime, fetch_hangseng_prime]
    results = []
    for fn in fetchers:
        try:
            results.append(fn())
        except Exception as e:
            logger.error(f"Error in {fn.__name__}: {e}")
    return results
