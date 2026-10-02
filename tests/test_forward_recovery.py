from src import http_client, web_app
from src.state import write_json


def test_last_valid_forward_record_retains_dates_without_a_network_call(tmp_path,monkeypatch):
    monkeypatch.setattr(web_app,"APP_DIR",tmp_path)
    monkeypatch.setattr(http_client.transport,"request",lambda *a,**k:(_ for _ in ()).throw(AssertionError("cache repair must be offline")))
    records=[{"date":"2026-08-31","tenor":tenor,"forward_points":-12.5} for tenor in ["1 星期","1 個月","3 個月","6 個月","9 個月","12 個月"]]
    write_json(tmp_path/"data.json.bak",{"hkd_forwards":records})
    assert web_app.last_valid_forwards({"hkd_forwards":[]})==records
    records.pop()
    write_json(tmp_path/"data.json.bak",{"hkd_forwards":records})
    assert web_app.last_valid_forwards({"hkd_forwards":[]})==[]


def test_forward_fetch_requests_only_latest_record(monkeypatch):
    from src.fetchers import hkma
    class Response:
        def raise_for_status(self):pass
        def json(self):
            keys=["hkd_fer_1w","hkd_fer_1m","hkd_fer_3m","hkd_fer_6m","hkd_fer_9m","hkd_fer_12m"]
            record={"end_of_day":"2026-08-31",**{key:1 for key in keys}}
            return {"result":{"records":[record]}}
    sent=[]
    monkeypatch.setattr(hkma.requests,"get",lambda *a,**k:(sent.append(k) or Response()))
    assert len(hkma.fetch_hkd_forward_rates())==6
    assert sent[0]["params"]=={"pagesize":1,"sortby":"end_of_day","sortorder":"desc"}
