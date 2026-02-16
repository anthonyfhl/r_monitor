"""Fetch SOFR (Secured Overnight Financing Rate) from NY Fed."""

import logging
from datetime import datetime, timedelta

import requests

from src.config import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

NYFED_BASE = "https://markets.newyorkfed.org/api/rates/secured/sofr"


def fetch_sofr_latest() -> dict:
    """Fetch the latest SOFR rate.

    Returns dict like: {"date": "2026-02-14", "rate": 4.31, "percentile_1": 4.30, ...}
    """
    url = f"{NYFED_BASE}/last/1.json"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("refRates", [])
        if not rates:
            return {}
        r = rates[0]
        return {
            "date": r.get("effectiveDate", ""),
            "rate": float(r.get("percentRate", 0)),
            "volume": r.get("volumeInBillions"),
            "percentile_1": r.get("percentPercentile1"),
            "percentile_25": r.get("percentPercentile25"),
            "percentile_75": r.get("percentPercentile75"),
            "percentile_99": r.get("percentPercentile99"),
        }
    except Exception as e:
        logger.error(f"Failed to fetch SOFR: {e}")
        return {}


def fetch_sofr_history(days: int = 365) -> list[dict]:
    """Fetch SOFR history for the past N days."""
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = f"{NYFED_BASE}/search.json"
    params = {"startDate": start, "endDate": end}

    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("refRates", [])
        return [
            {"date": r.get("effectiveDate", ""), "rate": float(r.get("percentRate", 0))}
            for r in rates
        ]
    except Exception as e:
        logger.error(f"Failed to fetch SOFR history: {e}")
        return []
