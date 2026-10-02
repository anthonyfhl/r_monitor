import json
from datetime import date
from pathlib import Path

import pytest
import requests

from src import http_client, loans, esaver, storage, health
from src.fetchers.banks import parse_hase_prime, parse_hsbc_prime
from src.fetchers.dbs_esaver import parse_esaver_page
from src.state import read_json, write_json


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    from src.state import RECOVERY_EVENTS
    RECOVERY_EVENTS.clear()
    monkeypatch.setattr(http_client,"STATE_FILE",tmp_path/"guard.json")
    monkeypatch.setattr(http_client,"LOCK_FILE",tmp_path/"guard.lock")
    monkeypatch.setattr(http_client,"_run_calls",0)
    monkeypatch.setattr(http_client,"MIN_INTERVAL",0)
    monkeypatch.setattr(http_client.time,"sleep",lambda _:None)
    monkeypatch.setattr(storage,"DATA_DIR",tmp_path)
    monkeypatch.setattr(health,"HEALTH_FILE",tmp_path/"health.json")
    monkeypatch.setattr(esaver,"DATA_DIR",tmp_path)
    for name in ["PROMOTIONS_FILE","REGISTRATIONS_FILE","NOTIFICATIONS_FILE","CURSOR_FILE"]:
        monkeypatch.setattr(esaver,name,tmp_path/(name.lower()+".json"))
    write_json(esaver.REGISTRATIONS_FILE,{"members":["Mum","Fong","Pik"],"registrations":{},"version":0})
    return tmp_path


def response(code,body="",headers=None):
    r=requests.Response();r.status_code=code;r._content=body.encode();r.headers.update(headers or {"Content-Type":"text/plain"});return r


@pytest.mark.parametrize("code",[401,403,429,409])
def test_refusal_stops_all_account_calls_and_repeat_lengthens(isolated,monkeypatch,code):
    now=[1000000.0];monkeypatch.setattr(http_client.time,"time",lambda:now[0])
    calls=[]
    def send(*args,**kwargs):calls.append(args);return response(code,headers={"Retry-After":"90000"})
    monkeypatch.setattr(http_client.transport,"request",send)
    with pytest.raises(http_client.RefusalError):http_client.get("https://api.example.test/one")
    first=read_json(http_client.STATE_FILE)["api.example.test"]["blocked_until"]
    for path in ["one","two","other-process"]:
        with pytest.raises(http_client.RefusalError):http_client.get("https://api.example.test/"+path)
    assert len(calls)==1
    now[0]=first+1
    with pytest.raises(http_client.RefusalError):http_client.get("https://api.example.test/verify")
    second=read_json(http_client.STATE_FILE)["api.example.test"]["blocked_until"]
    assert second-now[0]>first-1000000
    with pytest.raises(http_client.RefusalError):http_client.get("https://api.example.test/another")
    assert len(calls)==2


@pytest.mark.parametrize("body",["Too many requests", "cf-chl-mismatch", "Verify you are human", "Account is suspended"])
def test_challenge_in_200_is_refusal(isolated,monkeypatch,body):
    calls=[]
    monkeypatch.setattr(http_client.transport,"request",lambda *a,**k:(calls.append(a) or response(200,body)))
    with pytest.raises(http_client.RefusalError):http_client.get("https://example.test/")
    with pytest.raises(http_client.RefusalError):http_client.get("https://example.test/")
    assert len(calls)==1


@pytest.mark.parametrize("code",[400,404,422])
def test_bad_request_not_retried(isolated,monkeypatch,code):
    calls=[]
    monkeypatch.setattr(http_client.transport,"request",lambda *a,**k:(calls.append(a) or response(code)))
    with pytest.raises(http_client.GuardError):http_client.get("https://example.test/")
    assert len(calls)==1


def test_network_fault_repair_is_bounded(isolated,monkeypatch):
    calls=[]
    def send(*a,**k):calls.append(a);raise requests.Timeout("secret-bearing URL")
    monkeypatch.setattr(http_client.transport,"request",send)
    with pytest.raises(http_client.GuardError,match="bounded") as err:http_client.get("https://example.test/")
    assert "secret" not in str(err.value)
    assert len(calls)==2


def test_post_no_ambiguous_retry(isolated,monkeypatch):
    calls=[]
    monkeypatch.setattr(http_client.transport,"request",lambda *a,**k:(calls.append(a) or response(503)))
    with pytest.raises(http_client.GuardError):http_client.post("https://example.test/")
    assert len(calls)==1


def test_client_safety_cap_fails_before_call(isolated,monkeypatch):
    monkeypatch.setattr(http_client,"_run_calls",http_client.PER_RUN_CAP)
    monkeypatch.setattr(http_client.transport,"request",lambda *a,**k:pytest.fail("must not call transport"))
    with pytest.raises(http_client.GuardError,match="budget"):http_client.get("https://example.test/")


