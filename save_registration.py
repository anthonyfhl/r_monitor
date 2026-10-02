"""Project-owned synchronous save handler, called only by the authenticated hub.

JSON envelope on stdin; one JSON response on stdout. No network or scheduler.
"""
import json
import logging
import sys

from src.esaver import save_registration, InvalidRegistration


def main():
    try:
        event = json.loads(sys.stdin.buffer.read(8193).decode("utf-8"))
        result = save_registration(event)
    except (InvalidRegistration, json.JSONDecodeError, UnicodeDecodeError) as exc:
        result = {"ok": False, "status": 400, "error": str(exc)}
    except Exception:
        logging.exception("Registration save failed after available file recovery; original records preserved")
        result = {"ok": False, "status": 503,
                  "error": "未能確認保存；原紀錄及表格已保留，可用同一筆提交再次保存。"}
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
