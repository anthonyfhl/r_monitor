"""Discover the existing-customer offer in DBS's published page data.

DBS embeds the existing-customer HTML in __NEXT_DATA__ even when the server
renders only the new-customer tab. Never guess a PDF URL or parse a spinner.
"""
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup
from src import http_client

PAGE_URL = "https://www.dbs.com.hk/personal/promotion/esaver"
MONTHS = "January February March April May June July August September October November December".split()
DATE_PATTERN = r"\d{1,2}\s+(?:" + "|".join(MONTHS) + r")\s+\d{4}"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _dates(text):
    return [datetime.strptime(x, "%d %B %Y").date().isoformat() for x in re.findall(DATE_PATTERN, text, re.I)]


def parse_esaver_page(html):
    page = BeautifulSoup(html, "lxml")
    script = page.find("script", id="__NEXT_DATA__")
    candidates = list(_strings(json.loads(script.string))) if script else [html]
    offers = []
    for content in candidates:
        if "hk-esaver-etb-" not in content or "Benchmark Date" not in content:
            continue
        soup = BeautifulSoup(content, "lxml")
        link = next((a["href"] for a in soup.find_all("a", href=True) if re.search(r"hk-esaver-etb-\d{4}-tnc", a["href"])), None)
        if not link:
            continue
        yy, mm = re.search(r"etb-(\d{2})(\d{2})-tnc", link).groups()
        offer = {"id": f"20{yy}-{mm}", "promo_month": f"20{yy}-{mm}", "source_url": link,
                 "page_url": PAGE_URL, "source_kind": "official", "rates": {}, "tiers": []}
        for table in soup.find_all("table"):
            headers = table.get_text(" ", strip=True).lower()
            if "eligible new funds" in headers and "total savings" in headers:
                for row in table.find_all("tr"):
                    cells = [c.get_text(" ",strip=True) for c in row.find_all("td")]
                    if len(cells) < 4:
                        continue
                    amounts = re.findall(r"(?:HK|US)\$(\d[\d,]*)", cells[0])
                    pcts = [re.search(r"(\d+(?:\.\d+)?)\s*%", c) for c in cells[1:4]]
                    if len(amounts) < 2 or not all(pcts):
                        raise ValueError("DBS eSaver: incomplete published rate tier")
                    currency = "HKD" if "HK$" in cells[0] else "USD"
                    tier = {"currency": currency, "min": int(amounts[0].replace(",", "")), "max": int(amounts[1].replace(",", "")),
                            "bonus_rate": float(pcts[0].group(1)), "basic_rate": float(pcts[1].group(1)), "total_rate": float(pcts[2].group(1))}
                    if abs(tier["bonus_rate"] + tier["basic_rate"] - tier["total_rate"]) > 0.005:
                        raise ValueError("DBS eSaver: published rates do not reconcile")
                    offer["tiers"].append(tier)
            if "benchmark date" in headers and "reward" in headers:
                rows = table.find_all("tr")
                cells = [c.get_text(" ",strip=True) for c in rows[-1].find_all("td")]
                if len(cells) >= 4:
                    offer["benchmark_date"] = _dates(cells[0])[0]
                    offer["reg_end"] = _dates(cells[1])[-1]
                    offer["reward_start"], offer["reward_end"] = _dates(cells[2])[:2]
                    offer["credit_date"] = _dates(cells[3])[-1]
        for key, currency, amount in [("hkd_200k", "HKD", 200000), ("hkd_1m", "HKD", 1000000), ("hkd_5m", "HKD", 5000000), ("usd_25k", "USD", 25000)]:
            tier = next((t for t in offer["tiers"] if t["currency"] == currency and t["min"] <= amount <= t["max"]), None)
            offer["rates"][key] = tier["total_rate"] if tier else None
        text = soup.get_text(" ", strip=True)
        footnote = next((p.get_text(" ", strip=True) for p in soup.find_all("p") if "previously registered" in p.get_text().lower()), "")
        offer["exclusion_text"] = footnote
        offer["excluded_months"] = [f"{y}-{MONTHS.index(m.capitalize()) + 1:02d}" for m, y in re.findall(r"(" + "|".join(MONTHS) + r")\s+(20\d{2})", footnote,re.I)]
        offer["registration_closed_early"] = any("registration period is ended" in p.get_text().lower() and not re.search(r"display\s*:\s*none",p.get("style", ""),re.I) and not p.has_attr("hidden") for p in soup.find_all("p"))
        required = ["benchmark_date", "reg_end", "reward_start", "reward_end", "credit_date"]
        if any(not offer.get(k) for k in required) or any(v is None for v in offer["rates"].values()):
            raise ValueError("DBS eSaver: required dates or rates missing; original record preserved")
        if not offer["benchmark_date"] <= offer["reward_start"] <= offer["reward_end"] or offer["reg_end"] > offer["reward_end"]:
            raise ValueError("DBS eSaver: inconsistent date order")
        offer["days"] = (datetime.fromisoformat(offer["reward_end"]) - datetime.fromisoformat(offer["reward_start"])).days + 1
        offers.append(offer)
    if not offers:
        raise ValueError("DBS eSaver: existing-customer offer missing; no substitute from new-customer promotion")
    return max(offers, key=lambda x: x["reward_start"])


def fetch_esaver_current():
    response = http_client.get(PAGE_URL, headers={"Accept": "text/html"})
    return parse_esaver_page(response.content.decode("utf-8"))
