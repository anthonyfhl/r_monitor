"""Fetch outcomes including repair results; persisted atomically."""
from datetime import datetime
from src.config import DATA_DIR
from src.state import read_json, write_json

HEALTH_FILE = DATA_DIR / "fetch_health.json"


def load_health():
    return read_json(HEALTH_FILE)


def record_fetch_result(source, success, error="", repair=""):
    state = load_health()
    info = state.setdefault(source, {"consecutive_failures": 0})
    info["consecutive_failures"] = 0 if success else info.get("consecutive_failures", 0) + 1
    info["last_success" if success else "last_failure"] = datetime.now().astimezone().isoformat()
    info.update(ok=success, error=str(error), repair=repair)
    write_json(HEALTH_FILE, state)
    return info["consecutive_failures"]


def get_alerts(threshold=1):
    return [k for k, v in load_health().items() if v.get("consecutive_failures", 0) >= threshold]