@pytest.mark.parametrize("header",["invalid date", "NaN", "Infinity"])
def test_bad_refusal_header_cannot_disable_cooldown(isolated,monkeypatch,header):
    calls=[]
    monkeypatch.setattr(http_client.transport,"request",lambda *a,**k:(calls.append(a) or response(429,headers={"Retry-After":header})))
    with pytest.raises(http_client.RefusalError):http_client.get("https://example.test/")
    with pytest.raises(http_client.RefusalError):http_client.get("https://example.test/")
    assert len(calls)==1


def test_loan_formulas_and_no_bank_substitution():
    data={"hibor":{"date":"2026-10-02","1 Month":2.96839},"prime_rates":[{"bank":"HASE","rate":5,"date":"2026-10-02"}]}
    result=loans.calculate_loans(data,"2026-10-02")
    assert result["hsbc_wpl"]["rate"]==3.46839
    assert result["hase_al"]["rate"]==3.25
    data["prime_rates"]=[{"bank":"HSBC","rate":5,"date":"2026-10-02"}]
    assert "hase_al" not in loans.calculate_loans(data,"2026-10-02")
    data["hibor"]["date"]="2026-09-01"
    assert not loans.calculate_loans(data,"2026-10-02")


def test_change_notifications_only_advance_after_ack(isolated):
    state=isolated/"notify.json";sent=[]
    loan={"hsbc_wpl":{"rate":3.46839,"name":"滙豐","formula":"1 個月 HIBOR + 0.5%","source_date":"2026-10-02"}}
    assert loans.notify_changes(loan,lambda t:sent.append(t) or True,state)
    assert not sent
    loan["hsbc_wpl"]["rate"]=3.5
    assert not loans.notify_changes(loan,lambda t:False,state)
    assert read_json(state)["hsbc_wpl"]["rate"]==3.46839
    assert loans.notify_changes(loan,lambda t:sent.append(t) or True,state)
    assert len(sent)==1
    assert "+0.03161 百分點" in sent[0]
    assert loans.notify_changes(loan,lambda t:pytest.fail("duplicate notification"),state)


def test_bank_parsers_currency_and_provenance():
    hase=parse_hase_prime({"rate":"5.000","lastUpdateTime":"2026-10-02T12:00:00+08:00","lastChanges":[{"effectiveDate":"2025-10-31T00:00:00+08:00"}]})
    assert hase=={"bank":"HASE","rate":5,"date":"2026-10-02","effective_date":"2025-10-31"}
    assert parse_hsbc_prime("<h2>Hong Kong Dollar Best Lending Rate: 5.00%</h2>")["rate"]==5
    with pytest.raises(ValueError):parse_hsbc_prime("US Dollar Best Lending Rate: 6.75%")


def test_esaver_real_published_page_not_new_customer():
    offer=parse_esaver_page((Path(__file__).parent/"fixtures"/"esaver_page.html").read_text(encoding="utf-8"))
    assert offer["id"]=="2026-09"
    assert offer["reward_start"]=="2026-09-07"
    assert offer["reward_end"]=="2027-01-08"
    assert offer["reg_end"]=="2026-09-30"
    assert offer["days"]==124
    assert offer["rates"]=={"hkd_200k":3.026,"hkd_1m":3.026,"hkd_5m":3.15,"usd_25k":4.1}
    assert offer["excluded_months"]==["2026-08"]
    assert offer["credit_date"]=="2027-03-31"


def test_esaver_spinner_never_success():
    with pytest.raises(ValueError):parse_esaver_page("<title>Spinner App</title>Loading")


def test_new_period_notification_pending_until_ack(isolated):
    offer=parse_esaver_page((Path(__file__).parent/"fixtures"/"esaver_page.html").read_text(encoding="utf-8"))
    write_json(esaver.NOTIFICATIONS_FILE,{"seen":["2026-08"]})
    esaver.store_promotion(offer)
    assert not esaver.notify_new_promotions(lambda _:False)
    assert "2026-09" not in read_json(esaver.NOTIFICATIONS_FILE)["seen"]
    sent=[]
    assert esaver.notify_new_promotions(lambda t:sent.append(t) or True)
    assert len(sent)==1 and "3.026%" in sent[0]
    assert esaver.notify_new_promotions(lambda _:pytest.fail("duplicate"))


def test_new_promotion_gap_uses_latest_nonexcluded_period(isolated):
    write_json(esaver.PROMOTIONS_FILE,{"promotions":[
        {"id":"2026-07","reward_start":"2026-07-06","reward_end":"2026-09-07"},
        {"id":"2026-08","reward_start":"2026-08-05","reward_end":"2026-11-06"}]})
    esaver.store_promotion({"id":"2026-09","reward_start":"2026-09-07","reward_end":"2027-01-08","excluded_months":["2026-08"]})
    offer=read_json(esaver.PROMOTIONS_FILE)["promotions"][-1]
    assert offer["previous_valid_end"]=="2026-09-07"
    assert offer["gap_days"]==0


