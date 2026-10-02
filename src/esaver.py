"""Promotion archive and family registration records, independent of rate fetches."""
from datetime import date, datetime
import html
import json
from pathlib import Path

from src.config import DATA_DIR
from src.loans import APP_URL
from src.state import read_json, write_json

PROMOTIONS_FILE = DATA_DIR / "esaver_promotions.json"
REGISTRATIONS_FILE = DATA_DIR / "esaver_registrations.json"
NOTIFICATIONS_FILE = DATA_DIR / "esaver_notifications.json"
INBOX_FILE = Path("D:/git_MachinePortal/outputs/inbox/r_monitor__rates.jsonl")
CURSOR_FILE = DATA_DIR / "esaver_inbox_cursor.json"


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


def consume_inbox(inbox_path=None):
    """Validate and consume append-only portal events. Never modify portal files."""
    inbox = inbox_path or INBOX_FILE
    cursor = read_json(CURSOR_FILE, {"offset": 0, "event_ids": []})
    records = read_json(REGISTRATIONS_FILE, {"members": ["Mum", "Fong", "Pik"], "registrations": {}, "version": 0})
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
