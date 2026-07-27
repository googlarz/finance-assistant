"""
Timeline Engine — time-series analysis for Finance Assistant.

Provides trend detection, seasonality, correlations, anomalies, velocity,
and inflection points from the SQLite database. Pure stdlib only.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, timedelta
from typing import Optional

# ── Math Helpers ──────────────────────────────────────────────────────────────

def _mean(xs: list[float]) -> float:
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    variance = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(variance)


def _rolling_mean(xs: list[float], window: int = 3) -> list[float]:
    result = []
    for i in range(len(xs)):
        start = max(0, i - window + 1)
        chunk = xs[start : i + 1]
        result.append(_mean(chunk))
    return result


def _linear_regression(ys: list[float]) -> tuple[float, float, float]:
    """Returns (slope, intercept, r_squared). xs are 0-based indices."""
    n = len(ys)
    if n < 2:
        return (0.0, ys[0] if ys else 0.0, 0.0)

    xs = list(range(n))
    mean_x = _mean(xs)
    mean_y = _mean(ys)

    ss_xy = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    ss_xx = sum((x - mean_x) ** 2 for x in xs)

    if ss_xx == 0:
        return (0.0, mean_y, 0.0)

    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    # R-squared
    ss_res = sum((ys[i] - (slope * xs[i] + intercept)) ** 2 for i in range(n))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot != 0 else 0.0

    return (slope, intercept, max(0.0, r_squared))


def _pearson_r(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation coefficient between two equal-length lists."""
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x = _mean(xs)
    mean_y = _mean(ys)
    num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denom_x == 0 or denom_y == 0:
        return 0.0
    return num / (denom_x * denom_y)


# ── Month Helpers ─────────────────────────────────────────────────────────────

