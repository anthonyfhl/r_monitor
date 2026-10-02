"""Daily rate collection -> archive -> web application -> change notifications."""
import argparse
import html
import json
import logging
import sys
from datetime import datetime

from src.config import DATA_DIR
from src.esaver import consume_inbox, store_promotion, notify_new_promotions
from src.fetchers.banks import fetch_hsbc_prime, fetch_hase_prime, fetch_dbs_prime
from src.fetchers.hkma import fetch_hibor_latest, fetch_hkd_forward_rates
from src.fetchers.ib_rates import fetch_ib_margin_rates
from src.fetchers.fred import fetch_fed_funds_rate
from src.fetchers.ny_fed import fetch_sofr_latest
from src.fetchers.treasury import fetch_treasury_yields
from src.fetchers.fedwatch import fetch_fedwatch_probabilities
from src.fetchers.dbs_esaver import fetch_esaver_current
from src.health import record_fetch_result, load_health
from src.http_client import RefusalError, GuardError
from src.loans import calculate_loans, notify_changes, APP_URL
from src.ib_margin import notify_margin_changes
from src.state import file_lock, read_json, write_json, LockBusyError, RECOVERY_EVENTS
from src.storage import upsert_row
from src.telegram_sender import send_message
from src.web_app import build_dashboard, SNAPSHOT_FILE, last_valid_forwards

logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",handlers=[logging.StreamHandler(sys.stdout)])
logger=logging.getLogger(__name__)


def _checked(source, function, valid):
    try:
        result=function()
        if not valid(result):
            raise ValueError(f"{source}: source returned incomplete or invalid data")
        record_fetch_result(source,True)
        return result
    except Exception as exc:
        logger.exception("Fetch failed for %s",source)
        from src.repair import repair_source
        outcome=repair_source(source,exc)
        record_fetch_result(source,False,str(exc),outcome)
        return None


def fetch_all():
    data={}
    jobs=[
        ("hibor",fetch_hibor_latest,lambda r:r.get("date") and r.get("1 Month") is not None),
        ("ib_rates",fetch_ib_margin_rates,lambda r:all(r.get(k) and r[k].get("tiers") and r[k].get("rate") is not None for k in ["HKD","USD"])),
        ("fed_funds",fetch_fed_funds_rate,lambda r:r.get("date") and all(r.get(k) is not None for k in ["effective","target_upper","target_lower"])),
        ("sofr",fetch_sofr_latest,lambda r:r.get("date") and r.get("rate") is not None),
        ("treasury",fetch_treasury_yields,lambda r:r.get("date") and r.get("10 Yr") is not None),
        ("fedwatch",fetch_fedwatch_probabilities,lambda r:bool(r)),
        ("hkd_forwards",fetch_hkd_forward_rates,lambda r:bool(r) and all(v.get("forward_points") is not None for v in r)),
        ("esaver",fetch_esaver_current,lambda r:r.get("id") and r.get("rates")),
    ]
    # Fetch each bank independently; no HSBC substitution for Hang Seng.
    data["prime_rates"]=[]
    for bank,fn in [("HSBC",fetch_hsbc_prime),("HASE",fetch_hase_prime),("DBS",fetch_dbs_prime)]:
        value=_checked("prime_"+bank,fn,lambda r:r.get("rate") is not None)
        if value:
            data["prime_rates"].append(value)
    for source,fn,valid in jobs:
        logger.info("Fetching %s",source)
        value=_checked(source,fn,valid)
        data[source]=value if value is not None else ([] if source in ["fedwatch","hkd_forwards"] else {})
    return data


