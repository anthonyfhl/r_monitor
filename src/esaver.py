"""Promotion archive and family registration records, independent of rate fetches."""
from datetime import date, datetime
import html
import json
from pathlib import Path
from contextlib import contextmanager
import time

from src.config import DATA_DIR
from src.loans import APP_URL
from src.state import read_json, write_json, file_lock, LockBusyError, RECOVERY_EVENTS, recover_backup
from src.config import REPORTS_DIR

PROMOTIONS_FILE = DATA_DIR / "esaver_promotions.json"
REGISTRATIONS_FILE = DATA_DIR / "esaver_registrations.json"
NOTIFICATIONS_FILE = DATA_DIR / "esaver_notifications.json"
INBOX_FILE = Path("D:/git_MachinePortal/outputs/inbox/r_monitor__rates.jsonl")
CURSOR_FILE = DATA_DIR / "esaver_inbox_cursor.json"


class InvalidRegistration(ValueError):
    """Rejected form input, distinct from damaged server files or code errors."""


def store_promotion(offer):
    archive = read_json(PROMOTIONS_FILE, {"promotions": []})
    previous = next((r for r in archive["promotions"] if r["id"] == offer["id"]), None)
    if previous:
        # Bank evidence updates dates/rates; original Excel provenance is retained.
        previous.update(offer)
        previous["last_checked"] = datetime.now().astimezone().isoformat()
    else:
        entry={**offer, "discovered_at": datetime.now().astimezone().isoformat()}
        eligible=[p for p in archive["promotions"] if p["id"]<offer["id"] and p["id"] not in offer.get("excluded_months",[])]
        if eligible:
            prior=max(eligible,key=lambda p:p["reward_start"])
            entry["previous_valid_end"]=prior["reward_end"]
            entry["gap_days"]=(date.fromisoformat(offer["reward_start"])-date.fromisoformat(prior["reward_end"])).days
            entry["gap_source"]="Derived from latest previous period not excluded by this offer; family eligibility still needs bank confirmation"
        archive["promotions"].append(entry)
    archive["promotions"].sort(key=lambda r: r["reward_start"])
    write_json(PROMOTIONS_FILE, archive)


def notify_new_promotions(sender, state_path=None):
    path = state_path or NOTIFICATIONS_FILE
    archive = read_json(PROMOTIONS_FILE, {"promotions": []})
    state = read_json(path)
    if "seen" not in state:
        # Existing archive is the baseline, including imported Excel periods.
        state["seen"] = [r["id"] for r in archive["promotions"]]
        write_json(path, state)
        return True
    new = [r for r in archive["promotions"] if r["id"] not in state["seen"] and r.get("source_kind") == "official"]
    for offer in new:
        rates = offer["rates"]
        lines = [f"🆕 <b>DBS eSaver {offer['promo_month']} 新一期</b>",
                 f"💰 港元 20 萬／100 萬：{rates['hkd_200k']:.3f}%｜500 萬：{rates['hkd_5m']:.3f}%",
                 f"💵 美元 2.5 萬：{rates['usd_25k']:.3f}%",
                 f"📅 存款計息 {offer['reward_start']} 至 {offer['reward_end']}（{offer['days']} 日）",
                 f"⏰ 登記截止 {offer['reg_end']}｜比較存款餘額日期 {offer['benchmark_date']}"]
        if offer.get("excluded_months"):
            lines.append("⚠️ 已登記 " + "、".join(offer["excluded_months"]) + " 推廣者不適用；其他限制見條款")
        lines.append(f'<a href="{APP_URL}#esaver">🔗</a>')
        if not sender("\n".join(lines)):
            return False
        state["seen"].append(offer["id"])
        write_json(path, state)
    return True


