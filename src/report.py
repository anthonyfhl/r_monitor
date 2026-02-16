"""Generate HTML report for interest rate monitoring."""

import logging
from datetime import datetime

from jinja2 import Template

from src.storage import get_change

logger = logging.getLogger(__name__)

# Inline SVG sparkline generator
def _sparkline_svg(values: list[float], width: int = 80, height: int = 20) -> str:
    """Generate an inline SVG sparkline from a list of values."""
    if not values or len(values) < 2:
        return ""
    min_v = min(values)
    max_v = max(values)
    rng = max_v - min_v if max_v != min_v else 1
    n = len(values)
    points = []
    for i, v in enumerate(values):
        x = (i / (n - 1)) * width
        y = height - ((v - min_v) / rng) * (height - 2) - 1
        points.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(points)
    color = "#22c55e" if values[-1] >= values[0] else "#ef4444"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="vertical-align:middle;display:inline-block">'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="1.5"/>'
        f'<circle cx="{(n-1)/(n-1)*width:.1f}" cy="{height-((values[-1]-min_v)/rng)*(height-2)-1:.1f}" '
        f'r="2" fill="{color}"/>'
        f"</svg>"
    )


def _change_badge(change: float | None) -> str:
    """Format a rate change as a colored badge."""
    if change is None:
        return '<span style="color:#94a3b8">—</span>'
    sign = "+" if change >= 0 else ""
    color = "#ef4444" if change > 0 else "#22c55e" if change < 0 else "#94a3b8"
    arrow = "&#9650;" if change > 0 else "&#9660;" if change < 0 else "&#9644;"
    return f'<span style="color:{color};font-weight:600">{arrow} {sign}{change:.3f}%</span>'


def _fmt_rate(val) -> str:
    """Format a rate value."""
    if val is None:
        return '<span style="color:#94a3b8">N/A</span>'
    try:
        return f"{float(val):.4f}%"
    except (ValueError, TypeError):
        return str(val)


