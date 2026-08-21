# overdraft_detector.py

"""
Overdraft Detector — 30/60/90-day forward cash flow with overdraft risk warnings.

Complements cashflow_forecast.py by using real transaction history patterns
plus committed recurring items from SQLite to detect overdraft risk.
"""

from __future__ import annotations

import calendar
import os
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional


# ── DB import ─────────────────────────────────────────────────────────────────

try:
    from db import get_conn as _get_conn
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from db import get_conn as _get_conn


# ── Public API ────────────────────────────────────────────────────────────────

def get_account_balance(conn, account_id: str = None) -> float:
    """
    Get current balance from accounts table.
    If account_id is None, return sum of all checking/savings accounts.
    """
    if account_id is not None:
        row = conn.execute(
            "SELECT current_balance FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        return float(row["current_balance"]) if row else 0.0
    else:
        rows = conn.execute(
            "SELECT current_balance FROM accounts WHERE type IN ('checking', 'savings')"
        ).fetchall()
        return sum(float(r["current_balance"]) for r in rows)


def project_inflows(conn, days: int = 90) -> list[dict]:
    """
    Project future inflows from recurring_items (amount > 0) and detected patterns.
    Returns list of dicts: {date, amount, description, confidence}.
    """
    today = date.today()
    end = today + timedelta(days=days)
    results = []

    # 1. recurring_items table
    rows = conn.execute(
        "SELECT * FROM recurring_items WHERE amount > 0 AND active = 1"
    ).fetchall()
    for row in rows:
        for d in _project_item_dates(row, today, end):
            results.append({
                "date": d.isoformat(),
                "amount": float(row["amount"]),
                "description": f"{row['name']} (recurring)",
                "confidence": "high",
            })

    # 2. Pattern-detected income
    for pat in _detect_recurring_patterns(conn):
        if pat["avg_amount"] > 0:
            for d in _dates_for_pattern(pat["day_of_month"], today, end):
                results.append({
                    "date": d.isoformat(),
                    "amount": pat["avg_amount"],
                    "description": f"{pat['payee'] or pat['category']} (pattern)",
                    "confidence": "pattern",
                })

    return sorted(results, key=lambda x: x["date"])


def project_outflows(conn, days: int = 90) -> list[dict]:
    """
    Project future outflows from recurring_items (amount < 0) and detected patterns.
    Returns list of dicts with negative amounts.
    """
    today = date.today()
    end = today + timedelta(days=days)
    results = []

    # 1. recurring_items table
    rows = conn.execute(
        "SELECT * FROM recurring_items WHERE amount < 0 AND active = 1"
    ).fetchall()
    for row in rows:
        for d in _project_item_dates(row, today, end):
            results.append({
                "date": d.isoformat(),
                "amount": float(row["amount"]),
                "description": f"{row['name']} (recurring)",
                "confidence": "high",
            })

    # 2. Pattern-detected expenses
    for pat in _detect_recurring_patterns(conn):
        if pat["avg_amount"] < 0:
            for d in _dates_for_pattern(pat["day_of_month"], today, end):
                results.append({
                    "date": d.isoformat(),
                    "amount": pat["avg_amount"],
                    "description": f"{pat['payee'] or pat['category']} (pattern)",
                    "confidence": "pattern",
                })

    return sorted(results, key=lambda x: x["date"])


def build_daily_balance_forecast(
    starting_balance: float,
    inflows: list[dict],
    outflows: list[dict],
    days: int = 90,
) -> list[dict]:
    """
    Builds day-by-day running balance for the next `days` days.
    Returns only days where balance changes or is a weekly checkpoint.
    """
    today = date.today()

    # Map date string → list of transactions
    tx_by_date: dict[str, list[dict]] = defaultdict(list)
    for item in inflows + outflows:
        tx_by_date[item["date"]].append(item)

    balance = starting_balance
    snapshot: list[dict] = []

    for i in range(days):
        d = today + timedelta(days=i + 1)
        ds = d.isoformat()
        day_txns = tx_by_date.get(ds, [])
        is_checkpoint = (i + 1) % 7 == 0  # weekly

        if day_txns:
            for tx in day_txns:
                balance += tx["amount"]

        if day_txns or is_checkpoint:
            snapshot.append({
                "date": ds,
                "balance": round(balance, 2),
                "transactions": [
                    {"amount": t["amount"], "description": t["description"]}
                    for t in day_txns
                ],
                "is_low": balance < 500,
                "is_negative": balance < 0,
            })

    return snapshot


def detect_overdraft_risk(
    daily_forecast: list[dict],
    overdraft_threshold: float = 200.0,
) -> list[dict]:
    """
    Find days where projected balance drops below overdraft_threshold.
    """
    today = date.today()
    risks = []

    for snap in daily_forecast:
        bal = snap["balance"]
        if bal >= overdraft_threshold:
            continue

        d = date.fromisoformat(snap["date"])
        days_from_now = (d - today).days

        # Largest outflow on or just before this date
        triggered_by = ""
        largest_out = 0.0
        for tx in snap.get("transactions", []):
            if tx["amount"] < largest_out:
                largest_out = tx["amount"]
                triggered_by = tx["description"]

        severity = "critical" if bal < 0 else "warning"

        month_str = d.strftime("%b %-d")
        if triggered_by:
            trigger_part = f" {triggered_by.split(' (')[0]} of €{abs(largest_out):,.0f} due {month_str}."
        else:
            trigger_part = ""

        timing = "in 2 days" if days_from_now <= 2 else f"{days_from_now} days from now"
        if bal < 0:
            message = (
                f"Heads up — your balance could go negative on {month_str} ({timing}), "
                f"hitting around €{bal:,.0f}.{trigger_part}"
            )
        else:
            message = (
                f"Your balance looks tight around {month_str} ({timing}) — "
                f"projected at €{bal:,.0f}.{trigger_part}"
            )

        risks.append({
            "date": snap["date"],
            "projected_balance": bal,
            "days_from_now": days_from_now,
            "triggered_by": triggered_by,
            "severity": severity,
            "message": message,
        })

    return risks


def get_cashflow_summary(
    conn=None, days: int = 90, overdraft_threshold: float = 200.0
) -> dict:
    """
    Top-level function returning full cash flow summary with overdraft risks.
    """
    _own_conn = conn is None
    if _own_conn:
        ctx = _get_conn()
        conn = ctx.__enter__()
    try:
        balance = get_account_balance(conn)
        inflows = project_inflows(conn, days)
        outflows = project_outflows(conn, days)

        daily = build_daily_balance_forecast(balance, inflows, outflows, days)
        risks = detect_overdraft_risk(daily, overdraft_threshold)

        total_in = sum(x["amount"] for x in inflows)
        total_out = sum(x["amount"] for x in outflows)
        end_balance = daily[-1]["balance"] if daily else balance + total_in + total_out

        min_balance = balance
        min_balance_date = ""
        for snap in daily:
            if snap["balance"] < min_balance:
                min_balance = snap["balance"]
                min_balance_date = snap["date"]

        narrative = _build_narrative(balance, end_balance, total_in, total_out, risks, days)

        return {
            "current_balance": balance,
            "forecast_days": days,
            "projected_inflows_total": round(total_in, 2),
            "projected_outflows_total": round(total_out, 2),
            "projected_end_balance": round(end_balance, 2),
            "min_balance": round(min_balance, 2),
            "min_balance_date": min_balance_date,
            "overdraft_risks": risks,
            "daily_forecast": daily,
            "narrative": narrative,
        }
    finally:
        if _own_conn:
            ctx.__exit__(None, None, None)


def get_cashflow_alerts(conn=None) -> list[dict]:
    """
    Returns session alerts (matching session_alerts.py urgency structure) for:
    - Overdraft risk in next 14 days: urgency="critical", domain="cashflow"
    - Overdraft risk in 15-30 days: urgency="warning", domain="cashflow"
    - Min balance < 500 in next 30 days: urgency="info", domain="cashflow"
    """
    _own_conn = conn is None
    if _own_conn:
        ctx = _get_conn()
        conn = ctx.__enter__()
    try:
        summary = get_cashflow_summary(conn, days=90)
        alerts = []

        seen_dates: set[str] = set()
        for risk in summary["overdraft_risks"]:
            dfn = risk["days_from_now"]
            if dfn <= 14:
                urgency = "critical"
            elif dfn <= 30:
                urgency = "warning"
            else:
                continue  # beyond 30-day alert window

            if risk["date"] in seen_dates:
                continue
            seen_dates.add(risk["date"])

            alerts.append({
                "urgency": urgency,
                "domain": "cashflow",
                "title": "Overdraft risk",
                "detail": risk["message"],
                "action": "Review upcoming expenses or transfer funds.",
            })

        # Min balance < 500 within 30 days
        low_snap = next(
            (s for s in summary["daily_forecast"]
             if s["is_low"] and _days_from_today(s["date"]) <= 30),
            None,
        )
        if low_snap and not any(a["urgency"] in ("critical", "warning") for a in alerts):
            alerts.append({
                "urgency": "info",
                "domain": "cashflow",
                "title": "Low balance projected",
                "detail": (
                    f"Balance may drop below €500 around {low_snap['date']} "
                    f"(projected: €{low_snap['balance']:,.0f})."
                ),
                "action": "Consider setting aside a buffer.",
            })

        return alerts
    finally:
        if _own_conn:
            ctx.__exit__(None, None, None)


# ── Private helpers ───────────────────────────────────────────────────────────

def _detect_recurring_patterns(conn, days_back: int = 90) -> list[dict]:
    """
    Look at last 90 days of transactions. Find payee+category combos that:
    - Appear in 3+ different months
    - On the same day of month (±2 days tolerance)
    - Similar amount (±15%)
    """
    cutoff = (date.today() - timedelta(days=days_back)).isoformat()
    rows = conn.execute(
        """
        SELECT date, amount, payee, category
        FROM transactions
        WHERE date >= ?
        ORDER BY date
        """,
        (cutoff,),
    ).fetchall()

    # Group by (payee, category) → list of (year, month, day, amount)
    groups: dict[tuple, list[tuple[int, int, int, float]]] = defaultdict(list)
    for row in rows:
        try:
            d = date.fromisoformat(row["date"])
        except (ValueError, TypeError):
            continue
        key = (row["payee"] or "", row["category"] or "")
        groups[key].append((d.year, d.month, d.day, float(row["amount"])))

    patterns = []
    for (payee, category), entries in groups.items():
        if not payee and not category:
            continue

        # Merge entries by anchor day (±2 day tolerance)
        # anchor_day → list of (year, month, amount)
        anchor_buckets: dict[int, list[tuple[int, int, float]]] = {}
        for yr, mo, dom, amt in entries:
            placed = False
            for anchor in list(anchor_buckets.keys()):
                if abs(dom - anchor) <= 2:
                    anchor_buckets[anchor].append((yr, mo, amt))
                    placed = True
                    break
            if not placed:
                anchor_buckets[dom] = [(yr, mo, amt)]

        for anchor_day, bucket in anchor_buckets.items():
            # Count distinct (year, month) pairs
            months_seen = {(yr, mo) for yr, mo, _ in bucket}
            if len(months_seen) < 3:
                continue

            amounts = [amt for _, _, amt in bucket]
            avg = sum(amounts) / len(amounts)
            if avg == 0:
                continue

            # Check amount consistency (±15%)
            consistent = all(abs(a - avg) / abs(avg) <= 0.15 for a in amounts)
            if not consistent:
                continue

            patterns.append({
                "payee": payee,
                "category": category,
                "avg_amount": round(avg, 2),
                "day_of_month": anchor_day,
                "confidence": "pattern",
            })

    return patterns


def _project_item_dates(row, start: date, end: date) -> list[date]:
    """
    Project due dates for a recurring_items row between start (exclusive) and end.
    Only handles 'monthly' frequency; others fall back to day_of_month monthly.
    """
    freq = (row["frequency"] or "monthly").lower()
    dom = row["day_of_month"] or 1
    item_start = date.fromisoformat(row["start_date"]) if row["start_date"] else start

    if freq in ("monthly", ""):
        return _monthly_dates(dom, max(start, item_start), end)
    elif freq == "weekly":
        return _interval_dates(7, max(start, item_start), end)
    elif freq == "biweekly":
        return _interval_dates(14, max(start, item_start), end)
    elif freq in ("quarterly",):
        return _monthly_dates(dom, max(start, item_start), end, step=3)
    elif freq in ("annual", "yearly"):
        return _monthly_dates(dom, max(start, item_start), end, step=12)
    else:
        return _monthly_dates(dom, max(start, item_start), end)


def _monthly_dates(dom: int, after: date, end: date, step: int = 1) -> list[date]:
    """Yield monthly dates for a given day_of_month between after and end."""
    results = []
    current = date(after.year, after.month, 1)
    while current <= end:
        max_day = calendar.monthrange(current.year, current.month)[1]
        d = current.replace(day=min(dom, max_day))
        if after < d <= end:
            results.append(d)
        # Advance by `step` months
        m = current.month + step
        y = current.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        current = date(y, m, 1)
    return results


def _interval_dates(interval: int, after: date, end: date) -> list[date]:
    """Yield dates at fixed intervals starting just after `after`."""
    results = []
    d = after + timedelta(days=interval)
    while d <= end:
        results.append(d)
        d += timedelta(days=interval)
    return results


def _dates_for_pattern(dom: int, after: date, end: date) -> list[date]:
    return _monthly_dates(dom, after, end)


def _days_from_today(date_str: str) -> int:
    return (date.fromisoformat(date_str) - date.today()).days


def _build_narrative(
    balance: float,
    end_balance: float,
    total_in: float,
    total_out: float,
    risks: list[dict],
    days: int,
) -> str:
    direction = "increase" if end_balance > balance else "decrease"
    delta = abs(end_balance - balance)
    parts = [
        f"Over the next {days} days, your balance is projected to {direction} "
        f"by €{delta:,.0f} (from €{balance:,.0f} to €{end_balance:,.0f})."
    ]
    parts.append(
        f"Expected inflows total €{total_in:,.0f} and outflows total €{abs(total_out):,.0f}."
    )
    if risks:
        earliest = min(risks, key=lambda r: r["days_from_now"])
        parts.append(
            f"Warning: {len(risks)} overdraft risk(s) detected — "
            f"earliest on {earliest['date']} ({earliest['days_from_now']} days away)."
        )
    else:
        parts.append("No overdraft risks detected in the forecast period.")
    return " ".join(parts)