def store_data(data):
    today=datetime.now().date().isoformat()
    if not data.get("hkd_forwards") and load_health().get("hkd_forwards",{}).get("ok") is False:
        data["hkd_forwards"]=last_valid_forwards(read_json(SNAPSHOT_FILE))
    if data.get("hibor"):
        upsert_row("hibor_daily",data["hibor"])
    if data.get("prime_rates"):
        upsert_row("prime_rates",{"date":today,**{p["bank"]:p["rate"] for p in data["prime_rates"]}})
    ib=data.get("ib_rates") or {}
    if ib:
        upsert_row("ib_rates",{"date":today,"hkd_rate":ib["HKD"]["rate"],"usd_rate":ib["USD"]["rate"],
                               "hkd_tiers":json.dumps(ib["HKD"]["tiers"],separators=(",",":")),
                               "usd_tiers":json.dumps(ib["USD"]["tiers"],separators=(",",":"))})
    fed=data.get("fed_funds") or {}
    if fed:
        upsert_row("fed_rates",{"date":fed["date"],"rate":fed["effective"],"target_upper":fed["target_upper"],"target_lower":fed["target_lower"]})
    sofr=data.get("sofr") or {}
    if sofr:
        upsert_row("sofr",{"date":sofr["date"],"rate":sofr["rate"]})
    if data.get("treasury"):
        upsert_row("treasury_yields",data["treasury"])
    if data.get("esaver"):
        store_promotion(data["esaver"])
    loans=calculate_loans(data,today)
    data["loans"]=loans
    if loans:
        row={"date":today}
        for key,loan in loans.items():
            row[key]=loan["rate"]
            row[key+"_source_date"]=loan["source_date"]
            row[key+"_base_rate"]=loan["base_rate"]
        upsert_row("loan_rates",row)
    # Old aggregate health key cannot override individual bank checks.
    health=load_health()
    health.pop("prime_rates",None)
    write_json(DATA_DIR/"fetch_health.json",health)
    data["updated_at"]=datetime.now().astimezone().isoformat()
    write_json(SNAPSHOT_FILE,data)


def notify_health(sender):
    state_path=DATA_DIR/"alert_notifications.json"
    old=read_json(state_path)
    health=load_health()
    signature={k:(v.get("error") or "fetch failure") for k,v in health.items() if v.get("ok") is False}
    # Recovery is also a meaningful change, with the verified outcome.
    if signature == old.get("failures",{}):
        return True
    lines=["⚠️ <b>利率監察有資料未更新</b>" if signature else "✅ <b>利率監察資料已恢復</b>"]
    for source in signature:
        labels={"esaver":"DBS eSaver","fedwatch":"美國議息機率","hkd_forwards":"港元遠期匯價","hibor":"銀行同業拆息","prime_HASE":"恒生最優惠利率","prime_HSBC":"滙豐最優惠利率","prime_DBS":"星展最優惠利率","ib_rates":"盈透證券融資","fed_funds":"美國聯邦基金利率","sofr":"美元有抵押隔夜融資利率","treasury":"美國國債收益率","telegram":"Telegram 通知"}
        lines.append("⚠️ "+labels.get(source,source)+"："+html.escape(health[source].get("repair") or signature[source]))
    if not signature:
        lines.append("🔧 已重新取得及驗證原有來源")
    lines.append(f'<a href="{APP_URL}">🔗</a>')
    if not sender("\n".join(lines)):
        return False
    write_json(state_path,{"failures":signature})
    return True


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--build-only",action="store_true",help="Rebuild the web app without HTTP calls or notifications")
    parser.add_argument("--no-notify",action="store_true",help="Collect real data without Telegram sends")
    parser.add_argument("--weekly",action="store_true",help="Legacy flag, no longer sends HTML reports")
    args=parser.parse_args(argv)
    try:
        with file_lock(DATA_DIR/"monitor.lock"):
            if args.build_only:
                consume_inbox()
                build_dashboard()
                return 0
            data=fetch_all()
            store_data(data)
            consume_inbox()
            ok=True
            if not args.no_notify:
                ok=notify_changes(data["loans"],send_message)
                ok=notify_margin_changes(data.get("ib_rates") or {},send_message) and ok
                ok=notify_new_promotions(send_message) and ok
                ok=notify_health(send_message) and ok
            data["delivery_ok"]=ok
            data["repair_events"]=list(dict.fromkeys(RECOVERY_EVENTS))
            write_json(SNAPSHOT_FILE,data)
            build_dashboard()
            failures=[k for k,v in load_health().items() if v.get("ok") is False]
            logger.info("Web app updated. Unavailable sources: %s",failures)
            return 1 if failures or not ok else 0
    except LockBusyError:
        logger.warning("Another monitor instance owns the lock; original inbox preserved")
        return 0
    except OSError as exc:
        logger.exception("Monitor could not acquire lock or write files; original data preserved: %s",exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
