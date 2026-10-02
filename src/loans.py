"""The operator's agreed spreads; these are not public promotional quotes."""
from decimal import Decimal, InvalidOperation
from datetime import date

from src.config import DATA_DIR
from src.state import read_json, write_json

APP_URL = "https://hub.carelogic.org/app/r_monitor/rates/"
NOTIFY_FILE = DATA_DIR / "loan_notifications.json"
TERMS = {
    "hsbc_wpl": {"name": "滙豐滙財組合貸款", "short": "滙豐 WPL", "formula": "1 個月 HIBOR + 0.5%", "spread": "0.5"},
    "hase_al": {"name": "恒生 Asset Link 抵押透支", "short": "恒生 Asset Link", "formula": "恒生最優惠利率 − 1.75%", "spread": "-1.75"},
}


def number(value):
    try:
        val = Decimal(str(value))
        return val if val.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def calculate_loans(data, today=None):
    today = today or date.today().isoformat()
    result = {}
    hibor = data.get("hibor") or {}
    hase = next((r for r in data.get("prime_rates", []) if r.get("bank") == "HASE"), {})
    for key, value, source_date in [
        ("hsbc_wpl", hibor.get("1 Month"), hibor.get("date")),
        ("hase_al", hase.get("rate"), hase.get("date")),
    ]:
        base = number(value)
        if base is None or not source_date or not 0 <= base <= 20:
            continue
        if (date.fromisoformat(today) - date.fromisoformat(source_date)).days > 7 or source_date > today:
            continue
        term = TERMS[key]
        result[key] = {**term, "id": key, "date": today, "source_date": source_date,
                       "base_rate": float(base), "rate": float((base + Decimal(term["spread"])).quantize(Decimal("0.00001"))),
                       "effective_date": hase.get("effective_date") if key == "hase_al" else None}
    return result


def notify_changes(loans, sender, state_path=None):
    """Compare with last successfully notified values; failures remain pending."""
    path = state_path or NOTIFY_FILE
    state = read_json(path)
    changes = []
    for key, loan in loans.items():
        old = state.get(key)
        if old is None:
            state[key] = {"rate": loan["rate"], "source_date": loan["source_date"]}
        elif number(old["rate"]) != number(loan["rate"]):
            changes.append((key, old, loan))
    # New products establish a baseline without masquerading as a change.
    write_json(path, state)
    if not changes:
        return True
    title="｜".join(f"{'滙豐貸款' if key=='hsbc_wpl' else '恒生抵押透支'} {number(loan['rate'])-number(old['rate']):+.5f} 百分點" for key,old,loan in changes)
    lines = [f"🔔 <b>{title}</b>"]
    for key, old, loan in changes:
        change = number(loan["rate"]) - number(old["rate"])
        icon = "🔺" if change > 0 else "🔻"
        lines.append(f"{icon} {loan['name']}：{old['rate']:.5f}% → <b>{loan['rate']:.5f}%</b>（{change:+.5f} 百分點）")
        lines.append(f"📅 基準日期 {loan['source_date']}｜{loan['formula']}")
    lines.append(f'🌐 <a href="{APP_URL}">查看利率監察</a>')
    if not sender("\n".join(lines)):
        return False
    for key, old, loan in changes:
        state[key] = {"rate": loan["rate"], "source_date": loan["source_date"]}
    write_json(path, state)
    return True
