"""Read each bank's own HKD prime rate; never substitute another bank."""
import re
from datetime import date
from bs4 import BeautifulSoup
from src import http_client as requests
from src.config import REQUEST_TIMEOUT, USER_AGENT

SCRAPE_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
HSBC_PRIME_URL = "https://www.hsbc.com.hk/investments/market-information/hk/lending-rate/"
DBS_PRIME_URL = "https://www.dbs.com.hk/personal/loans/home-loans/home-advice/interestrate.html"
HASE_PRIME_URL = "https://rbwm-api.hsbc.com.hk/pws-hk-hase-rates-papi-prod-proxy/v1/hkd-prime-rates"


def parse_hsbc_prime(html):
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    match = re.search(r"Hong Kong Dollar\s+Best Lending Rate\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if not match:
        raise ValueError("HSBC: labelled HKD best lending rate missing")
    rate = float(match.group(1))
    if not 0 < rate < 20:
        raise ValueError("HSBC: prime rate outside valid range")
    return {"bank": "HSBC", "rate": rate, "date": date.today().isoformat()}


def fetch_hsbc_prime():
    return parse_hsbc_prime(requests.get(HSBC_PRIME_URL, headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT).text)


def parse_hase_prime(data):
    rate = float(data["rate"])
    observed = data["lastUpdateTime"][:10]
    date.fromisoformat(observed)
    if not 0 < rate < 20:
        raise ValueError("Hang Seng: prime rate outside valid range")
    return {"bank": "HASE", "rate": rate, "date": observed,
            "effective_date": data["lastChanges"][0]["effectiveDate"][:10] if data.get("lastChanges") else None}


def fetch_hase_prime():
    return parse_hase_prime(requests.get(HASE_PRIME_URL, timeout=REQUEST_TIMEOUT).json())


def fetch_dbs_prime():
    soup = BeautifulSoup(requests.get(DBS_PRIME_URL, headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT).text, "lxml")
    for table in soup.find_all("table"):
        if "prime" not in table.get_text().lower():
            continue
        for row in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 2:
                continue
            try:
                rate = float(cells[1])
            except ValueError:
                continue
            if 0 < rate < 20:
                return {"bank": "DBS", "rate": rate, "date": date.today().isoformat()}
    raise ValueError("DBS: labelled prime-rate table missing")


def fetch_all_prime_rates():
    return [fn() for fn in (fetch_hsbc_prime, fetch_hase_prime, fetch_dbs_prime)]
