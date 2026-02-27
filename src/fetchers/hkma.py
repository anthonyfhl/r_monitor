"""Fetch HKD rates: HIBOR from HKAB, HKD Forward Rates from HKMA.

HIBOR fixings are sourced from the HKAB (Hong Kong Association of Banks) API,
which is the authoritative publisher and provides same-day data for all tenors.

HKMA API is still used for HKD forward rates.
"""

import logging
from datetime import datetime, timedelta

import requests

from src.config import (
    HKMA_FORWARD,
    HEADERS,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)

HKAB_HIBOR_URL = "https://www.hkab.org.hk/api/hibor"

# Maps HKAB JSON keys -> our display names (4 key tenors only)
HIBOR_FIELD_MAP = {
    "Overnight": "Overnight",
    "1 Month": "1 Month",
    "3 Months": "3 Months",
    "12 Months": "12 Months",
}


def fetch_hibor_latest() -> dict:
    """Fetch the most recent HIBOR fixing rates from HKAB.

    Returns dict like:
        {"date": "2026-02-27", "Overnight": 2.55, "1 Month": 2.41, ...}
    """
    now = datetime.now()
    resp = requests.get(
        HKAB_HIBOR_URL,
        params={"year": now.year, "month": now.month, "day": now.day},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("isHoliday"):
        for offset in range(1, 5):
            prev = now - timedelta(days=offset)
            resp = requests.get(
                HKAB_HIBOR_URL,
                params={"year": prev.year, "month": prev.month, "day": prev.day},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("isHoliday"):
                break

    if data.get("isHoliday"):
        logger.warning("HKAB returned holiday for recent days")
        return {}

    date_str = f"{data['year']}-{data['month']:02d}-{data['day']:02d}"
    row = {"date": date_str}
    for hkab_key, display_name in HIBOR_FIELD_MAP.items():
        val = data.get(hkab_key)
        if val is not None:
            row[display_name] = float(val)

    return row


def _hkma_get(url: str, params: dict | None = None, max_pages: int = 50) -> list[dict]:
    """Generic HKMA API paginated fetch."""
    all_records = []
    params = params or {}
    offset = 0
    page = 0
    while page < max_pages:
        params["offset"] = offset
        resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        records = result.get("records", [])
        if not records:
            break
        all_records.extend(records)
        total = result.get("datasize", 0)
        offset += len(records)
        page += 1
        if total and offset >= total:
            break
    return all_records


def fetch_hkd_forward_rates() -> list[dict]:
    """Fetch the latest HKD forward rates (implied interest rates from FX forwards)."""
    params = {}
    resp = requests.get(HKMA_FORWARD, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    records = resp.json().get("result", {}).get("records", [])
    if not records:
        return []

    sample = records[0]
    date_key = "end_of_day" if "end_of_day" in sample else "end_of_date"
    latest_date = max(r.get(date_key, "") for r in records)

    results = []
    for rec in records:
        if rec.get(date_key) != latest_date:
            continue
        results.append({
            "date": rec.get(date_key, ""),
            "tenor": rec.get("tenor", ""),
            "bid": rec.get("bid"),
            "offer": rec.get("offer"),
        })
    return results
