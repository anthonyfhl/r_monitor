"""Notify changes to published borrowing tiers, with delivery-confirmed state."""
import html
from decimal import Decimal

from src.config import DATA_DIR
from src.loans import APP_URL
from src.state import read_json, write_json

NOTIFY_FILE = DATA_DIR / "ib_margin_notifications.json"


def notify_margin_changes(rates, sender, state_path=None):
    path = state_path or NOTIFY_FILE
    state = read_json(path)
    changed = []
    for ccy in ["HKD", "USD"]:
        item = rates.get(ccy)
        if not item or not item.get("tiers"):
            continue  # Source failure stays visible in health; do not alert using old quotes.
        current = {"tiers": item["tiers"], "plan": item["plan"]}
        if ccy not in state:
            state[ccy] = current
        elif state[ccy] != current:
            changed.append((ccy, state[ccy], item))
    write_json(path, state)
    if not changed:
        return True
    titles, lines = [], []
    for ccy, old, item in changed:
        label = "港元" if ccy == "HKD" else "美元"
        old_tiers, tiers = old["tiers"], item["tiers"]
        structure = lambda ts: [(t["lower"], t["upper"], t["notes"]) for t in ts]
        same_structure = old["plan"] == item["plan"] and structure(old_tiers) == structure(tiers)
        diffs = [Decimal(str(t["rate"])) - Decimal(str(o["rate"])) for o, t in zip(old_tiers, tiers)]
        uniform = same_structure and len(set(diffs)) == 1 and diffs[0] != 0
        if uniform:
            titles.append(f"{label} {diffs[0]:+.3f} 百分點")
            lines.append(f"💵 {label}首 {tiers[0]['upper']:,.0f}：{old_tiers[0]['rate']:.3f}% → <b>{tiers[0]['rate']:.3f}%</b>；全 {len(tiers)} 級同幅調整")
        elif same_structure and any(diffs):
            affected = [(i, delta) for i, delta in enumerate(diffs) if delta]
            titles.append(f"{label}第 {affected[0][0]+1} 段 {affected[0][1]:+.3f} 百分點" if len(affected)==1 else f"{label} {len(affected)} 段息率有變")
            for i, delta in affected[:2]:
                upper=tiers[i]["upper"]
                amount=f"{tiers[i]['lower']:,.0f}–{upper:,.0f}" if upper is not None else f"超過 {tiers[i]['lower']:,.0f}"
                lines.append(f"💵 {label} {amount}：{old_tiers[i]['rate']:.3f}% → <b>{tiers[i]['rate']:.3f}%</b>（{delta:+.3f} 百分點）")
            if len(affected)>2:
                lines.append(f"📋 其餘 {len(affected)-2} 段更新見網頁")
        else:
            titles.append(f"{label}借款級別／條款更新")
            lines.append(f"💵 {label}首級 <b>{tiers[0]['rate']:.3f}%</b>；分級條款有變，請查看完整利率表")
    lines.append(f"📅 {changed[0][2]['date']}｜專業帳戶方案（{html.escape(changed[0][2]['plan'])}）")
    message = "\n".join(["🔔 <b>盈透證券借款：" + "｜".join(titles) + "</b>", *lines,
                         f'<a href="{APP_URL}#ib-margin">🔗</a>'])
    if not sender(message):
        return False
    for ccy, old, item in changed:
        state[ccy] = {"tiers": item["tiers"], "plan": item["plan"]}
    write_json(path, state)
    return True
