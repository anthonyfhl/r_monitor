"""Fetch rates from HKMA API: HIBOR daily, Base Rate, HKD Forward Rates."""

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

HIBOR_FIELD_MAP = {
    "overnight": "Overnight",
    "1w": "1 Week",
    "1m": "1 Month",
    "2m": "2 Months",
    "3m": "3 Months",
    "6m": "6 Months",
    "12m": "12 Months",
}


def _hkma_get(url: str, params: dict | None = None) -> list[dict]:
    """Generic HKMA API paginated fetch."""
    all_records = []
    params = params or {}
    params.setdefault("pagesize", 100)
    offset = 0
    while True:
        params["offset"] = offset
        resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        records = result.get("records", [])
        if not records:
            break
        all_records.extend(records)
        total = result.get("datasize", len(records))
        offset += len(records)
        if offset >= total:
            break
    return all_records


def fetch_hibor_latest() -> dict:
    """Fetch the most recent HIBOR fixing rates.

    Returns dict like:
        {"date": "2026-02-15", "Overnight": 3.95, "1 Week": 4.01, ...}
    """
    params = {"segment": "hibor.fixing", "pagesize": 1, "sortby": "end_of_date", "sortorder": "desc"}
    resp = requests.get(HKMA_HIBOR_DAILY, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    records = resp.json().get("result", {}).get("records", [])
    if not records:
        logger.warning("No HIBOR records returned")
        return {}
    rec = records[0]
    result = {"date": rec.get("end_of_date", "")}
    for api_key, display_name in HIBOR_FIELD_MAP.items():
        val = rec.get(api_key)
        if val is not None:
            result[display_name] = float(val)
    return result


def fetch_hibor_history(days: int = 365) -> list[dict]:
    """Fetch HIBOR history for the past N days."""
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "segment": "hibor.fixing",
        "sortby": "end_of_date",
        "sortorder": "asc",
        "choose": "end_of_date",
        "from": start,
        "to": end,
    }
    records = _hkma_get(HKMA_HIBOR_DAILY, params)
    results = []
    for rec in records:
        row = {"date": rec.get("end_of_date", "")}
        for api_key, display_name in HIBOR_FIELD_MAP.items():
            val = rec.get(api_key)
            if val is not None:
                row[display_name] = float(val)
        results.append(row)
    return results


def fetch_hkma_base_rate() -> dict:
    """Fetch the current HKMA Base Rate.

    Returns dict like: {"date": "2026-01-30", "rate": 4.75}
    """
    url = f"{HKMA_BASE}/er-ir/hkd-ir-effdates"
    params = {"segment": "base.rate", "pagesize": 1, "sortby": "eff_date", "sortorder": "desc"}
    resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    records = resp.json().get("result", {}).get("records", [])
    if not records:
        logger.warning("No HKMA base rate records returned")
        return {}
    rec = records[0]
    return {"date": rec.get("eff_date", ""), "rate": float(rec.get("ir", 0))}


def fetch_hkma_base_rate_history() -> list[dict]:
    """Fetch full history of HKMA Base Rate changes."""
    url = f"{HKMA_BASE}/er-ir/hkd-ir-effdates"
    params = {"segment": "base.rate", "sortby": "eff_date", "sortorder": "asc"}
    records = _hkma_get(url, params)
    return [{"date": r.get("eff_date", ""), "rate": float(r.get("ir", 0))} for r in records]


def fetch_hkd_forward_rates() -> list[dict]:
    """Fetch the latest HKD forward rates (implied interest rates from FX forwards).

    Returns list of dicts with tenor and rate.
    """
    params = {"pagesize": 20, "sortby": "end_of_date", "sortorder": "desc"}
    resp = requests.get(HKMA_FORWARD, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    records = resp.json().get("result", {}).get("records", [])
    if not records:
        return []
    # Get only the latest date's records
    latest_date = records[0].get("end_of_date", "")
    results = []
    for rec in records:
        if rec.get("end_of_date") != latest_date:
            break
        results.append({
            "date": rec.get("end_of_date", ""),
            "tenor": rec.get("tenor", ""),
            "bid": rec.get("bid"),
            "offer": rec.get("offer"),
        })
    return results