@contextmanager
def registration_lock(timeout=3):
    """Only serialize short family-file writes, never wait on bank collection."""
    deadline = time.monotonic() + timeout
    while True:
        lock = file_lock(DATA_DIR / "registrations.lock")
        try:
            lock.__enter__()
            break
        except LockBusyError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def _publish_records(records, app_dir=None):
    """Publish while holding registration_lock; verify before acknowledging."""
    output = (app_dir or REPORTS_DIR / "app") / "registrations.json"
    visible = {**records, "save_mode": "immediate"}
    visible.pop("sync_mode", None)
    if RECOVERY_EVENTS:
        visible["sync_errors"] = list(dict.fromkeys(visible.get("sync_errors", []) + RECOVERY_EVENTS))
    # A failed derived-file write gets one repair attempt from canonical data.
    try:
        write_json(output, visible)
    except OSError:
        RECOVERY_EVENTS.append("展示檔案寫入曾失敗；已即時從正式家人紀錄重建。")
        visible["sync_errors"] = list(dict.fromkeys(visible.get("sync_errors", []) + RECOVERY_EVENTS))
        write_json(output, visible)
    if read_json(output) != visible:
        raise RuntimeError("Published registrations failed verification; canonical records preserved")
    return visible


def _read_records(records_file=None):
    source = records_file or REGISTRATIONS_FILE
    def validated(path):
        value = read_json(path)
        if not isinstance(value, dict) or not isinstance(value.get("registrations"), dict) or not isinstance(value.get("members"), list) or not isinstance(value.get("version"), int) or not isinstance(value.get("save_receipts", {}), dict):
            raise ValueError("Family record file has an invalid schema")
        return value
    if not source.exists():
        backup = source.with_name(source.name + ".bak")
        if not backup.exists():
            raise RuntimeError("Family record missing; no verified backup to restore, refusing empty replacement")
        records = validated(backup)
        write_json(source, records)
        RECOVERY_EVENTS.append("正式家人紀錄檔案遺失；已從驗證過的備份復原。")
        return records
    try:
        return validated(source)
    except ValueError:
        return recover_backup(source, validated)


def publish_registrations(app_dir=None, records_file=None):
    with registration_lock():
        records = _read_records(records_file)
        return _publish_records(records, app_dir)


def save_registration(event, app_dir=None):
    """Commit the validated record and published view before returning success.

    A request token is stored in the SAME atomic file as the record. Repeating
    an uncertain submission cannot duplicate it, even after later edits.
    """
    if event.get("kind") != "esaver_registration":
        raise InvalidRegistration("Unknown registration event kind")
    data = event.get("payload")
    if not isinstance(data, dict):
        raise InvalidRegistration("Registration payload must be an object")
    event_id = data.get("event_id")
    member = data.get("member")
    promo = data.get("promo_id")
    status = data.get("status")
    registered_on = data.get("registered_on") or None
    if not isinstance(event_id, str) or not 8 <= len(event_id) <= 80:
        raise InvalidRegistration("Invalid request identifier")
    if not isinstance(member, str) or not 1 <= len(member.strip()) <= 60 or any(ord(c) < 32 for c in member) or "|" in member:
        raise InvalidRegistration("Invalid family member name")
    member = member.strip()
    if not isinstance(promo, str) or status not in ("registered", "not_registered"):
        raise InvalidRegistration("Invalid promotion or registration status")
    if registered_on is not None:
        try:
            valid_date = isinstance(registered_on, str) and date.fromisoformat(registered_on).isoformat() == registered_on and registered_on <= date.today().isoformat()
        except ValueError:
            valid_date = False
        if not valid_date:
            raise InvalidRegistration("Invalid or future registration date")
    payload = {"promo_id": promo, "member": member, "status": status, "registered_on": registered_on}
    with registration_lock():
        periods = {p["id"] for p in read_json(PROMOTIONS_FILE, {"promotions": []})["promotions"]}
        if promo not in periods:
            raise InvalidRegistration("Unknown promotion period")
        records = _read_records()
        receipts = records.setdefault("save_receipts", {})
        if event_id in receipts:
            if receipts[event_id] != payload:
                raise InvalidRegistration("Request identifier was already used for different data")
        else:
            key = f"{promo}|{member}"
            records["registrations"][key] = {**records["registrations"].get(key, {}), **payload,
                "updated_at": event["utc"], "source": "web", "event_id": event_id}
            if member not in records["members"]:
                records["members"].append(member)
            records["version"] += 1
            records["synced_at"] = event["utc"]
            receipts[event_id] = payload
            try:
                write_json(REGISTRATIONS_FILE, records)
            except OSError:
                # Repair a removed parent directory or transient local write;
                # no network and no recurring job. Atomic replacement keeps old data.
                REGISTRATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
                write_json(REGISTRATIONS_FILE, records)
                RECOVERY_EVENTS.append("家人紀錄首次寫入失敗；已即時修復檔案路徑並重新寫入。")
        if read_json(REGISTRATIONS_FILE) != records:
            raise RuntimeError("Family record write failed verification")
        visible = _publish_records(records, app_dir)
        return {"ok": True, "committed": True, "event_id": event_id, "registrations": visible}


