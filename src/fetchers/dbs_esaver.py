"""Fetch DBS eSaver promotional savings rates for EXISTING customers.

Parses the current ETB (Existing To Bank) T&C PDF to extract rates and dates.
The webpage shows existing customer rates as PNG images (not scrapable HTML),
so we fetch the T&C PDF directly.

URL pattern for ETB T&Cs:
  https://www.dbs.com.hk/iwov-resources/pdf/deposits/YYYYMM_eSaver_ETB_Generic_TC.pdf
"""

import logging
import re
from datetime import datetime

import fitz  # PyMuPDF
import requests

from src.config import REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)

ETB_TC_URL_TEMPLATE = (
    "https://www.dbs.com.hk/iwov-resources/pdf/deposits/"
    "{yyyymm}_eSaver_ETB_Generic_TC.pdf"
)

HEADERS = {"User-Agent": USER_AGENT}

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def fetch_esaver_current() -> dict:
    """Fetch the current DBS eSaver promotion for existing customers.

    Tries the current month's ETB T&C PDF first, then the previous month.

    Returns dict like:
        {
            "promo_month": "2026-02",
            "reg_end": "2026-03-06",
            "reward_end": "2026-05-07",
            "min_hkd": 200000,
            "min_usd": 25000,
            "hkd_esaver_rate": 2.875,
            "usd_esaver_rate": 3.699,
            "max_total_hkd": 3.0,
            "max_total_usd": 3.7,
            "has_levelup": "no",
        }
    """
    now = datetime.now()

    # Try current month first, then previous month
    candidates = [
        now.strftime("%Y%m"),
    ]
    # Previous month
    if now.month == 1:
        candidates.append(f"{now.year - 1}12")
    else:
        candidates.append(f"{now.year}{now.month - 1:02d}")

    for yyyymm in candidates:
        url = ETB_TC_URL_TEMPLATE.format(yyyymm=yyyymm)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                logger.info(f"Fetched ETB T&C PDF: {url}")
                result = _parse_etb_pdf(resp.content)
                if result:
                    return result
            else:
                logger.debug(f"ETB T&C PDF not found: {url} ({resp.status_code})")
        except Exception as e:
            logger.warning(f"Failed to fetch ETB T&C PDF {url}: {e}")

    logger.error("Could not fetch any ETB T&C PDF")
    return {}