REPORT_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Interest Rate Monitor - {{ report_date }}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
    background: #0f172a; color: #e2e8f0; padding: 16px; font-size: 14px;
    max-width: 900px; margin: 0 auto;
  }
  h1 { font-size: 20px; color: #f8fafc; margin-bottom: 4px; }
  .subtitle { color: #94a3b8; font-size: 12px; margin-bottom: 16px; }
  .section { margin-bottom: 20px; }
  .section-title {
    font-size: 15px; font-weight: 700; color: #38bdf8;
    border-bottom: 1px solid #1e293b; padding-bottom: 6px; margin-bottom: 10px;
  }
  table { width: 100%; border-collapse: collapse; margin-bottom: 8px; }
  th {
    background: #1e293b; color: #94a3b8; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.5px;
    padding: 8px 10px; text-align: left; border-bottom: 1px solid #334155;
  }
  td {
    padding: 7px 10px; border-bottom: 1px solid #1e293b; font-size: 13px;
    white-space: nowrap;
  }
  tr:hover { background: #1e293b; }
  .rate-name { color: #e2e8f0; font-weight: 500; }
  .rate-value { color: #f8fafc; font-weight: 700; font-family: 'SF Mono', 'Fira Code', monospace; }
  .source { color: #64748b; font-size: 11px; }
  .footer { color: #475569; font-size: 11px; margin-top: 16px; text-align: center; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 600px) { .grid-2 { grid-template-columns: 1fr; } }
  .forecast-table td { font-size: 12px; }
  .prob-bar {
    display: inline-block; height: 14px; border-radius: 2px;
    background: #38bdf8; min-width: 2px; vertical-align: middle;
  }
  .highlight { background: #1e3a5f; }
</style>
</head>
<body>

<h1>&#128200; Interest Rate Monitor</h1>
<p class="subtitle">Report generated: {{ report_date }} {{ report_time }} HKT</p>

{# ===== HKD RATES ===== #}
<div class="section">
  <div class="section-title">&#127469;&#127472; HKD Interest Rates</div>
  <table>
    <thead>
      <tr><th>Rate</th><th>Current</th><th>7d Change</th><th>30d Change</th><th>Trend</th></tr>
    </thead>
    <tbody>
      {% for row in hkd_rates %}
      <tr>
        <td class="rate-name">{{ row.name }}</td>
        <td class="rate-value">{{ row.value }}</td>
        <td>{{ row.change_7d }}</td>
        <td>{{ row.change_30d }}</td>
        <td>{{ row.sparkline }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <p class="source">Sources: HKMA, HSBC, BOC, SCB, Hang Seng, Interactive Brokers</p>
</div>

{# ===== USD RATES ===== #}
<div class="section">
  <div class="section-title">&#127482;&#127480; USD Interest Rates</div>
  <table>
    <thead>
      <tr><th>Rate</th><th>Current</th><th>7d Change</th><th>30d Change</th><th>Trend</th></tr>
    </thead>
    <tbody>
      {% for row in usd_rates %}
      <tr>
        <td class="rate-name">{{ row.name }}</td>
        <td class="rate-value">{{ row.value }}</td>
        <td>{{ row.change_7d }}</td>
        <td>{{ row.change_30d }}</td>
        <td>{{ row.sparkline }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <p class="source">Sources: Federal Reserve (FRED), NY Fed, US Treasury, Interactive Brokers</p>
</div>

{# ===== US TREASURY YIELD CURVE ===== #}
{% if treasury_yields %}
<div class="section">
  <div class="section-title">&#127974; US Treasury Yield Curve</div>
  <table>
    <thead>
      <tr><th>Maturity</th><th>Yield</th><th>7d Change</th></tr>
    </thead>
    <tbody>
      {% for row in treasury_yields %}
      <tr>
        <td class="rate-name">{{ row.maturity }}</td>
        <td class="rate-value">{{ row.value }}</td>
        <td>{{ row.change_7d }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <p class="source">Source: US Department of the Treasury</p>
</div>
{% endif %}

{# ===== RATE FORECASTS ===== #}
<div class="section">
  <div class="section-title">&#128302; Market Rate Expectations</div>

  {% if fedwatch %}
  <h4 style="color:#94a3b8;font-size:12px;margin-bottom:6px;">CME FedWatch - FOMC Meeting Probabilities</h4>
  <table class="forecast-table">
    <thead>
      <tr>
        <th>Meeting</th>
        {% for rate_range in fedwatch_ranges %}
        <th>{{ rate_range }}</th>
        {% endfor %}
      </tr>
    </thead>
    <tbody>
      {% for meeting in fedwatch %}
      <tr>
        <td class="rate-name">{{ meeting.meeting }}</td>
        {% for rate_range in fedwatch_ranges %}
        <td>
          {% if meeting.probabilities.get(rate_range) %}
          <span class="prob-bar" style="width:{{ meeting.probabilities[rate_range] * 0.6 }}px"></span>
          {{ "%.1f"|format(meeting.probabilities[rate_range]) }}%
          {% else %}—{% endif %}
        </td>
        {% endfor %}
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <p class="source">Source: CME Group FedWatch Tool (based on Fed Funds Futures)</p>
  {% else %}
  <p style="color:#94a3b8;font-size:12px;">FedWatch data unavailable — CME may restrict automated access.</p>
  {% endif %}

  {% if hkd_forwards %}
  <h4 style="color:#94a3b8;font-size:12px;margin:12px 0 6px;">HKD Forward Points (Implied Future Rates)</h4>
  <table class="forecast-table">
    <thead>
      <tr><th>Tenor</th><th>Bid</th><th>Offer</th></tr>
    </thead>
    <tbody>
      {% for row in hkd_forwards %}
      <tr>
        <td class="rate-name">{{ row.tenor }}</td>
        <td class="rate-value">{{ row.bid }}</td>
        <td class="rate-value">{{ row.offer }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <p class="source">Source: HKMA (HKD Forward Exchange Rates)</p>
  {% endif %}
</div>

<div class="footer">
  r_monitor &mdash; Automated Interest Rate Tracker<br>
  Data may be delayed. Not financial advice.
</div>

</body>
</html>
""")


def generate_report(data: dict) -> str:
    """Generate the full HTML report from collected data.

    Args:
        data: dict with keys:
            - hibor: dict of latest HIBOR rates
            - hkma_base_rate: dict with rate
            - prime_rates: list of bank prime rate dicts
            - ib_rates: dict with HKD/USD margin rates
            - fed_funds: dict with effective/target rates
            - sofr: dict with rate
            - treasury: dict with yield curve
            - fedwatch: list of meeting probability dicts
            - hkd_forwards: list of forward rate dicts
    """
    now = datetime.now()

    # --- Build HKD rates table ---
    hkd_rates = []

    # HKMA Base Rate
    base = data.get("hkma_base_rate", {})
    if base.get("rate") is not None:
        hkd_rates.append({
            "name": "HKMA Base Rate",
            "value": _fmt_rate(base["rate"]),
            "change_7d": _change_badge(None),  # Step function, no daily change
            "change_30d": _change_badge(None),
            "sparkline": "",
        })

    # HIBOR tenors
    hibor = data.get("hibor", {})
    tenor_keys = ["Overnight", "1 Week", "1 Month", "3 Months", "6 Months", "9 Months", "12 Months"]
    for tenor in tenor_keys:
        val = hibor.get(tenor)
        if val is not None:
            col_name = tenor
            hkd_rates.append({
                "name": f"HIBOR {tenor}",
                "value": _fmt_rate(val),
                "change_7d": _change_badge(get_change("hibor_daily", col_name, 7)),
                "change_30d": _change_badge(get_change("hibor_daily", col_name, 30)),
                "sparkline": "",
            })

    # Prime rates
    for pr in data.get("prime_rates", []):
        if pr.get("rate") is not None:
            hkd_rates.append({
                "name": f"Prime Rate ({pr['bank']})",
                "value": _fmt_rate(pr["rate"]),
                "change_7d": _change_badge(None),
                "change_30d": _change_badge(None),
                "sparkline": "",
            })

    # IB HKD
    ib = data.get("ib_rates", {})
    ib_hkd = ib.get("HKD")
    if ib_hkd and ib_hkd.get("rate") is not None:
        hkd_rates.append({
            "name": "IB HKD Margin Rate",
            "value": _fmt_rate(ib_hkd["rate"]),
            "change_7d": _change_badge(get_change("ib_rates", "hkd_rate", 7)),
            "change_30d": _change_badge(get_change("ib_rates", "hkd_rate", 30)),
            "sparkline": "",
        })

    # --- Build USD rates table ---
    usd_rates = []

    # Fed Funds
    fed = data.get("fed_funds", {})
    if fed.get("target_upper") is not None and fed.get("target_lower") is not None:
        usd_rates.append({
            "name": "Fed Funds Target Range",
            "value": f"{fed['target_lower']:.2f}% - {fed['target_upper']:.2f}%",
            "change_7d": _change_badge(None),
            "change_30d": _change_badge(None),
            "sparkline": "",
        })
    if fed.get("effective") is not None:
        usd_rates.append({
            "name": "Fed Funds Effective",
            "value": _fmt_rate(fed["effective"]),
            "change_7d": _change_badge(get_change("fed_rates", "rate", 7)),
            "change_30d": _change_badge(get_change("fed_rates", "rate", 30)),
            "sparkline": "",
        })

    # SOFR
    sofr = data.get("sofr", {})
    if sofr.get("rate") is not None:
        usd_rates.append({
            "name": "SOFR",
            "value": _fmt_rate(sofr["rate"]),
            "change_7d": _change_badge(get_change("sofr", "rate", 7)),
            "change_30d": _change_badge(get_change("sofr", "rate", 30)),
            "sparkline": "",
        })

    # IB USD
    ib_usd = ib.get("USD")
    if ib_usd and ib_usd.get("rate") is not None:
        usd_rates.append({
            "name": "IB USD Margin Rate",
            "value": _fmt_rate(ib_usd["rate"]),
            "change_7d": _change_badge(get_change("ib_rates", "usd_rate", 7)),
            "change_30d": _change_badge(get_change("ib_rates", "usd_rate", 30)),
            "sparkline": "",
        })

    # --- Treasury Yields ---
    treasury = data.get("treasury", {})
    treasury_yields = []
    maturity_order = ["1 Mo", "2 Mo", "3 Mo", "6 Mo", "1 Yr", "2 Yr", "3 Yr", "5 Yr", "7 Yr", "10 Yr", "20 Yr", "30 Yr"]
    for mat in maturity_order:
        val = treasury.get(mat)
        if val is not None:
            treasury_yields.append({
                "maturity": mat,
                "value": _fmt_rate(val),
                "change_7d": _change_badge(get_change("treasury_yields", mat, 7)),
            })

    # --- FedWatch ---
    fedwatch = data.get("fedwatch", [])
    fedwatch_ranges = []
    if fedwatch:
        # Collect all unique rate ranges across meetings
        all_ranges = set()
        for m in fedwatch:
            all_ranges.update(m.get("probabilities", {}).keys())
        fedwatch_ranges = sorted(all_ranges)

    # --- HKD Forwards ---
    hkd_forwards = data.get("hkd_forwards", [])
    formatted_forwards = []
    for fwd in hkd_forwards:
        formatted_forwards.append({
            "tenor": fwd.get("tenor", ""),
            "bid": fwd.get("bid", "N/A"),
            "offer": fwd.get("offer", "N/A"),
        })

    # --- Render ---
    html = REPORT_TEMPLATE.render(
        report_date=now.strftime("%Y-%m-%d"),
        report_time=now.strftime("%H:%M"),
        hkd_rates=hkd_rates,
        usd_rates=usd_rates,
        treasury_yields=treasury_yields,
        fedwatch=fedwatch,
        fedwatch_ranges=fedwatch_ranges,
        hkd_forwards=formatted_forwards,
    )

    return html