def test_inbox_persists_replays_and_handles_partial_append(isolated):
    write_json(esaver.PROMOTIONS_FILE,{"promotions":[{"id":"2026-09"}]})
    inbox=isolated/"inbox.jsonl"
    event={"utc":"2026-10-02T00:00:00Z","email":"owner@example.com","kind":"esaver_registration","payload":{"event_id":"event-12345","promo_id":"2026-09","member":"Mum","status":"registered","registered_on":None}}
    line=json.dumps(event).encode()+b"\n";inbox.write_bytes(line+line+b'{"utc":')
    records=esaver.consume_inbox(inbox)
    assert records["version"]==1
    assert records["registrations"]["2026-09|Mum"]["status"]=="registered"
    assert read_json(esaver.CURSOR_FILE)["offset"]==len(line)*2
    assert esaver.consume_inbox(inbox)["version"]==1


def test_bad_registration_preserved_and_warned(isolated):
    write_json(esaver.PROMOTIONS_FILE,{"promotions":[]})
    inbox=isolated/"inbox.jsonl";inbox.write_bytes(b'{"kind":"unknown"}\n')
    records=esaver.consume_inbox(inbox)
    assert records["sync_errors"]
    assert (isolated/"quarantine"/"invalid_registration_events.jsonl").read_bytes()==inbox.read_bytes()


def test_truncated_inbox_repairs_cursor_preserves_records(isolated):
    write_json(esaver.PROMOTIONS_FILE,{"promotions":[]})
    write_json(esaver.REGISTRATIONS_FILE,{"members":["Mum"],"registrations":{"2026-02|Mum":{"status":"registered"}},"version":1})
    write_json(esaver.CURSOR_FILE,{"offset":1000,"event_ids":["event-12345"]})
    inbox=isolated/"inbox.jsonl";inbox.write_bytes(b"")
    records=esaver.consume_inbox(inbox)
    assert records["registrations"]["2026-02|Mum"]["status"]=="registered"
    assert records["sync_errors"]
    assert read_json(esaver.CURSOR_FILE)["offset"]==0
    assert len(list((isolated/"quarantine").glob("inbox_cursor_*.json")))==1


def test_record_write_cursor_crash_replay_is_idempotent(isolated,monkeypatch):
    write_json(esaver.PROMOTIONS_FILE,{"promotions":[{"id":"2026-09"}]})
    event={"utc":"2026-10-02T00:00:00Z","kind":"esaver_registration","payload":{"event_id":"event-12345","promo_id":"2026-09","member":"Mum","status":"registered"}}
    inbox=isolated/"inbox.jsonl";inbox.write_text(json.dumps(event)+"\n",encoding="utf-8")
    original_write=esaver.write_json
    def crash_on_cursor(path,value):
        if path==esaver.CURSOR_FILE:raise OSError("simulated interrupted cursor write")
        original_write(path,value)
    monkeypatch.setattr(esaver,"write_json",crash_on_cursor)
    with pytest.raises(OSError):esaver.consume_inbox(inbox)
    monkeypatch.setattr(esaver,"write_json",original_write)
    assert esaver.consume_inbox(inbox)["version"]==1


def test_lock_conflict_releases_after_owner_closes(isolated):
    from src.state import file_lock, LockBusyError
    path=isolated/"monitor.lock"
    with file_lock(path):
        with pytest.raises(LockBusyError):
            with file_lock(path):pytest.fail("second process lock must not succeed")
    with file_lock(path):pass


def test_corrupt_csv_fails_without_overwrite(isolated):
    source=isolated/"rates.csv";source.write_text('date,rate\n"unterminated',encoding="utf-8")
    original=source.read_bytes()
    with pytest.raises(RuntimeError):storage.upsert_row("rates",{"date":"2026-10-02","rate":1})
    assert source.read_bytes()==original


def test_json_corruption_restores_verified_backup_keeps_original(isolated):
    path=isolated/"family.json"
    write_json(path,{"members":["Mum"]})
    write_json(path,{"members":["Mum","Fong"]})
    path.write_text('{"members":',encoding="utf-8")
    assert read_json(path)=={"members":["Mum"]}
    assert len(list((isolated/"quarantine").glob("family.json.*.broken")))==1


def test_guard_corruption_never_rolls_back_cooldown(isolated):
    write_json(http_client.STATE_FILE,{"blocked_until":100})
    write_json(http_client.STATE_FILE,{"blocked_until":200})
    http_client.STATE_FILE.write_text('{',encoding="utf-8")
    # Isolated test file has a generic name; production prefix is deliberately protected.
    path=isolated/"http_guard.json"
    path.write_text('{',encoding="utf-8")
    path.with_name(path.name+".bak").write_text('{"blocked_until":100}',encoding="utf-8")
    with pytest.raises(RuntimeError,match="cannot roll back"):read_json(path)
    assert path.read_text()=="{"


