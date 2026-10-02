"""Publish only safe display data and static assets through the existing hub."""
import os
from datetime import datetime
import math
from pathlib import Path
import pandas as pd
from src.config import DATA_DIR, REPORTS_DIR, PROJECT_ROOT
from src.esaver import PROMOTIONS_FILE, REGISTRATIONS_FILE
from src.health import load_health
from src.loans import TERMS
from src.state import read_json, write_json, RECOVERY_EVENTS
from src.storage import load_csv

APP_DIR = REPORTS_DIR / "app"
SNAPSHOT_FILE = DATA_DIR / "rates_latest.json"
SERIES = [
    ("hibor_1m", "1 個月銀行同業拆息", "hibor_daily", "1 Month", "hkd", "hibor"),
    ("hibor_on", "隔夜銀行同業拆息", "hibor_daily", "Overnight", "hkd", "hibor"),
    ("hibor_3m", "3 個月銀行同業拆息", "hibor_daily", "3 Months", "hkd", "hibor"),
    ("hibor_12m", "12 個月銀行同業拆息", "hibor_daily", "12 Months", "hkd", "hibor"),
    ("hase_prime", "恒生最優惠利率", "prime_rates", "HASE", "hkd", "prime_HASE"),
    ("hsbc_prime", "滙豐最優惠利率", "prime_rates", "HSBC", "hkd", "prime_HSBC"),
    ("dbs_prime", "星展最優惠利率", "prime_rates", "DBS", "hkd", "prime_DBS"),
    ("ib_hkd", "IB 港元孖展借款（首級）", "ib_rates", "hkd_rate", "hkd", "ib_rates"),
    ("fed", "美國聯邦基金有效利率", "fed_rates", "rate", "usd", "fed_funds"),
    ("sofr", "美元有抵押隔夜融資利率", "sofr", "rate", "usd", "sofr"),
    ("ib_usd", "IB 美元孖展借款（首級）", "ib_rates", "usd_rate", "usd", "ib_rates"),
    ("ust_2y", "美國國債 2 年", "treasury_yields", "2 Yr", "usd", "treasury"),
    ("ust_10y", "美國國債 10 年", "treasury_yields", "10 Yr", "usd", "treasury"),
]


def _series(name, column):
    df = load_csv(name)
    if df.empty or column not in df:
        return []
    df = df[["date",column]].copy().dropna()
    df[column] = pd.to_numeric(df[column], errors="raise")
    df = df.sort_values("date").drop_duplicates("date", keep="last")
    return [{"date":str(r["date"]), "value":float(r[column])} for _, r in df.tail(1500).iterrows()]


def last_valid_forwards(snapshot):
    """Recover real previously published values without changing their dates.

    Source health remains failed. Only a complete six-tenor record qualifies;
    never synthesize quotes or use a stale record to turn the source green.
    """
    candidates=[snapshot]
    for path in [APP_DIR/"data.json",APP_DIR/"data.json.bak"]:
        if path.exists():
            candidates.append(read_json(path))
    for candidate in candidates:
        records=candidate.get("hkd_forwards",[])
        if len(records)!=6:
            continue
        try:
            dates={r["date"] for r in records}
            if len(dates)!=1 or next(iter(dates))>datetime.now().date().isoformat():
                continue
            datetime.fromisoformat(next(iter(dates)))
            if {r["tenor"] for r in records}!={"1 星期","1 個月","3 個月","6 個月","9 個月","12 個月"}:
                continue
            if not all(math.isfinite(float(r["forward_points"])) for r in records):
                continue
            return records
        except (KeyError,TypeError,ValueError):
            continue
    return []


def build_dashboard():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    health = load_health()
    snapshot = read_json(SNAPSHOT_FILE)
    series = []
    for key, label, csv, col, group, source in SERIES:
        points = _series(csv,col)
        series.append({"id":key,"label":label,"group":group,"points":points,"source":source,
                       "ok": health.get(source,{}).get("ok"), "last_checked":health.get(source,{}).get("last_success")})
    loans = []
    for key, term in TERMS.items():
        points = _series("loan_rates",key)
        current = (snapshot.get("loans") or {}).get(key)
        loans.append({**term,"id":key,"points":points,"current":current,
                      "latest":points[-1] if points else None,"ok":bool(current)})
    archive = read_json(PROMOTIONS_FILE,{"promotions":[]})
    data = {"updated_at":snapshot.get("updated_at"), "built_at":datetime.now().astimezone().isoformat(),
            "loans":loans,"series":series,"health":health,"ib_margin":snapshot.get("ib_rates",{}),"promotions":archive["promotions"],
            "fedwatch":snapshot.get("fedwatch",[]),"hkd_forwards":last_valid_forwards(snapshot) if health.get("hkd_forwards",{}).get("ok") is False else snapshot.get("hkd_forwards",[]),
            "treasury":snapshot.get("treasury",{}),"fed_funds":snapshot.get("fed_funds",{}),
            "delivery_ok":snapshot.get("delivery_ok",True),"repair_events":snapshot.get("repair_events",[]) + RECOVERY_EVENTS}
    write_json(APP_DIR / "data.json",data)
    publish_registrations()
    for asset in (PROJECT_ROOT / "web").iterdir():
        if asset.suffix in (".html",".css",".js",".svg"):
            temp = APP_DIR / (asset.name + ".tmp")
            temp.write_bytes(asset.read_bytes())
            os.replace(temp,APP_DIR/asset.name)
    return APP_DIR


def publish_registrations():
    APP_DIR.mkdir(parents=True,exist_ok=True)
    records=read_json(REGISTRATIONS_FILE,{"members":[],"registrations":{},"version":0,"sync_errors":[]})
    schedule=read_json(PROJECT_ROOT/"logs"/"web_sync_install.json")
    records["sync_mode"]="every_minute" if schedule.get("ok") is True else "daily_only"
    if RECOVERY_EVENTS:
        records["sync_errors"]=list(dict.fromkeys(records.get("sync_errors",[]) + RECOVERY_EVENTS))
        write_json(REGISTRATIONS_FILE,records)
    write_json(APP_DIR / "registrations.json",records)
