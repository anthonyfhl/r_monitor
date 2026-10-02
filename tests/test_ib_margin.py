import copy
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.fetchers.ib_rates import parse_ib_margin_rates
from src.ib_margin import notify_margin_changes
from src.state import read_json


@pytest.fixture
def page():
    return (Path(__file__).parent / "fixtures" / "ib_margin_table.html").read_text(encoding="utf-8")


@pytest.fixture
def rates(page):
    return parse_ib_margin_rates(page, "2026-10-02")


def test_real_table_all_tiers_total_pro_rate_and_special_terms(rates):
    assert len(rates["HKD"]["tiers"]) == 4
    assert len(rates["USD"]["tiers"]) == 5
    assert rates["HKD"]["rate"] == 6.631
    assert rates["USD"]["rate"] == 5.38
    assert rates["HKD"]["benchmark_rate"] == 4.131
    assert rates["USD"]["benchmark_rate"] == 3.88
    assert rates["HKD"]["tiers"][1] == {"lower":780000,"upper":7800000,"rate":6.131,"spread":2.0,"notes":[]}
    assert rates["USD"]["tiers"][3]["notes"] == [1]
    assert rates["USD"]["tiers"][-1]["notes"] == [1,2]


@pytest.mark.parametrize("defect", ["gap", "missing_currency", "wrong_column", "missing_tail", "benchmark_mismatch"])
def test_incomplete_or_wrong_rates_fail_loud(page, defect):
    soup = BeautifulSoup(page,"lxml")
    usd = next(row for row in soup.find_all("tr") if row.find("td") and row.find("td").get_text(strip=True)=="USD")
    if defect == "gap":
        usd.find_next_sibling("tr").decompose()
    elif defect == "missing_currency":
        usd.find("td").string = "EUR"
    elif defect == "wrong_column":
        usd.find_all("td")[2].string = "BM + 1.5%"
    elif defect == "benchmark_mismatch":
        usd.find_all("td")[2].string = "9.380% (BM + 1.5%)"
    else:
        usd.find_next_siblings("tr")[3].decompose()
    with pytest.raises(ValueError):
        parse_ib_margin_rates(str(soup))


def test_high_tier_change_detected_pending_until_delivery_then_quiet(rates, tmp_path):
    state=tmp_path/"notifications.json"
    sent=[]
    assert notify_margin_changes(rates,lambda _:pytest.fail("first observation is a baseline"),state)
    changed=copy.deepcopy(rates)
    changed["HKD"]["tiers"][1]["rate"] += .1
    assert not notify_margin_changes(changed,lambda _:False,state)
    assert read_json(state)["HKD"]["tiers"][1]["rate"] == 6.131
    assert notify_margin_changes(changed,lambda msg:sent.append(msg) or True,state)
    assert len(sent)==1 and "港元第 2 段 +0.100 百分點" in sent[0].splitlines()[0]
    assert "USD" not in sent[0]
    assert notify_margin_changes(changed,lambda _:pytest.fail("duplicate"),state)
    changed["HKD"]["date"]="2026-10-03"
    assert notify_margin_changes(changed,lambda _:pytest.fail("date alone is not a rate change"),state)


def test_uniform_change_title_and_tier_boundary_changes(rates,tmp_path):
    state=tmp_path/"notifications.json";sent=[]
    notify_margin_changes(rates,lambda _:True,state)
    for tier in rates["USD"]["tiers"]:
        tier["rate"]=round(tier["rate"]-.25,3)
    assert notify_margin_changes(rates,lambda msg:sent.append(msg) or True,state)
    assert "美元 -0.250 百分點" in sent[-1].splitlines()[0]
    assert "全 5 級同幅調整" in sent[-1]
    rates["HKD"]["tiers"][0]["upper"]=800000
    rates["HKD"]["tiers"][1]["lower"]=800000
    assert notify_margin_changes(rates,lambda msg:sent.append(msg) or True,state)
    assert "港元借款級別／條款更新" in sent[-1]


def test_store_all_tiers_preserves_original_rate_history(rates,tmp_path,monkeypatch):
    import main
    from src import storage,health
    monkeypatch.setattr(storage,"DATA_DIR",tmp_path)
    monkeypatch.setattr(main,"DATA_DIR",tmp_path)
    monkeypatch.setattr(main,"SNAPSHOT_FILE",tmp_path/"snapshot.json")
    monkeypatch.setattr(health,"HEALTH_FILE",tmp_path/"health.json")
    storage.upsert_row("ib_rates",{"date":"2026-10-01","hkd_rate":6.6,"usd_rate":5.3})
    main.store_data({"ib_rates":rates})
    stored=storage.load_csv("ib_rates")
    assert len(stored)==2
    assert stored.iloc[0]["hkd_rate"]==6.6
    assert json.loads(stored.iloc[1]["hkd_tiers"])==rates["HKD"]["tiers"]
    assert read_json(main.SNAPSHOT_FILE)["ib_rates"]==rates
