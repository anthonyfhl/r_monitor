"""Generate HTML report for interest rate monitoring."""

import logging
import math
from datetime import datetime

import pandas as pd
from jinja2 import Template

from src.storage import get_change, load_csv

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


def _build_hkd_chart_svg(width: int = 860, height: int = 320) -> str:
    """Build an inline SVG multi-series line chart of HKD rates over time.

    Series: HIBOR O/N, 1M, 3M, 12M + 細P + 大P + IB HKD
    Uses data from hibor_daily.csv, prime_rates.csv, ib_rates.csv
    """
    pad_left, pad_right, pad_top, pad_bottom = 55, 20, 20, 40
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    # --- Load data ---
    hibor_df = load_csv("hibor_daily")
    if hibor_df.empty or "date" not in hibor_df.columns:
        return ""

    hibor_df["date"] = pd.to_datetime(hibor_df["date"])
    hibor_df = hibor_df.sort_values("date")

    # Series config: (label, color, csv_name, column, step)
    # step=True draws horizontal-then-vertical step lines (for rates that jump)
    series_defs = [
        ("HIBOR O/N", "#60a5fa", "hibor_daily", "Overnight", False),
        ("HIBOR 1M", "#38bdf8", "hibor_daily", "1 Month", False),
        ("HIBOR 3M", "#22d3ee", "hibor_daily", "3 Months", False),
        ("HIBOR 12M", "#a78bfa", "hibor_daily", "12 Months", False),
    ]

    # Also load prime rates & IB rates if available
    prime_df = load_csv("prime_rates")
    if not prime_df.empty and "date" in prime_df.columns:
        prime_df["date"] = pd.to_datetime(prime_df["date"])
        prime_df = prime_df.sort_values("date")
        if "HSBC" in prime_df.columns:
            series_defs.append(("細P (HSBC)", "#f97316", "prime_rates", "HSBC", True))
        if "DBS" in prime_df.columns:
            series_defs.append(("大P (DBS)", "#ef4444", "prime_rates", "DBS", True))

    ib_df = load_csv("ib_rates")
    if not ib_df.empty and "date" in ib_df.columns:
        ib_df["date"] = pd.to_datetime(ib_df["date"])
        ib_df = ib_df.sort_values("date")
        if "hkd_rate" in ib_df.columns:
            series_defs.append(("IB HKD", "#fbbf24", "ib_rates", "hkd_rate", False))

    # --- Determine global date/rate range ---
    dfs = {"hibor_daily": hibor_df}
    if not prime_df.empty:
        dfs["prime_rates"] = prime_df
    if not ib_df.empty:
        dfs["ib_rates"] = ib_df

    all_dates = []
    all_vals = []
    for label, color, csv_name, col, step in series_defs:
        df = dfs.get(csv_name)
        if df is None or col not in df.columns:
            continue
        s = df[["date", col]].dropna(subset=[col])
        if not s.empty:
            all_dates.extend(s["date"].tolist())
            all_vals.extend(s[col].astype(float).tolist())

    if not all_dates or not all_vals:
        return ""

    date_min = min(all_dates)
    date_max = max(all_dates)
    date_range = (date_max - date_min).total_seconds()
    if date_range == 0:
        return ""

    val_min = min(all_vals)
    val_max = max(all_vals)
    val_range = val_max - val_min
    if val_range == 0:
        val_range = 1
    # Add 5% padding
    val_min -= val_range * 0.05
    val_max += val_range * 0.05
    val_range = val_max - val_min

    def x_pos(dt):
        return pad_left + ((dt - date_min).total_seconds() / date_range) * plot_w

    def y_pos(v):
        return pad_top + plot_h - ((v - val_min) / val_range) * plot_h

    # --- Build SVG ---
    svg_parts = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="background:#0f172a;border-radius:8px">'
    ]

    # Grid lines and Y-axis labels
    # Nice round tick values
    tick_step = 0.5
    if val_range > 4:
        tick_step = 1.0
    elif val_range < 1:
        tick_step = 0.1

    y_tick = math.ceil(val_min / tick_step) * tick_step
    while y_tick <= val_max:
        yp = y_pos(y_tick)
        svg_parts.append(
            f'<line x1="{pad_left}" y1="{yp:.1f}" x2="{width - pad_right}" y2="{yp:.1f}" '
            f'stroke="#1e293b" stroke-width="1"/>'
        )
        svg_parts.append(
            f'<text x="{pad_left - 5}" y="{yp + 4:.1f}" text-anchor="end" '
            f'fill="#64748b" font-size="10">{y_tick:.1f}%</text>'
        )
        y_tick += tick_step

    # X-axis: year labels
    for year in range(date_min.year, date_max.year + 2):
        dt = pd.Timestamp(f"{year}-01-01")
        if dt < date_min or dt > date_max:
            continue
        xp = x_pos(dt)
        svg_parts.append(
            f'<line x1="{xp:.1f}" y1="{pad_top}" x2="{xp:.1f}" y2="{height - pad_bottom}" '
            f'stroke="#1e293b" stroke-width="1"/>'
        )
        svg_parts.append(
            f'<text x="{xp:.1f}" y="{height - pad_bottom + 15}" text-anchor="middle" '
            f'fill="#64748b" font-size="10">{year}</text>'
        )
    # Also add mid-year markers
    for year in range(date_min.year, date_max.year + 2):
        dt = pd.Timestamp(f"{year}-07-01")
        if dt < date_min or dt > date_max:
            continue
        xp = x_pos(dt)
        svg_parts.append(
            f'<line x1="{xp:.1f}" y1="{pad_top}" x2="{xp:.1f}" y2="{height - pad_bottom}" '
            f'stroke="#1e293b" stroke-width="0.5" stroke-dasharray="4,4"/>'
        )

    # Plot each series
    legend_items = []
    today = pd.Timestamp.now().normalize()
    for label, color, csv_name, col, is_step in series_defs:
        df = dfs.get(csv_name)
        if df is None or col not in df.columns:
            continue
        s = df[["date", col]].dropna(subset=[col]).copy()
        s[col] = s[col].astype(float)
        if s.empty:
            continue

        if is_step:
            # Step-function series: horizontal then vertical at each change
            # Extend the last known value to today for a complete picture
            points = []
            rows = list(s.itertuples(index=False))
            for i, row in enumerate(rows):
                dt, val = row[0], row[1]
                if i > 0:
                    # Horizontal line from previous y to this x
                    prev_val = rows[i - 1][1]
                    points.append(f"{x_pos(dt):.1f},{y_pos(prev_val):.1f}")
                # Vertical line to new y
                points.append(f"{x_pos(dt):.1f},{y_pos(val):.1f}")
            # Extend last value to today (or date_max)
            if rows:
                last_val = rows[-1][1]
                end_dt = min(today, date_max)
                if end_dt > rows[-1][0]:
                    points.append(f"{x_pos(end_dt):.1f},{y_pos(last_val):.1f}")
        else:
            # Continuous series — downsample if too many points
            if len(s) > 500:
                ds_step = len(s) // 400
                s = s.iloc[::ds_step]

            points = []
            for _, row in s.iterrows():
                px = x_pos(row["date"])
                py = y_pos(row[col])
                points.append(f"{px:.1f},{py:.1f}")

        if points:
            polyline = " ".join(points)
            svg_parts.append(
                f'<polyline points="{polyline}" fill="none" stroke="{color}" '
                f'stroke-width="1.5" opacity="0.85"/>'
            )
            legend_items.append((label, color))

    # Legend (bottom-right)
    leg_x = pad_left + 10
    leg_y = pad_top + 5
    for i, (label, color) in enumerate(legend_items):
        lx = leg_x + (i % 4) * 130
        ly = leg_y + (i // 4) * 16
        svg_parts.append(
            f'<line x1="{lx}" y1="{ly + 4}" x2="{lx + 16}" y2="{ly + 4}" '
            f'stroke="{color}" stroke-width="2.5"/>'
        )
        svg_parts.append(
            f'<text x="{lx + 20}" y="{ly + 8}" fill="#94a3b8" font-size="10">{label}</text>'
        )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


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
  .current-row { background: #1e3a5f; border-left: 3px solid #38bdf8; }
  .na { color: #64748b; }
  .esaver-table td { font-size: 12px; padding: 5px 8px; }
  .esaver-table th { font-size: 10px; padding: 6px 8px; }
  .note-cell { white-space: normal; max-width: 120px; font-size: 11px; color: #94a3b8; }
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
  <p class="source">Sources: HKAB, HSBC, DBS, Interactive Brokers</p>
  {% if hkd_chart %}
  <div style="margin-top:12px">
    <div style="color:#94a3b8;font-size:12px;margin-bottom:6px;">Historical HKD Rates</div>
    {{ hkd_chart }}
  </div>
  {% endif %}
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

{# ===== DBS eSAVER PROMOTIONS ===== #}
{% if esaver_history %}
<div class="section">
  <div class="section-title">&#128179; DBS e$aver Savings Promotion (Existing Customers)</div>
  {% if esaver_current %}
  <p style="color:#94a3b8;font-size:12px;margin-bottom:8px;">
    Current: <b style="color:#38bdf8">{{ esaver_current.promo_month or 'N/A' }}</b>
    &mdash; Register by {{ esaver_current.reg_end or '?' }}
    &mdash; Reward until {{ esaver_current.reward_end or '?' }}
    &mdash; Min HK${{ "{:,.0f}".format(esaver_current.min_hkd) if esaver_current.min_hkd else 'N/A' }}
    / US${{ "{:,.0f}".format(esaver_current.min_usd) if esaver_current.min_usd else 'N/A' }}
  </p>
  {% endif %}
  <table class="esaver-table">
    <thead>
      <tr>
        <th>Month</th>
        <th>HKD e$aver</th>
        <th>USD e$aver</th>
        <th>Total HKD</th><th>Total USD</th>
        <th>Level-Up</th>
        <th>Excludes</th>
        <th>Reg End</th><th>Reward End</th>
        <th>Notes</th>
      </tr>
    </thead>
    <tbody>
      {% for row in esaver_history %}
      <tr{% if row.is_current %} class="current-row"{% endif %}>
        <td class="rate-name">{{ row.promo_month }}</td>
        <td class="rate-value">{% if row.hkd_esaver_rate %}{{ "%.3f"|format(row.hkd_esaver_rate) }}%{% else %}<span class="na">N/A</span>{% endif %}</td>
        <td class="rate-value">{% if row.usd_esaver_rate %}{{ "%.3f"|format(row.usd_esaver_rate) }}%{% else %}<span class="na">N/A</span>{% endif %}</td>
        <td class="rate-value" style="color:#22c55e">{% if row.max_total_hkd %}{{ "%.2f"|format(row.max_total_hkd) }}%{% else %}<span class="na">N/A</span>{% endif %}</td>
        <td class="rate-value" style="color:#22c55e">{% if row.max_total_usd %}{{ "%.2f"|format(row.max_total_usd) }}%{% else %}<span class="na">N/A</span>{% endif %}</td>
        <td>{% if row.has_levelup == 'yes' %}<span style="color:#fbbf24">Yes</span>{% else %}<span class="na">No</span>{% endif %}</td>
        <td class="note-cell">{{ row.excludes or '' }}</td>
        <td style="font-size:11px">{{ row.reg_end or '' }}</td>
        <td style="font-size:11px">{{ row.reward_end or '' }}</td>
        <td class="note-cell">{{ row.notes or '' }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <p class="source">Source: DBS Bank (Hong Kong) &mdash; T&amp;Cs for Existing Customers</p>
</div>
{% endif %}

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
  <h4 style="color:#94a3b8;font-size:12px;margin-bottom:6px;">FedWatch - FOMC Meeting Rate Probabilities</h4>
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
  <p class="source">Source: Investing.com Fed Rate Monitor (based on Fed Funds Futures)</p>
  {% else %}
  <p style="color:#94a3b8;font-size:12px;">FedWatch data unavailable.</p>
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

    # HIBOR tenors
    hibor = data.get("hibor", {})
    tenor_keys = ["Overnight", "1 Month", "3 Months", "12 Months"]
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

    # HSBC WPL Rate (<1m) = HIBOR 1M + 1.2%
    hibor_1m = hibor.get("1 Month")
    if hibor_1m is not None:
        wpl_rate = hibor_1m + 1.2
        hkd_rates.append({
            "name": "HSBC WPL Rate (&lt;1m)",
            "value": _fmt_rate(wpl_rate),
            "change_7d": _change_badge(get_change("hibor_daily", "1 Month", 7)),
            "change_30d": _change_badge(get_change("hibor_daily", "1 Month", 30)),
            "sparkline": "",
        })

    # Prime rates — label with 細P / 大P tier
    _prime_labels = {
        "HSBC": "細P Prime (HSBC)",
        "DBS": "大P Prime (DBS)",
    }
    for pr in data.get("prime_rates", []):
        if pr.get("rate") is not None:
            label = _prime_labels.get(pr["bank"], f"Prime Rate ({pr['bank']})")
            hkd_rates.append({
                "name": label,
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

    # --- DBS eSaver ---
    esaver_current = data.get("esaver", {})
    esaver_history = _build_esaver_history(esaver_current)

    # --- HKD Chart ---
    hkd_chart = _build_hkd_chart_svg()

    # --- Render ---
    html = REPORT_TEMPLATE.render(
        report_date=now.strftime("%Y-%m-%d"),
        report_time=now.strftime("%H:%M"),
        hkd_rates=hkd_rates,
        usd_rates=usd_rates,
        hkd_chart=hkd_chart,
        treasury_yields=treasury_yields,
        fedwatch=fedwatch,
        fedwatch_ranges=fedwatch_ranges,
        hkd_forwards=formatted_forwards,
        esaver_current=esaver_current,
        esaver_history=esaver_history,
    )

    return html


def _build_esaver_history(current: dict) -> list[dict]:
    """Load eSaver history from CSV and format for the report template."""
    df = load_csv("esaver_history")
    if df.empty:
        return []

    df = df.sort_values("promo_month").reset_index(drop=True)
    current_month = current.get("promo_month", "")

    rows = []
    for _, r in df.iterrows():
        row = {}
        for col in df.columns:
            val = r[col]
            if isinstance(val, float) and math.isnan(val):
                row[col] = None
            else:
                row[col] = val
        row["is_current"] = (str(row.get("promo_month", "")) == current_month)
        rows.append(row)

    return rows