def consume_inbox(inbox_path=None):
    """Migration-only: keep older accepted submissions, under the same lock."""
    with registration_lock():
        return _consume_inbox(inbox_path)


def _consume_inbox(inbox_path=None):
    """Validate and consume append-only portal events. Never modify portal files."""
    inbox = inbox_path or INBOX_FILE
    cursor = read_json(CURSOR_FILE, {"offset": 0, "event_ids": []})
    records = _read_records()
    if not inbox.exists():
        return records
    archive = read_json(PROMOTIONS_FILE, {"promotions": []})
    periods = {p["id"] for p in archive["promotions"]}
    raw = inbox.read_bytes()
    if len(raw) < cursor["offset"]:
        # Quarantine the old cursor and replay the surviving append-only events.
        # Saved event ids prevent duplicate records; saved registrations survive.
        quarantine = DATA_DIR / "quarantine"
        quarantine.mkdir(exist_ok=True)
        write_json(quarantine / ("inbox_cursor_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".json"), cursor)
        cursor["offset"] = 0
        records.setdefault("sync_errors", []).append("收件箱曾被截短；已保留原紀錄及游標備份，重讀現存事件並去除重複。")
    lines = raw[cursor["offset"]:].splitlines(keepends=True)
    errors = []
    for line in lines:
        if not line.endswith(b"\n"):
            break  # A live append may be incomplete; leave it for the next pass.
        try:
            event = json.loads(line)
            if event["kind"] != "esaver_registration":
                raise ValueError("Unknown event kind")
            data = event["payload"]
            event_id = data["event_id"]
            if not isinstance(event_id, str) or not 8 <= len(event_id) <= 80:
                raise ValueError("Invalid event identifier")
            if event_id in cursor["event_ids"] or event_id in records.get("processed_event_ids", []) or any(r.get("event_id")==event_id for r in records["registrations"].values()):
                cursor["offset"] += len(line)
                continue
            member = data["member"].strip()
            promo = data["promo_id"]
            if promo not in periods or not 1 <= len(member) <= 60 or any(ord(c) < 32 for c in member):
                raise ValueError("Unknown period or invalid member name")
            if data["status"] not in ("registered", "not_registered"):
                raise ValueError("Invalid registration status")
            registered_on = data.get("registered_on") or None
            if registered_on:
                date.fromisoformat(registered_on)
                if registered_on > date.today().isoformat():
                    raise ValueError("Registration date cannot be in the future")
            existing = records["registrations"].get(f"{promo}|{member}", {})
            records["registrations"][f"{promo}|{member}"] = {**existing,
                "promo_id": promo, "member": member, "status": data["status"], "registered_on": registered_on,
                "updated_at": event["utc"], "source": "web", "event_id": event_id}
            if member not in records["members"]:
                records["members"].append(member)
            records["version"] += 1
            cursor["event_ids"].append(event_id)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            # Preserve invalid input and continue valid events, with a visible warning.
            quarantine = DATA_DIR / "quarantine"
            quarantine.mkdir(exist_ok=True)
            with (quarantine / "invalid_registration_events.jsonl").open("ab") as target:
                target.write(line)
            errors.append(f"Invalid registration event quarantined: {exc}")
        cursor["offset"] += len(line)
    records["sync_errors"] = errors or records.get("sync_errors", [])
    records["processed_event_ids"] = list(dict.fromkeys(records.get("processed_event_ids", []) + cursor["event_ids"]))
    records["synced_at"] = datetime.now().astimezone().isoformat()
    # The event id in each saved record also allows recovery if cursor write crashes.
    write_json(REGISTRATIONS_FILE, records)
    write_json(CURSOR_FILE, cursor)
    return records
