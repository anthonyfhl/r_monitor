"""Generate HTML report for interest rate monitoring."""

import logging
import math
from datetime import datetime
from pathlib import Path

import pandas as pd
from jinja2 import Template

from src.storage import get_change, get_recent, load_csv

_TEMPLATE_DIR = Path(__file__).parent / "templates"

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


def _sparkline_from_csv(csv_name: str, column: str, days: int = 30) -> str:
    """Generate a sparkline SVG from recent CSV data."""
    df = get_recent(csv_name, days=days)
    if df.empty or column not in df.columns:
        return ""
    vals = pd.to_numeric(df[column], errors="coerce").dropna().tolist()
    return _sparkline_svg(vals)


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


def _build_multi_series_chart_svg(
    series_defs: list[tuple[str, str, str, str, bool]],
    width: int = 860,
    height: int = 320,
) -> str:
    """Build an inline SVG multi-series line chart.

    Args:
        series_defs: list of (label, color, csv_name, column, is_step) tuples.
            is_step=True draws horizontal-then-vertical step lines.
        width: SVG width in pixels.
        height: SVG height in pixels.

    Returns:
        SVG string, or "" if no data.
    """
    pad_left, pad_right, pad_top, pad_bottom = 55, 20, 20, 40
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    # --- Load data ---
    csv_names = list({s[2] for s in series_defs})
    dfs = {}
    for name in csv_names:
        df = load_csv(name)
        if not df.empty and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            dfs[name] = df

    if not dfs:
        return ""

    # --- Determine global date/rate range ---
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
    # Mid-year markers
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
            points = []
            rows = list(s.itertuples(index=False))
            for i, row in enumerate(rows):
                dt, val = row[0], row[1]
                if i > 0:
                    prev_val = rows[i - 1][1]
                    points.append(f"{x_pos(dt):.1f},{y_pos(prev_val):.1f}")
                points.append(f"{x_pos(dt):.1f},{y_pos(val):.1f}")
            if rows:
                last_val = rows[-1][1]
                end_dt = min(today, date_max)
                if end_dt > rows[-1][0]:
                    points.append(f"{x_pos(end_dt):.1f},{y_pos(last_val):.1f}")
        else:
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

    # Legend (top-left)
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


def _build_yield_curve_svg(treasury: dict, width: int = 500, height: int = 200) -> str:
    """Build an inline SVG of the current Treasury yield curve shape.

    Plots yield (Y) against maturity (X, log scale) for a single point in time.
    """
    maturities = [
        ("1 Mo", 1), ("2 Mo", 2), ("3 Mo", 3), ("6 Mo", 6), ("1 Yr", 12),
        ("2 Yr", 24), ("3 Yr", 36), ("5 Yr", 60), ("7 Yr", 84),
        ("10 Yr", 120), ("20 Yr", 240), ("30 Yr", 360),
    ]

    # Filter to available data points
    points_data = []
    for label, months in maturities:
        val = treasury.get(label)
        if val is not None:
            try:
                points_data.append((label, months, float(val)))
            except (ValueError, TypeError):
                pass

    if len(points_data) < 3:
        return ""

    pad_left, pad_right, pad_top, pad_bottom = 45, 20, 15, 30
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    # Log scale for maturity
    import math as _math
    log_min = _math.log(points_data[0][1])
    log_max = _math.log(points_data[-1][1])
    log_range = log_max - log_min

    vals = [p[2] for p in points_data]
    val_min = min(vals) - 0.15
    val_max = max(vals) + 0.15
    val_range = val_max - val_min
    if val_range == 0:
        val_range = 1

    def x_pos(months):
        return pad_left + ((_math.log(months) - log_min) / log_range) * plot_w

    def y_pos(v):
        return pad_top + plot_h - ((v - val_min) / val_range) * plot_h

    svg = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="background:#0f172a;border-radius:8px">'
    ]

    # Y-axis grid
    tick_step = 0.25 if val_range < 2 else 0.5
    y_tick = math.ceil(val_min / tick_step) * tick_step
    while y_tick <= val_max:
        yp = y_pos(y_tick)
        svg.append(
            f'<line x1="{pad_left}" y1="{yp:.1f}" x2="{width - pad_right}" y2="{yp:.1f}" '
            f'stroke="#1e293b" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{pad_left - 4}" y="{yp + 4:.1f}" text-anchor="end" '
            f'fill="#64748b" font-size="9">{y_tick:.2f}%</text>'
        )
        y_tick += tick_step

    # X-axis labels (selected tenors only)
    x_labels = ["3 Mo", "1 Yr", "2 Yr", "5 Yr", "10 Yr", "30 Yr"]
    for label, months, _ in points_data:
        if label in x_labels:
            xp = x_pos(months)
            svg.append(
                f'<text x="{xp:.1f}" y="{height - pad_bottom + 14}" text-anchor="middle" '
                f'fill="#64748b" font-size="9">{label}</text>'
            )

    # Polyline
    poly_points = []
    for label, months, val in points_data:
        poly_points.append(f"{x_pos(months):.1f},{y_pos(val):.1f}")
    svg.append(
        f'<polyline points="{" ".join(poly_points)}" fill="none" '
        f'stroke="#22d3ee" stroke-width="2" opacity="0.9"/>'
    )

    # Dot markers + value labels
    for label, months, val in points_data:
        xp = x_pos(months)
        yp = y_pos(val)
        svg.append(
            f'<circle cx="{xp:.1f}" cy="{yp:.1f}" r="3" fill="#22d3ee"/>'
        )
        # Value label above the dot
        svg.append(
            f'<text x="{xp:.1f}" y="{yp - 6:.1f}" text-anchor="middle" '
            f'fill="#94a3b8" font-size="8">{val:.2f}</text>'
        )

    svg.append("</svg>")
    return "\n".join(svg)