def _parse_etb_pdf(pdf_bytes: bytes) -> dict:
    """Parse an ETB T&C PDF to extract promotion details."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text() + "\n"
    doc.close()

    result = {}

    # --- Promo month ---
    # Pattern: "DBS e$aver Deposit Promotion for Selected Individual Customers (February 2026)"
    m = re.search(
        r"Promotion\s+for\s+Selected\s+Individual\s+Customers\s*\("
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{4})\)",
        text, re.IGNORECASE,
    )
    if m:
        month_num = MONTH_NAMES.get(m.group(1).lower(), 0)
        result["promo_month"] = f"{m.group(2)}-{month_num:02d}"

    # --- Registration end date ---
    # Pattern: "now until 6 March 2026" or "runs from now until DD Month YYYY"
    m = re.search(
        r"(?:runs\s+from\s+now\s+until|now\s+until)\s+"
        r"(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{4})",
        text, re.IGNORECASE,
    )
    if m:
        day, month_name, year = m.group(1), m.group(2), m.group(3)
        month_num = MONTH_NAMES.get(month_name.lower(), 0)
        result["reg_end"] = f"{year}-{month_num:02d}-{int(day):02d}"

    # --- Reward counting period end ---
    # Pattern: 'until 7 May 2026 ("Reward Counting\n Period")'
    # The text "Reward Counting Period" appears after the date, possibly with newlines
    m = re.search(
        r'(\d{1,2})\s+'
        r'(January|February|March|April|May|June|July|August|September|October|November|December)'
        r'\s+(\d{4})\s*.{0,30}Reward\s+Counting\s+Period',
        text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        day, month_name, year = m.group(1), m.group(2), m.group(3)
        month_num = MONTH_NAMES.get(month_name.lower(), 0)
        result["reward_end"] = f"{year}-{month_num:02d}-{int(day):02d}"

    # --- Minimum eligible funds ---
    # Pattern: "Eligible New Funds of HK$200,000 and /or US$25,000"
    m = re.search(r'HK\$(\d[\d,]+)\s+and\s*/?\s*or\s+US\$(\d[\d,]+)', text)
    if m:
        result["min_hkd"] = int(m.group(1).replace(",", ""))
        result["min_usd"] = int(m.group(2).replace(",", ""))
    else:
        result["min_hkd"] = 200000
        result["min_usd"] = 25000

    # --- e$aver interest rates ---
    # Pattern in Table 1:
    #   HK$200,000 to HK$10,000,000    +2.875%
    #   US$25,000 to US$1,300,000       +3.699%
    m = re.search(r'HK\$\d[\d,]+\s*(?:to|-)\s*HK\$\d[\d,]+\s*\n?\s*\+?(\d+\.?\d*)\s*%', text)
    if m:
        result["hkd_esaver_rate"] = float(m.group(1))

    m = re.search(r'US\$\d[\d,]+\s*(?:to|-)\s*US\$\d[\d,]+\s*\n?\s*\+?(\d+\.?\d*)\s*%', text)
    if m:
        result["usd_esaver_rate"] = float(m.group(1))

    # --- Max total rates ---
    # From example tables: rows like "HK$5,000,000 ... Up to 3.00%"
    # and "US$25,000 ... Up to 3.70%"
    # Find all "Up to X%" values and pair with preceding currency context
    hkd_totals = []
    usd_totals = []
    for m in re.finditer(r'Up\s+to\s+(\d+\.?\d*)\s*%', text, re.IGNORECASE):
        val = float(m.group(1))
        # Look at the 200 chars before this match for currency context
        ctx = text[max(0, m.start() - 200):m.start()]
        last_hk = ctx.rfind("HK$")
        last_us = ctx.rfind("US$")
        if last_hk > last_us:
            hkd_totals.append(val)
        elif last_us > last_hk:
            usd_totals.append(val)

    if hkd_totals:
        result["max_total_hkd"] = max(hkd_totals)
    if usd_totals:
        result["max_total_usd"] = max(usd_totals)

    # Fallback: calculate from esaver_rate + typical basic rate
    if not result.get("max_total_hkd") and result.get("hkd_esaver_rate"):
        result["max_total_hkd"] = round(result["hkd_esaver_rate"] + 0.125, 2)
    if not result.get("max_total_usd") and result.get("usd_esaver_rate"):
        result["max_total_usd"] = round(result["usd_esaver_rate"] + 0.001, 3)

    # --- Level-Up ---
    # Check if the T&C mentions Level-Up bonus
    has_levelup = bool(re.search(r'Level.?Up\s+Bonus', text, re.IGNORECASE))
    result["has_levelup"] = "yes" if has_levelup else "no"

    # --- Exclusions ---
    # Pattern: 'previously registered for "DBS e$aver ... (Month YYYY)"'
    # These are months whose participants cannot join this promotion
    excluded_months = []
    for m in re.finditer(r'previously\s+registered\s+for[^.;]*', text, re.IGNORECASE | re.DOTALL):
        chunk = m.group()
        for mm in re.finditer(r'\((\w+)\s+(\d{4})\)', chunk):
            month_name = mm.group(1)
            year = mm.group(2)
            if month_name.lower() in MONTH_NAMES:
                short = f"{month_name[:3]} {year}"
                excluded_months.append(short)
    if excluded_months:
        result["excludes"] = "; ".join(excluded_months)

    if result.get("promo_month"):
        logger.info(
            f"DBS eSaver (ETB): {result['promo_month']} — "
            f"HKD +{result.get('hkd_esaver_rate', '?')}%, "
            f"USD +{result.get('usd_esaver_rate', '?')}%, "
            f"max HKD {result.get('max_total_hkd', '?')}%, "
            f"max USD {result.get('max_total_usd', '?')}%"
        )

    return result