def _months_back(n: int) -> list[str]:
    """Return list of YYYY-MM strings, most recent first, going back n months."""
    today = date.today()
    result = []
    year, month = today.year, today.month
    for _ in range(n):
        result.append(f"{year}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return result


def _month_end(ym: str) -> str:
    """Return YYYY-MM-DD for the last day of the given YYYY-MM month."""
    year, month = int(ym[:4]), int(ym[5:7])
    if month == 12:
        last = date(year, month, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return last.isoformat()


# ── Core Query ────────────────────────────────────────────────────────────────

def get_monthly_summary(conn: sqlite3.Connection, months: int = 24) -> list[dict]:
    """
    Returns one dict per calendar month (most recent first), each containing:
    month, income, expenses, net, savings_rate, by_category,
    net_worth (from snapshots, nearest to month-end), portfolio_value.
    """
    month_list = _months_back(months)

    # ── transactions ─────────────────────────────────────────────────────────
    earliest = month_list[-1] + "-01"
    cursor = conn.execute(
        """
        SELECT strftime('%Y-%m', date) AS month,
               category,
               SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS income,
               SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) AS expenses
        FROM transactions
        WHERE date >= ?
          AND type NOT IN ('transfer', 'investment', 'debt_payment')
        GROUP BY month, category
        """,
        (earliest,),
    )
    rows = cursor.fetchall()

    # Aggregate per month
    month_data: dict[str, dict] = {}
    for ym in month_list:
        month_data[ym] = {"income": 0.0, "expenses": 0.0, "by_category": {}}

    for row in rows:
        ym = row[0]
        if ym not in month_data:
            continue
        cat = row[1] or "uncategorized"
        month_data[ym]["income"] += row[2] or 0.0
        month_data[ym]["expenses"] += row[3] or 0.0
        if row[3] and row[3] > 0:
            month_data[ym]["by_category"][cat] = (
                month_data[ym]["by_category"].get(cat, 0.0) + row[3]
            )

    # ── snapshots ────────────────────────────────────────────────────────────
    snap_cursor = conn.execute(
        "SELECT type, date, data FROM snapshots WHERE date >= ? ORDER BY date",
        (earliest,),
    )
    snaps = snap_cursor.fetchall()

    # Index snapshots by type → list of (date_str, data_dict)
    snap_by_type: dict[str, list[tuple[str, dict]]] = {}
    for row in snaps:
        stype, sdate, sdata = row[0], row[1], row[2]
        try:
            data_dict = json.loads(sdata)
        except (json.JSONDecodeError, TypeError):
            data_dict = {}
        snap_by_type.setdefault(stype, []).append((sdate, data_dict))

    def _nearest_snap(stype: str, target_date: str) -> Optional[dict]:
        entries = snap_by_type.get(stype, [])
        if not entries:
            return None
        best = min(entries, key=lambda e: abs((date.fromisoformat(e[0][:10]) - date.fromisoformat(target_date)).days))
        return best[1]

    # ── Build output ─────────────────────────────────────────────────────────
    result = []
    for ym in month_list:
        md = month_data[ym]
        income = md["income"]
        expenses = md["expenses"]
        net = income - expenses
        savings_rate = (net / income) if income > 0 else 0.0

        end_date = _month_end(ym)
        nw_snap = _nearest_snap("net_worth", end_date)
        port_snap = _nearest_snap("portfolio", end_date)

        net_worth = None
        if nw_snap:
            net_worth = nw_snap.get("net_worth") or nw_snap.get("total_assets")

        portfolio_value = None
        if port_snap:
            portfolio_value = port_snap.get("total_value")

        result.append({
            "month": ym,
            "income": round(income, 2),
            "expenses": round(expenses, 2),
            "net": round(net, 2),
            "savings_rate": round(savings_rate, 4),
            "by_category": {k: round(v, 2) for k, v in md["by_category"].items()},
            "net_worth": net_worth,
            "portfolio_value": portfolio_value,
        })

    return result


# ── Analysis Functions ────────────────────────────────────────────────────────

def compute_trend(series: list[float]) -> dict:
    """
    Linear regression on a list of values (oldest first).
    Returns slope, direction, r_squared, pct_change_per_period.
    """
    if len(series) < 2:
        return {"slope": 0.0, "direction": "flat", "r_squared": 0.0, "pct_change_per_period": 0.0}

    slope, _intercept, r_squared = _linear_regression(series)
    mean_val = _mean(series)

    if mean_val == 0:
        pct = 0.0
        direction = "flat"
    else:
        pct = (slope / abs(mean_val)) * 100
        if abs(pct) < 1.0:
            direction = "flat"
        elif slope > 0:
            direction = "up"
        else:
            direction = "down"

    return {
        "slope": round(slope, 4),
        "direction": direction,
        "r_squared": round(r_squared, 4),
        "pct_change_per_period": round(pct, 2),
    }


def detect_seasonality(monthly_data: list[dict], key: str) -> dict:
    """
    Detect annual seasonal patterns. Needs ≥13 months.
    key can be a top-level field ('expenses') or a category name.
    """
    empty = {
        "has_seasonality": False,
        "peak_month": None,
        "trough_month": None,
        "peak_vs_average_pct": 0.0,
        "description": "Not enough data for seasonality analysis.",
    }

    if len(monthly_data) < 13:
        return empty

    def _get_val(m: dict) -> float:
        if key in m:
            return float(m[key] or 0)
        return float(m.get("by_category", {}).get(key, 0))

    # Monthly averages across years (month number 1–12)
    month_totals: dict[int, list[float]] = {i: [] for i in range(1, 13)}
    for m in monthly_data:
        try:
            month_num = int(m["month"][5:7])
        except (KeyError, ValueError):
            continue
        val = _get_val(m)
        month_totals[month_num].append(val)

    # Only use months with at least one data point
    month_avgs: dict[int, float] = {}
    for mn, vals in month_totals.items():
        if vals:
            month_avgs[mn] = _mean(vals)

    if not month_avgs:
        return empty

    overall_avg = _mean(list(month_avgs.values()))
    if overall_avg == 0:
        return empty

    peak_month = max(month_avgs, key=lambda mn: month_avgs[mn])
    trough_month = min(month_avgs, key=lambda mn: month_avgs[mn])
    peak_val = month_avgs[peak_month]
    peak_pct = ((peak_val - overall_avg) / overall_avg) * 100

    # Consider seasonality present if peak is ≥15% above average
    has_seasonality = peak_pct >= 15.0

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    peak_name = month_names[peak_month - 1]
    desc = (
        f"{peak_name} {key} typically {peak_pct:.0f}% above average"
        if has_seasonality
        else f"No strong seasonal pattern detected for {key}."
    )

    return {
        "has_seasonality": has_seasonality,
        "peak_month": peak_month,
        "trough_month": trough_month,
        "peak_vs_average_pct": round(peak_pct, 2),
        "description": desc,
    }


def compute_correlations(monthly_data: list[dict]) -> list[dict]:
    """
    Pearson r between key metric pairs (only pairs with strength != 'none').
    """
    if len(monthly_data) < 3:
        return []

    def _extract(key: str) -> list[float]:
        vals = []
        for m in monthly_data:
            v = m.get(key)
            vals.append(float(v) if v is not None else float("nan"))
        return vals

    pairs = [
        ("income", "expenses"),
        ("income", "savings_rate"),
        ("income", "net_worth"),
        ("expenses", "net_worth"),
        ("net_worth", "portfolio_value"),
    ]

    results = []
    for a, b in pairs:
        xs_raw = _extract(a)
        ys_raw = _extract(b)

        # Filter out pairs where either value is NaN
        filtered = [(x, y) for x, y in zip(xs_raw, ys_raw)
                    if not math.isnan(x) and not math.isnan(y)]
        if len(filtered) < 3:
            continue

        xs = [p[0] for p in filtered]
        ys = [p[1] for p in filtered]
        r = _pearson_r(xs, ys)
        abs_r = abs(r)

        if abs_r > 0.7:
            strength = "strong"
        elif abs_r > 0.4:
            strength = "moderate"
        elif abs_r > 0.2:
            strength = "weak"
        else:
            continue  # skip "none"

        results.append({
            "metric_a": a,
            "metric_b": b,
            "r": round(r, 4),
            "strength": strength,
            "direction": "positive" if r >= 0 else "negative",
        })

    return results


def detect_anomalies(monthly_data: list[dict], key: str, sigma: float = 2.0) -> list[dict]:
    """
    Find months where a metric is more than sigma std devs from the rolling mean.
    """
    if len(monthly_data) < 4:
        return []

    # oldest first for rolling mean calculation
    ordered = list(reversed(monthly_data))

    def _get_val(m: dict) -> Optional[float]:
        v = m.get(key)
        if v is None:
            return None
        return float(v)

    values = [_get_val(m) for m in ordered]
    months_ordered = [m["month"] for m in ordered]

    # Use all non-None values to compute global mean/stdev for anomaly detection
    valid = [v for v in values if v is not None]
    if len(valid) < 4:
        return []

    global_mean = _mean(valid)
    global_std = _stdev(valid)

    if global_std == 0:
        return []

    results = []
    for i, (v, ym) in enumerate(zip(values, months_ordered)):
        if v is None:
            continue
        deviation = (v - global_mean) / global_std
        if abs(deviation) > sigma:
            results.append({
                "month": ym,
                "value": round(v, 2),
                "mean": round(global_mean, 2),
                "deviation_sigma": round(deviation, 2),
                "direction": "above" if deviation > 0 else "below",
            })

    return results


def compute_velocity(series: list[float]) -> str:
    """
    Is the trend accelerating or decelerating?
    Compare slope of first half vs second half of series.
    Returns: "accelerating" | "decelerating" | "stable" | "reversing"
    """
    if len(series) < 4:
        return "stable"

    mid = len(series) // 2
    first_half = series[:mid]
    second_half = series[mid:]

    slope1, _, _ = _linear_regression(first_half)
    slope2, _, _ = _linear_regression(second_half)

    # Reversing: slopes have opposite signs
    if slope1 * slope2 < 0 and abs(slope1) > 1e-9 and abs(slope2) > 1e-9:
        return "reversing"

    diff = slope2 - slope1
    threshold = max(abs(slope1), abs(slope2), 1e-9) * 0.1

    if abs(diff) < threshold:
        return "stable"
    elif diff > 0:
        return "accelerating"
    else:
        return "decelerating"


def find_inflection_points(series: list[float], months: list[str]) -> list[dict]:
    """
    Detect months where trend changed direction (local maxima/minima with 2-period lookahead).
    """
    if len(series) < 5 or len(series) != len(months):
        return []

    results = []
    for i in range(2, len(series) - 2):
        v = series[i]
        # Peak: higher than 2 neighbours on each side
        if v > series[i - 1] and v > series[i - 2] and v > series[i + 1] and v > series[i + 2]:
            results.append({"month": months[i], "type": "peak", "value": round(v, 2)})
        # Trough: lower than 2 neighbours on each side
        elif v < series[i - 1] and v < series[i - 2] and v < series[i + 1] and v < series[i + 2]:
            results.append({"month": months[i], "type": "trough", "value": round(v, 2)})

    return results


# ── Narrative Generation ──────────────────────────────────────────────────────

def _generate_narrative_bullets(
    monthly_data: list[dict],
    trends: dict,
    anomalies: dict,
    velocity: dict,
    inflection_points: dict,
) -> list[str]:
    """
    Pick 3-5 most notable findings in plain English.
    Priority: anomalies > velocity/acceleration > strong trends > seasonality.
    """
    bullets = []

    # 1. Anomalies (highest priority)
    for metric, anom_list in anomalies.items():
        for a in anom_list[:1]:  # at most one anomaly per metric
            direction_word = "spike" if a["direction"] == "above" else "dip"
            bullets.append(
                f"{metric.replace('_', ' ').title()} had an unusual {direction_word} in {a['month']} "
                f"({a['value']:,.0f} vs avg {a['mean']:,.0f}, {abs(a['deviation_sigma']):.1f}σ)."
            )
            if len(bullets) >= 3:
                break
        if len(bullets) >= 3:
            break

    # 2. Velocity / acceleration
    for metric, vel in velocity.items():
        if vel in ("accelerating", "reversing") and len(bullets) < 5:
            trend = trends.get(metric, {})
            direction = trend.get("direction", "")
            if vel == "reversing":
                bullets.append(f"{metric.replace('_', ' ').title()} trend is reversing direction.")
            elif direction == "up":
                bullets.append(f"{metric.replace('_', ' ').title()} growth is accelerating.")
            elif direction == "down":
                bullets.append(f"{metric.replace('_', ' ').title()} decline is accelerating.")

    # 3. Strong trends
    for metric, trend in trends.items():
        if metric == "by_category":
            continue
        if trend.get("direction") != "flat" and trend.get("r_squared", 0) > 0.5 and len(bullets) < 5:
            pct = trend.get("pct_change_per_period", 0)
            direction = trend.get("direction", "")
            if direction == "up":
                bullets.append(
                    f"{metric.replace('_', ' ').title()} is trending up "
                    f"(+{abs(pct):.1f}% per month, R²={trend['r_squared']:.2f})."
                )
            elif direction == "down":
                bullets.append(
                    f"{metric.replace('_', ' ').title()} is trending down "
                    f"({pct:.1f}% per month, R²={trend['r_squared']:.2f})."
                )

    # 4. Category trends
    cat_trends = trends.get("by_category", {})
    for cat, trend in cat_trends.items():
        if trend.get("direction") != "flat" and trend.get("r_squared", 0) > 0.6 and len(bullets) < 5:
            pct = trend.get("pct_change_per_period", 0)
            if trend["direction"] == "up":
                bullets.append(
                    f"{cat.title()} spending rising {abs(pct):.1f}% per month."
                )

    # Fallback
    if not bullets:
        if not monthly_data:
            bullets = ["No historical data yet — start logging transactions to see trends."]
        else:
            bullets = ["Not enough variation in data to highlight notable patterns yet."]

    return bullets[:5]


# ── Top-Level Entry Point ─────────────────────────────────────────────────────

def build_timeline_context(months: int = 24) -> dict:
    """
    Top-level function called by skill.py.
    Loads data from SQLite and returns full structured temporal context.
    """
    try:
        import os
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from db import get_conn
    except ImportError:
        return {
            "monthly_summary": [],
            "narrative_bullets": ["No historical data yet — start logging transactions to see trends."],
        }

    try:
        with get_conn() as conn:
            monthly_data = get_monthly_summary(conn, months=months)
    except Exception:
        return {
            "monthly_summary": [],
            "narrative_bullets": ["No historical data yet — start logging transactions to see trends."],
        }

    if not monthly_data:
        return {
            "monthly_summary": [],
            "narrative_bullets": ["No historical data yet — start logging transactions to see trends."],
        }

    # oldest-first series for trend calculations
    reversed_data = list(reversed(monthly_data))

    def _series(key: str) -> list[float]:
        vals = []
        for m in reversed_data:
            v = m.get(key)
            vals.append(float(v) if v is not None else 0.0)
        return vals

    months_list = [m["month"] for m in reversed_data]

    # Top-level metric series
    metric_keys = ["expenses", "income", "savings_rate", "net_worth", "portfolio_value"]
    series_map = {k: _series(k) for k in metric_keys}

    # Per-category series
    all_categories: set[str] = set()
    for m in monthly_data:
        all_categories.update(m.get("by_category", {}).keys())

    cat_series: dict[str, list[float]] = {}
    for cat in all_categories:
        cat_series[cat] = [float(m.get("by_category", {}).get(cat, 0)) for m in reversed_data]

    # ── Trends ───────────────────────────────────────────────────────────────
    trends: dict = {}
    for k in metric_keys:
        trends[k] = compute_trend(series_map[k])
    trends["by_category"] = {cat: compute_trend(cat_series[cat]) for cat in all_categories}

    # ── Seasonality ──────────────────────────────────────────────────────────
    seasonality: dict = {}
    for cat in all_categories:
        s = detect_seasonality(monthly_data, cat)
        if s["has_seasonality"]:
            seasonality[cat] = s

    # ── Correlations ─────────────────────────────────────────────────────────
    correlations = compute_correlations(monthly_data)

    # ── Anomalies ────────────────────────────────────────────────────────────
    anomaly_metrics = ["expenses", "net_worth"]
    anomalies: dict = {}
    for k in anomaly_metrics:
        result = detect_anomalies(monthly_data, k)
        if result:
            anomalies[k] = result

    # ── Velocity ─────────────────────────────────────────────────────────────
    velocity: dict = {}
    for k in metric_keys:
        velocity[k] = compute_velocity(series_map[k])

    # ── Inflection Points ────────────────────────────────────────────────────
    inflection_points: dict = {}
    for k in ["net_worth", "expenses", "income"]:
        pts = find_inflection_points(series_map[k], months_list)
        if pts:
            inflection_points[k] = pts

    # ── Narrative ────────────────────────────────────────────────────────────
    narrative_bullets = _generate_narrative_bullets(
        monthly_data, trends, anomalies, velocity, inflection_points
    )

    return {
        "monthly_summary": monthly_data,
        "trends": trends,
        "seasonality": seasonality,
        "correlations": correlations,
        "anomalies": anomalies,
        "velocity": velocity,
        "inflection_points": inflection_points,
        "narrative_bullets": narrative_bullets,
    }
