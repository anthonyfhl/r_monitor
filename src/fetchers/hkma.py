"""Fetch rates from HKMA API: HIBOR daily, Base Rate, HKD Forward Rates.

HKMA API only supports `segment` and `offset` parameters.
No server-side date filtering, sorting, or page size control.
All filtering/sorting must be done client-side.

Actual HIBOR field names: end_of_day, ir_overnight, ir_1w, ir_1m, ir_3m, ir_6m, ir_9m, ir_12m
"""

import logging
from datetime import datetime, timedelta

import requests

from src.config import (
    HKMA_BASE,
    HKMA_HIBOR_DAILY,
    HKMA_FORWARD,
    HEADERS,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Maps HKMA API field names -> display names
HIBOR_FIELD_MAP = {
    "ir_overnight": "Overnight",
    "ir_1w": "1 Week",
    "ir_1m": "1 Month",
    "ir_3m": "3 Months",
    "ir_6m": "6 Months",
    "ir_9m": "9 Months",
    "ir_12m": "12 Months",
}


def _hkma_get(url: str, params: dict | None = None, max_pages: int = 50) -> list[dict]:
    """Generic HKMA API paginated fetch.

    HKMA API only supports `offset` for pagination (fixed page size ~100).
    """
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


def _parse_hibor_record(rec: dict) -> dict:
    """Parse a single HIBOR API record into our standard format."""
    row = {"date": rec.get("end_of_day", "")}
    for api_key, display_name in HIBOR_FIELD_MAP.items():
        val = rec.get(api_key)
        if val is not None:
            row[display_name] = float(val)
    return row


def fetch_hibor_latest() -> dict:
    """Fetch the most recent HIBOR fixing rates.

    Returns dict like:
        {"date": "2026-01-30", "Overnight": 2.18, "1 Week": 2.30, ...}
    """
    params = {"segment": "hibor.fixing"}
    resp = requests.get(HKMA_HIBOR_DAILY, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    records = resp.json().get("result", {}).get("records", [])
    if not records:
        logger.warning("No HIBOR records returned")
        return {}

    # Find the most recent date (field is "end_of_day")
    latest_date = max(rec.get("end_of_day", "") for rec in records)

    for rec in records:
        if rec.get("end_of_day") == latest_date:
            return _parse_hibor_record(rec)

    return {}


def fetch_hibor_history(days: int = 365) -> list[dict]:
    """Fetch HIBOR history for the past N days.

    Fetches all available data and filters client-side.
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"segment": "hibor.fixing"}
    records = _hkma_get(HKMA_HIBOR_DAILY, params, max_pages=100)

    results = []
    for rec in records:
        date_str = rec.get("end_of_day", "")
        if date_str < cutoff:
            continue
        results.append(_parse_hibor_record(rec))

    # Sort by date ascending
    results.sort(key=lambda x: x.get("date", ""))
    return results


def fetch_hkma_base_rate() -> dict:
    """Fetch the current HKMA Base Rate.

    Returns dict like: {"date": "2025-10-31", "rate": 4.75}
    """
    url = f"{HKMA_BASE}/er-ir/hkd-ir-effdates"
    params = {}
    resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    records = resp.json().get("result", {}).get("records", [])
    if not records:
        logger.warning("No HKMA base rate records returned")
        return {}

    # Detect the actual field names from the first record
    sample = records[0]
    date_key = "eff_date" if "eff_date" in sample else "effect_date"
    rate_key = next(
        (k for k in ["ir", "base_rate", "best_lending_rate"] if k in sample),
        None,
    )

    if not rate_key:
        logger.warning(f"Unknown HKMA base rate fields: {list(sample.keys())}")
        return {}

    latest = max(records, key=lambda r: r.get(date_key, ""))
    return {"date": latest.get(date_key, ""), "rate": float(latest.get(rate_key, 0))}


def fetch_hkma_base_rate_history() -> list[dict]:
    """Fetch full history of HKMA Base Rate changes."""
    url = f"{HKMA_BASE}/er-ir/hkd-ir-effdates"
    params = {}
    records = _hkma_get(url, params, max_pages=100)
    if not records:
        return []

    sample = records[0]
    date_key = "eff_date" if "eff_date" in sample else "effect_date"
    rate_key = next(
        (k for k in ["ir", "base_rate", "best_lending_rate"] if k in sample),
        None,
    )
    if not rate_key:
        logger.warning(f"Unknown HKMA base rate fields: {list(sample.keys())}")
        return []

    results = []
    for r in records:
        d = r.get(date_key, "")
        v = r.get(rate_key)
        if d and v:
            results.append({"date": d, "rate": float(v)})

    results.sort(key=lambda x: x.get("date", ""))
    return results


def fetch_hkd_forward_rates() -> list[dict]:
    """Fetch the latest HKD forward rates (implied interest rates from FX forwards).

    Returns list of dicts with tenor and rate.
    """
    params = {}
    resp = requests.get(HKMA_FORWARD, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    records = resp.json().get("result", {}).get("records", [])
    if not records:
        return []

    # Detect date field
    sample = records[0]
    date_key = "end_of_day" if "end_of_day" in sample else "end_of_date"

    # Find the latest date
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
