"""CSV-based historical data storage for rate tracking."""

import csv
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.config import DATA_DIR

logger = logging.getLogger(__name__)


def _csv_path(name: str) -> Path:
    return DATA_DIR / f"{name}.csv"


def load_csv(name: str) -> pd.DataFrame:
    """Load a CSV file into a DataFrame. Returns empty DataFrame if file doesn't exist."""
    path = _csv_path(name)
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, parse_dates=["date"] if "date" in _peek_columns(path) else False)
        return df
    except Exception as e:
        logger.error(f"Failed to load {path}: {e}")
        return pd.DataFrame()


def _peek_columns(path: Path) -> list[str]:
    """Read just the header row of a CSV."""
    try:
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            return next(reader, [])
    except Exception:
        return []


def save_csv(name: str, df: pd.DataFrame) -> None:
    """Save a DataFrame to CSV."""
    path = _csv_path(name)
    df.to_csv(path, index=False)
    logger.info(f"Saved {len(df)} rows to {path}")


def append_row(name: str, row: dict) -> None:
    """Append a single row to a CSV file. Skips if date already exists."""
    df = load_csv(name)
    date_val = row.get("date", "")

    if not df.empty and "date" in df.columns and date_val:
        # Convert to string for comparison
        existing_dates = df["date"].astype(str).values
        if str(date_val) in existing_dates:
            logger.debug(f"Date {date_val} already exists in {name}, skipping")
            return

    new_row = pd.DataFrame([row])
    df = pd.concat([df, new_row], ignore_index=True)
    save_csv(name, df)


def append_rows(name: str, rows: list[dict]) -> None:
    """Append multiple rows, skipping dates that already exist."""
    if not rows:
        return
    df = load_csv(name)
    existing_dates = set()
    if not df.empty and "date" in df.columns:
        existing_dates = set(df["date"].astype(str).values)

    new_rows = [r for r in rows if str(r.get("date", "")) not in existing_dates]
    if not new_rows:
        logger.debug(f"No new rows to append to {name}")
        return

    new_df = pd.DataFrame(new_rows)
    df = pd.concat([df, new_df], ignore_index=True)
    if "date" in df.columns:
        df = df.sort_values("date").reset_index(drop=True)
    save_csv(name, df)
    logger.info(f"Appended {len(new_rows)} new rows to {name}")


def get_recent(name: str, days: int = 30) -> pd.DataFrame:
    """Get rows from the last N days."""
    df = load_csv(name)
    if df.empty or "date" not in df.columns:
        return df
    df["date"] = pd.to_datetime(df["date"])
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
    return df[df["date"] >= cutoff].reset_index(drop=True)


def get_change(name: str, column: str, days: int = 7) -> float | None:
    """Calculate the change in a column over N days.

    Returns the difference: latest_value - value_N_days_ago
    """
    df = load_csv(name)
    if df.empty or "date" not in df.columns or column not in df.columns:
        return None

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").dropna(subset=[column])

    if len(df) < 2:
        return None

    latest = df.iloc[-1][column]
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
    past = df[df["date"] <= cutoff]

    if past.empty:
        # Use the earliest available
        past_val = df.iloc[0][column]
    else:
        past_val = past.iloc[-1][column]

    try:
        return float(latest) - float(past_val)
    except (ValueError, TypeError):
        return None