def _build_hkd_chart_svg() -> str:
    """Build HKD rates chart (HIBOR, Prime, IB HKD)."""
    series = [
        ("HIBOR O/N", "#60a5fa", "hibor_daily", "Overnight", False),
        ("HIBOR 1M", "#38bdf8", "hibor_daily", "1 Month", False),
        ("HIBOR 3M", "#22d3ee", "hibor_daily", "3 Months", False),
        ("HIBOR 12M", "#a78bfa", "hibor_daily", "12 Months", False),
    ]

    # Conditionally add Prime rates and IB HKD
    prime_df = load_csv("prime_rates")
    if not prime_df.empty and "date" in prime_df.columns:
        if "HSBC" in prime_df.columns:
            series.append(("細P (HSBC)", "#f97316", "prime_rates", "HSBC", True))
        if "DBS" in prime_df.columns:
            series.append(("大P (DBS)", "#ef4444", "prime_rates", "DBS", True))

    ib_df = load_csv("ib_rates")
    if not ib_df.empty and "hkd_rate" in ib_df.columns:
        series.append(("IB HKD", "#fbbf24", "ib_rates", "hkd_rate", False))

    return _build_multi_series_chart_svg(series)


def _build_usd_chart_svg() -> str:
    """Build USD rates chart (Fed Funds, SOFR, IB USD, Treasury 2Y/10Y)."""
    series = [
        ("Fed Funds", "#ef4444", "fed_rates", "rate", True),
        ("SOFR", "#22d3ee", "sofr", "rate", False),
        ("Treasury 2Y", "#a78bfa", "treasury_yields", "2 Yr", False),
        ("Treasury 10Y", "#38bdf8", "treasury_yields", "10 Yr", False),
    ]

    ib_df = load_csv("ib_rates")
    if not ib_df.empty and "usd_rate" in ib_df.columns:
        series.append(("IB USD", "#fbbf24", "ib_rates", "usd_rate", False))

    return _build_multi_series_chart_svg(series)


def _load_template() -> Template:
    """Load the Jinja2 report template from the templates directory."""
    template_path = _TEMPLATE_DIR / "report.html"
    return Template(template_path.read_text(encoding="utf-8"))


REPORT_TEMPLATE = _load_template()


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
                "sparkline": _sparkline_from_csv("hibor_daily", col_name),
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
            "sparkline": _sparkline_from_csv("hibor_daily", "1 Month"),
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
            "sparkline": _sparkline_from_csv("ib_rates", "hkd_rate"),
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
            "sparkline": _sparkline_from_csv("fed_rates", "rate"),
        })

    # SOFR
    sofr = data.get("sofr", {})
    if sofr.get("rate") is not None:
        usd_rates.append({
            "name": "SOFR",
            "value": _fmt_rate(sofr["rate"]),
            "change_7d": _change_badge(get_change("sofr", "rate", 7)),
            "change_30d": _change_badge(get_change("sofr", "rate", 30)),
            "sparkline": _sparkline_from_csv("sofr", "rate"),
        })

    # IB USD
    ib_usd = ib.get("USD")
    if ib_usd and ib_usd.get("rate") is not None:
        usd_rates.append({
            "name": "IB USD Margin Rate",
            "value": _fmt_rate(ib_usd["rate"]),
            "change_7d": _change_badge(get_change("ib_rates", "usd_rate", 7)),
            "change_30d": _change_badge(get_change("ib_rates", "usd_rate", 30)),
            "sparkline": _sparkline_from_csv("ib_rates", "usd_rate"),
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

    # --- Charts ---
    hkd_chart = _build_hkd_chart_svg()
    usd_chart = _build_usd_chart_svg()
    yield_curve_chart = _build_yield_curve_svg(treasury)

    # --- Render ---
    html = REPORT_TEMPLATE.render(
        report_date=now.strftime("%Y-%m-%d"),
        report_time=now.strftime("%H:%M"),
        hkd_rates=hkd_rates,
        usd_rates=usd_rates,
        hkd_chart=hkd_chart,
        usd_chart=usd_chart,
        yield_curve_chart=yield_curve_chart,
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
