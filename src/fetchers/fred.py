"""Fetch Federal Reserve interest rates from FRED API."""

import logging
from datetime import datetime, timedelta

import requests

from src.config import FRED_API_KEY, FRED_BASE, FRED_SERIES, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


def _fred_get(series_id: str, start_date: str | None = None, end_date: str | None = None) -> list[dict]:
    """Fetch observations from FRED for a given series."""
    if not FRED_API_KEY:
        logger.error("FRED_API_KEY not set")
        return []

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
    }
    if start_date:
        params["observation_start"] = start_date
    if end_date:
        params["observation_end"] = end_date

    resp = requests.get(FRED_BASE, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    observations = data.get("observations", [])
    # Filter out missing values
    return [o for o in observations if o.get("value", ".") != "."]


def fetch_fed_funds_rate() -> dict:
    """Fetch current Federal Funds Rate (effective + target range).

    Returns dict like:
        {"date": "2026-02-14", "effective": 4.33,
         "target_upper": 4.50, "target_lower": 4.25}
    """
    result = {}

    for key, series_id in FRED_SERIES.items():
        try:
            obs = _fred_get(series_id)
            if obs:
                latest = obs[0]
                result["date"] = latest.get("date", "")
                if key == "fed_funds_effective":
                    result["effective"] = float(latest["value"])
                elif key == "fed_funds_target_upper":
                    result["target_upper"] = float(latest["value"])
                elif key == "fed_funds_target_lower":
                    result["target_lower"] = float(latest["value"])
        except Exception as e:
            logger.error(f"Failed to fetch FRED series {series_id}: {e}")

    return result


def fetch_fed_funds_history(days: int = 365) -> list[dict]:
    """Fetch daily Fed Funds Effective Rate history."""
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        obs = _fred_get("DFF", start_date=start, end_date=end)
        obs.reverse()  # chronological order
        return [{"date": o["date"], "rate": float(o["value"])} for o in obs]
    except Exception as e:
        logger.error(f"Failed to fetch Fed Funds history: {e}")
        return []


def fetch_fed_target_history() -> list[dict]:
    """Fetch Fed Funds Target Rate (upper) full history."""
    try:
        obs = _fred_get("DFEDTARU", start_date="2000-01-01")
        obs.reverse()
        results = []
        for o in obs:
            upper = float(o["value"])
            results.append({"date": o["date"], "target_upper": upper})
        return results
    except Exception as e:
        logger.error(f"Failed to fetch Fed target history: {e}")
        return []
