"""Track fetch health and alert on persistent failures."""

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.config import DATA_DIR
from src.storage import load_csv

logger = logging.getLogger(__name__)

HEALTH_FILE = DATA_DIR / "fetch_health.json"


def load_health() -> dict:
    """Load health state from JSON file."""
    if HEALTH_FILE.exists():
        try:
            return json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_health(state: dict) -> None:
    """Save health state to JSON file."""
    HEALTH_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def record_fetch_result(source: str, success: bool) -> int:
    """Record a fetch result. Returns consecutive failure count."""
    state = load_health()
    if source not in state:
        state[source] = {"consecutive_failures": 0, "last_success": None, "last_failure": None}

    if success:
        state[source]["consecutive_failures"] = 0
        state[source]["last_success"] = datetime.now().isoformat()
    else:
        state[source]["consecutive_failures"] += 1
        state[source]["last_failure"] = datetime.now().isoformat()

    save_health(state)
    return state[source]["consecutive_failures"]


def get_alerts(threshold: int = 3) -> list[str]:
    """Get list of sources with consecutive failures >= threshold."""
    state = load_health()
    return [
        source for source, info in state.items()
        if info.get("consecutive_failures", 0) >= threshold
    ]


def check_staleness(threshold_days: int = 3) -> list[tuple[str, str, int]]:
    """Check each CSV for stale data.

    Returns list of (csv_name, last_date, days_stale) for stale sources.
    """
    stale = []
    csvs_to_check = ["hibor_daily", "fed_rates", "sofr", "treasury_yields", "ib_rates"]
    today = pd.Timestamp.now().normalize()

    for name in csvs_to_check:
        df = load_csv(name)
        if df.empty or "date" not in df.columns:
            stale.append((name, "no data", -1))
            continue
        last_date = pd.to_datetime(df["date"]).max()
        gap = (today - last_date).days
        if gap > threshold_days:
            stale.append((name, str(last_date.date()), gap))

    return stale
