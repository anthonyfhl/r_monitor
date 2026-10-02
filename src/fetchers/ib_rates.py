"""Published IBKR Pro borrowing rates, including every HKD and USD tier."""
import logging
import re
from datetime import datetime
from decimal import Decimal

from bs4 import BeautifulSoup
from src import http_client as requests
from src.config import REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)
SCRAPE_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9"}
IB_RATES_URL = "https://www.interactivebrokers.com/en/trading/margin-rates.php"


def _tier_bounds(text):
    text = " ".join(text.split()).replace(",", "")
    bounded = re.fullmatch(r"(\d+)\s*≤\s*(\d+)", text)
    unlimited = re.fullmatch(r">\s*(\d+)", text)
    if bounded:
        return int(bounded[1]), int(bounded[2])
    if unlimited:
        return int(unlimited[1]), None
    raise ValueError(f"Unrecognised IB borrowing tier: {text}")


def parse_ib_margin_rates(page, observed_on=None):
    """Read total Pro rates (never Lite or just the benchmark spread).

    Continuation rows leave the currency cell blank. Bounds must cover the
    whole balance without gaps; incomplete tables fail before publication.
    """
    soup = BeautifulSoup(page, "lxml")
    tables = [t for t in soup.find_all("table")
              if any("Currency" in h.get_text() for h in t.find_all("th"))
              and any("Rate Charged: IBKR Pro" in h.get_text() for h in t.find_all("th"))]
    if len(tables) != 1:
        raise ValueError("IB borrowing rate table missing or ambiguous")
    headers = [h.get_text(" ", strip=True) for h in tables[0].find_all("th")]
    currency_col = next(i for i, h in enumerate(headers) if h == "Currency")
    tier_col = next(i for i, h in enumerate(headers) if h == "Tier")
    pro_col = next(i for i, h in enumerate(headers) if "Rate Charged: IBKR Pro" in h)
    result = {ccy: {"currency": ccy, "plan": "IBKR Pro", "date": observed_on or datetime.now().date().isoformat(),
                    "source_url": IB_RATES_URL, "tiers": []} for ccy in ["HKD", "USD"]}
    currency = None
    for row in tables[0].find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if not cells:
            continue
        if len(cells) <= max(currency_col, tier_col, pro_col):
            raise ValueError("IB borrowing table has an incomplete row")
        currency = cells[currency_col].get_text(strip=True) or currency
        if currency not in result:
            continue
        tier_text = cells[tier_col].get_text(" ", strip=True)
        lower, upper = _tier_bounds(tier_text)
        text = cells[pro_col].get_text(" ", strip=True)
        quote = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%\s*\(\s*BM\s*\+\s*(\d+(?:\.\d+)?)\s*%\s*\)\s*[\d,\s]*", text)
        if not quote:
            raise ValueError(f"IB {currency} Pro total rate/spread missing")
        rate, spread = Decimal(quote[1]), Decimal(quote[2])
        if not 0 <= spread <= rate <= 30:
            raise ValueError(f"IB {currency} Pro rate outside valid range")
        notes = sorted(set(int(n) for sup in cells[pro_col].find_all("sup") for n in re.findall(r"\d+", sup.get_text())))
        result[currency]["tiers"].append({"lower": lower, "upper": upper, "rate": float(rate),
                                          "spread": float(spread), "notes": notes})
    for ccy, item in result.items():
        tiers = item["tiers"]
        if len(tiers) < 2 or tiers[0]["lower"] != 0 or tiers[-1]["upper"] is not None:
            raise ValueError(f"IB {ccy} tier coverage incomplete")
        for i, tier in enumerate(tiers):
            if tier["upper"] is not None and tier["upper"] <= tier["lower"]:
                raise ValueError(f"IB {ccy} tier has invalid bounds")
            if i and tiers[i-1]["upper"] != tier["lower"]:
                raise ValueError(f"IB {ccy} tiers overlap or leave a gap")
        benchmarks = [Decimal(str(t["rate"])) - Decimal(str(t["spread"])) for t in tiers]
        if max(benchmarks) - min(benchmarks) > Decimal("0.001"):
            raise ValueError(f"IB {ccy} Pro tiers disagree on the benchmark")
        item["rate"] = tiers[0]["rate"]  # Preserve the existing historical series.
        item["benchmark_rate"] = float(benchmarks[0])
    return result


def fetch_ib_margin_rates():
    response = requests.get(IB_RATES_URL, headers=SCRAPE_HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    result = parse_ib_margin_rates(response.text)
    logger.info("IBKR Pro borrowing rates: HKD %s%%, USD %s%%; all tiers verified", result["HKD"]["rate"], result["USD"]["rate"])
    return result