def test_csv_corruption_restores_real_history_and_quarantines(isolated):
    storage.upsert_row("rates",{"date":"2026-10-01","rate":5})
    storage.upsert_row("rates",{"date":"2026-10-02","rate":4.5})
    source=isolated/"rates.csv";source.write_text('date,rate\n"unterminated',encoding="utf-8")
    restored=storage.load_csv("rates")
    assert restored.to_dict("records")==[{"date":"2026-10-01","rate":5}]
    assert len(list((isolated/"quarantine").glob("rates.csv.*.broken")))==1


def test_upsert_refreshes_today_preserves_history(isolated):
    storage.upsert_row("prime_rates",{"date":"2026-10-01","HSBC":5})
    storage.upsert_row("prime_rates",{"date":"2026-10-02","HSBC":5})
    storage.upsert_row("prime_rates",{"date":"2026-10-02","HASE":5})
    df=storage.load_csv("prime_rates")
    assert len(df)==2 and df.iloc[-1]["HASE"]==5 and df.iloc[-1]["HSBC"]==5


def test_all_fetchers_use_guarded_send():
    for p in (Path(__file__).resolve().parents[1]/"src"/"fetchers").glob("*.py"):
        text=p.read_text(encoding="utf-8")
        assert "import requests\n" not in text
        assert "from requests" not in text


def test_retired_reports_cannot_be_sent():
    text=(Path(__file__).resolve().parents[1]/"main.py").read_text(encoding="utf-8")
    assert "send_document" not in text and "generate_report" not in text


def test_plain_telegram_message_omits_null_parse_mode(isolated,monkeypatch):
    from src import telegram_sender
    monkeypatch.setattr(telegram_sender,"TELEGRAM_BOT_TOKEN","test-token")
    monkeypatch.setattr(telegram_sender,"TELEGRAM_CHAT_ID","123")
    sent=[]
    monkeypatch.setattr(telegram_sender.http_client,"post",lambda *a,**k:(sent.append(k["json"]) or response(200,'{"ok":true}',{"Content-Type":"application/json"})))
    assert telegram_sender.send_message("設定已完成",parse_mode=None)
    assert "parse_mode" not in sent[0]
    assert telegram_sender.send_message("<b>設定已完成</b>")
    assert sent[1]["parse_mode"]=="HTML"


def test_repair_launcher_uses_native_binary_without_second_shell(isolated,monkeypatch):
    from src import repair
    launcher=isolated/"codex.cmd";launcher.write_text("fake wrapper")
    native=isolated/"node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe"
    native.parent.mkdir(parents=True);native.write_bytes(b"test fixture")
    monkeypatch.setattr(repair.shutil,"which",lambda _:str(launcher))
    assert repair._codex_executable()==str(native)


def test_repair_overrides_do_not_create_phantom_quoted_connectors():
    from src.repair import _connector_overrides
    args=_connector_overrides({"mcp_servers":{"node_repl":{}},"plugins":{"browser@openai-bundled":{}}})
    assert args==['-c','mcp_servers.node_repl.enabled=false','-c','plugins.browser@openai-bundled.enabled=false']


def test_missing_web_asset_repaired_from_source_without_bank_calls(isolated,monkeypatch):
    import sync_web
    from src import web_app
    from src.config import PROJECT_ROOT
    app=isolated/"app"
    monkeypatch.setattr(web_app,"APP_DIR",app)
    monkeypatch.setattr(web_app,"SNAPSHOT_FILE",isolated/"snapshot.json")
    monkeypatch.setattr(web_app,"PROMOTIONS_FILE",esaver.PROMOTIONS_FILE)
    monkeypatch.setattr(web_app,"REGISTRATIONS_FILE",esaver.REGISTRATIONS_FILE)
    monkeypatch.setattr(sync_web,"APP_DIR",app)
    monkeypatch.setattr(sync_web,"DATA_DIR",isolated)
    monkeypatch.setattr(sync_web,"consume_inbox",lambda:{"sync_errors":[]})
    monkeypatch.setattr(http_client.transport,"request",lambda *a,**k:pytest.fail("asset recovery must not fetch bank data"))
    assert sync_web.main()==0
    assert (app/"http-guard.js").read_bytes()==(PROJECT_ROOT/"web"/"http-guard.js").read_bytes()
    (app/"http-guard.js").unlink()
    assert sync_web.main()==0
    assert (app/"http-guard.js").read_bytes()==(PROJECT_ROOT/"web"/"http-guard.js").read_bytes()
