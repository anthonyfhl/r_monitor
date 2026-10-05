"""Seed verified public history under the existing bank-data writer lock."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.dsb import store_offer, store_calendar
from src.dsb_reference import archived_rules, calendar_2024
from src.config import DATA_DIR
from src.state import file_lock

if __name__ == '__main__':
    with file_lock(DATA_DIR / 'monitor.lock'):
        for rule in archived_rules():
            store_offer(rule)
        store_calendar(calendar_2024())
    print('Archived April/July terms and 2024 government holiday calendar imported')
