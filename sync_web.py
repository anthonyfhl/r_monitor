"""Manual legacy-inbox / missing-asset repair. No scheduled task uses this file."""
import logging
import sys
from src.config import DATA_DIR, PROJECT_ROOT
from src.esaver import consume_inbox
from src.state import file_lock, LockBusyError
from src.web_app import publish_registrations, build_dashboard, APP_DIR


def main():
    try:
        with file_lock(DATA_DIR/"monitor.lock"):
            expected=[APP_DIR/p.name for p in (PROJECT_ROOT/"web").iterdir() if p.suffix in (".html",".css",".js",".svg")]
            expected += [APP_DIR/"data.json", APP_DIR/"registrations.json"]
            if any(not p.exists() for p in expected):
                logging.warning("Web resources missing; repair: rebuild from verified local records and source assets")
                build_dashboard()
            records=consume_inbox()
            publish_registrations()
            return 1 if records.get("sync_errors") else 0
    except LockBusyError:
        logging.warning("Daily collector owns the lock; manual repair did not run, legacy inbox preserved")
        return 1
    except Exception:
        logging.exception("Inbox sync failed; records preserved")
        return 1


if __name__=="__main__":
    sys.exit(main())
