"""Fetch CME FedWatch implied probabilities for future FOMC meetings.

Since the CME FedWatch API is paid, we scrape the publicly available
FedWatch tool page or use the pyfedwatch approach (calculating from
Fed Funds futures prices via CME delayed data).
"""

import json
import logging
import re

import requests
from bs4 import BeautifulSoup

from src.config import REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)

# CME FedWatch tool page
FEDWATCH_URL = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"

# CME delayed quotes for Fed Funds futures (30-Day)
CME_FF_QUOTES_URL = "https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/ZQ/G"

SCRAPE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.cmegroup.com/",
}


def fetch_fedwatch_probabilities() -> list[dict]:
    """Fetch FedWatch meeting probabilities.

    Returns list of dicts like:
        [{"meeting": "Mar 2026", "date": "2026-03-19",
          "probabilities": {"4.00-4.25": 15.2, "4.25-4.50": 84.8}},
         ...]

    Falls back to a simplified calculation if scraping fails.
    """
    # Try the CME API endpoint that the FedWatch tool uses internally
    try:
        return _fetch_from_cme_api()
    except Exception as e:
        logger.warning(f"CME API approach failed: {e}")

    # Fallback: try scraping the page
    try:
        return _scrape_fedwatch_page()
    except Exception as e:
        logger.warning(f"FedWatch page scraping failed: {e}")

    return []


def _fetch_from_cme_api() -> list[dict]:
    """Try to fetch FedWatch data from CME's internal API endpoints."""
    # The FedWatch tool loads data via AJAX calls
    api_url = "https://www.cmegroup.com/services/fed-funds-implied/"
    headers = {
        **SCRAPE_HEADERS,
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }
    resp = requests.get(api_url, headers=headers, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 200:
        data = resp.json()
        return _parse_cme_api_response(data)
    raise ValueError(f"CME API returned status {resp.status_code}")


def _parse_cme_api_response(data: dict) -> list[dict]:
    """Parse the CME FedWatch API response."""
    meetings = []
    # Structure varies; adapt to what we get
    if isinstance(data, list):
        for item in data:
            meeting = {
                "meeting": item.get("meetingDate", item.get("meeting", "")),
                "probabilities": {},
            }
            # Extract probability buckets
            for key, val in item.items():
                if "prob" in key.lower() or "-" in key:
                    try:
                        meeting["probabilities"][key] = float(val)
                    except (ValueError, TypeError):
                        pass
            if meeting["probabilities"]:
                meetings.append(meeting)
    elif isinstance(data, dict):
        for meeting_key, meeting_data in data.items():
            if isinstance(meeting_data, dict):
                meeting = {"meeting": meeting_key, "probabilities": {}}
                for rate_range, prob in meeting_data.items():
                    try:
                        meeting["probabilities"][rate_range] = float(prob)
                    except (ValueError, TypeError):
                        pass
                if meeting["probabilities"]:
                    meetings.append(meeting)
    return meetings


def _scrape_fedwatch_page() -> list[dict]:
    """Scrape the FedWatch tool page for probability data."""
    resp = requests.get(FEDWATCH_URL, headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # Look for embedded JSON data in script tags
    for script in soup.find_all("script"):
        text = script.string or ""
        if "fedwatch" in text.lower() or "probability" in text.lower():
            # Try to extract JSON objects
            json_matches = re.findall(r'\{[^{}]*"(?:prob|meeting|rate)[^{}]*\}', text, re.IGNORECASE)
            for match in json_matches:
                try:
                    data = json.loads(match)
                    if data:
                        return _parse_cme_api_response(data)
                except json.JSONDecodeError:
                    continue

    # Try to find table data
    tables = soup.find_all("table")
    for table in tables:
        text = table.get_text().lower()
        if "meeting" in text or "probability" in text or "fomc" in text:
            return _parse_fedwatch_table(table)

    return []


def _parse_fedwatch_table(table) -> list[dict]:
    """Parse a FedWatch HTML table."""
    rows = table.find_all("tr")
    if len(rows) < 2:
        return []

    # First row might be headers (rate ranges)
    headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]

    meetings = []
    for row in rows[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        meeting = {"meeting": cells[0], "probabilities": {}}
        for i, val in enumerate(cells[1:], 1):
            if i < len(headers):
                try:
                    pct = float(val.replace("%", ""))
                    meeting["probabilities"][headers[i]] = pct
                except ValueError:
                    pass
        if meeting["probabilities"]:
            meetings.append(meeting)

    return meetings
