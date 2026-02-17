"""Fetch FedWatch-style FOMC meeting rate probabilities from investing.com.

Verified HTML structure (Feb 2026):
- URL: https://www.investing.com/central-banks/fed-rate-monitor
- Page has one table per upcoming FOMC meeting
- Each table preceded by a heading with the meeting date (e.g. "Mar 18, 2026")
- Table columns: Target Rate | Current | Previous Day | Previous Week
- Rows like: "3.50-3.75" | "91.4%" | "91.0%" | "88.2%"

Removed: CME FedWatch direct access (all endpoints return 403/401).
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

from src.config import REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)

FEDWATCH_URL = "https://www.investing.com/central-banks/fed-rate-monitor"

SCRAPE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.investing.com/",
}


def _parse_pct(text: str) -> float | None:
    """Parse a percentage string like '91.4%' → 91.4."""
    match = re.search(r"([\d.]+)\s*%", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _parse_rate_range(text: str) -> str | None:
    """Parse a rate range like '3.50-3.75' or '350-375' from text.

    Returns normalised format like '3.50-3.75'.
    """
    text = text.strip()
    # Direct match: "3.50-3.75" or "3.50 - 3.75"
    m = re.search(r"(\d+\.\d+)\s*[-–]\s*(\d+\.\d+)", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    # Basis-point style: "350-375" → "3.50-3.75"
    m = re.search(r"(\d{3})\s*[-–]\s*(\d{3})", text)
    if m:
        lo = int(m.group(1)) / 100
        hi = int(m.group(2)) / 100
        return f"{lo:.2f}-{hi:.2f}"
    return None


def _extract_meeting_date(text: str) -> str | None:
    """Extract a meeting date from surrounding text.

    Matches patterns like:
    - "Mar 18, 2026" / "March 18, 2026"
    - "2026-03-18"
    - "18 Mar 2026"
    """
    # "Mar 18, 2026" or "March 18, 2026"
    m = re.search(
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(\d{1,2}),?\s+(\d{4})",
        text,
    )
    if m:
        return f"{m.group(1)} {m.group(2)}, {m.group(3)}"

    # "18 Mar 2026"
    m = re.search(
        r"(\d{1,2})\s+"
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*"
        r"\s+(\d{4})",
        text,
    )
    if m:
        return f"{m.group(2)} {m.group(1)}, {m.group(3)}"

    # ISO "2026-03-18"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    return None


def fetch_fedwatch_probabilities() -> list[dict]:
    """Fetch FOMC meeting rate probabilities from investing.com.

    Returns list of dicts like:
        [{"meeting": "Mar 18, 2026",
          "probabilities": {"3.25-3.50": 8.6, "3.50-3.75": 91.4},
          "most_likely": "3.50-3.75",
          "most_likely_pct": 91.4},
         ...]
    """
    try:
        resp = requests.get(FEDWATCH_URL, headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return _parse_investing_page(resp.text)
    except Exception as e:
        logger.error(f"Failed to fetch FedWatch data from investing.com: {e}")
        return []


def _parse_investing_page(html: str) -> list[dict]:
    """Parse the investing.com Fed Rate Monitor page.

    Page structure (verified Feb 2026):
    - Each FOMC meeting is wrapped in <div class="cardWrapper">
    - Date is in <div class="fedRateDate" id="cardName_N"> → "Mar 18, 2026"
    - Table has class "fedRateTbl" with columns: Target Rate | Current | Prev Day | Prev Week
    - Sidebar tables (indices, bonds) are NOT class "fedRateTbl"
    """
    soup = BeautifulSoup(html, "lxml")
    meetings = []

    # Strategy 1: Find tables with the specific "fedRateTbl" class
    tables = soup.find_all("table", class_="fedRateTbl")

    if not tables:
        # Fallback: find tables that look like rate-probability tables
        logger.info("No 'fedRateTbl' class found, trying generic table search")
        tables = [
            t for t in soup.find_all("table")
            if re.search(r"\d+\.\d+\s*[-–]\s*\d+\.\d+", t.get_text())
        ]

    for table in tables:
        # --- Extract meeting date ---
        meeting_date = None

        # Primary: find parent cardWrapper → fedRateDate div
        card_wrapper = table.find_parent("div", class_="cardWrapper")
        if card_wrapper:
            date_div = card_wrapper.find("div", class_="fedRateDate")
            if date_div:
                meeting_date = _extract_meeting_date(date_div.get_text(strip=True))

        # Secondary: find parent cardBlock → infoFed div
        if not meeting_date:
            card_block = table.find_parent("div", class_="cardBlock")
            if card_block:
                info_div = card_block.find("div", class_="infoFed")
                if info_div:
                    meeting_date = _extract_meeting_date(info_div.get_text(strip=True))

        # Tertiary: walk backwards (less reliable for later meetings)
        if not meeting_date:
            prev = table.find_previous(["h1", "h2", "h3", "h4", "h5", "h6", "div", "span"])
            search_count = 0
            while prev and search_count < 20:
                meeting_date = _extract_meeting_date(prev.get_text(strip=True))
                if meeting_date:
                    break
                prev = prev.find_previous(["h1", "h2", "h3", "h4", "h5", "h6", "div", "span"])
                search_count += 1

        if not meeting_date:
            meeting_date = f"Meeting {len(meetings) + 1}"

        # --- Parse table rows ---
        probabilities = {}
        rows = table.find_all("tr")

        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            # First cell = rate range (e.g. "3.50 - 3.75")
            cell_texts = [c.get_text(strip=True) for c in cells]
            rate_range = _parse_rate_range(cell_texts[0])
            if not rate_range:
                continue

            # Second cell = current probability (e.g. "91.4%")
            pct = _parse_pct(cell_texts[1]) if len(cell_texts) > 1 else None
            if pct is not None:
                probabilities[rate_range] = pct

        if probabilities:
            most_likely = max(probabilities, key=probabilities.get)
            meetings.append({
                "meeting": meeting_date,
                "probabilities": probabilities,
                "most_likely": most_likely,
                "most_likely_pct": probabilities[most_likely],
            })

    if meetings:
        logger.info(f"Parsed {len(meetings)} FOMC meetings from investing.com")
        for m in meetings:
            logger.info(f"  {m['meeting']}: {m['most_likely']} ({m['most_likely_pct']:.1f}%)")
    else:
        logger.warning("No FedWatch data found on investing.com page")

    return meetings
