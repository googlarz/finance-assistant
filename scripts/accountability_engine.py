# accountability_engine.py

"""
Accountability Engine — proactive nudges surfaced without being asked.

Checks five accountability domains:
  1. Budget pattern violations (category over-budget 3+ months in a row)
  2. Commitment follow-through (open journal commitments past due date)
  3. Goal drift (savings goal falling behind required monthly pace)
  4. Savings rate decline (3+ consecutive months dropping)
  5. Spending category creep (3-month avg up >20% vs prior 3 months)
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Optional


# ── Helpers ───────────────────────────────────────────────────────────────────

def _today() -> date:
    return date.today()


def _get_conn_ctx():
    """Return the get_conn context manager from db module."""
    import os
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from db import get_conn
    return get_conn


def _months_back(n: int, ref: Optional[date] = None) -> list[str]:
    """Return list of 'YYYY-MM' strings, most recent first, going back n months."""
    today = ref or _today()
    result = []
    year, month = today.year, today.month
    for _ in range(n):
        result.append(f"{year}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return result


# ── Check 1: Budget Pattern Violations ────────────────────────────────────────

def check_budget_patterns(conn: sqlite3.Connection) -> list[dict]:
    """Find categories over-budget 3+ consecutive months."""
    try:
        rows = conn.execute(
            """
            SELECT month, category, limit_amount, actual_amount
            FROM budget_categories
            WHERE limit_amount > 0
            ORDER BY category, month DESC
            """
        ).fetchall()
    except Exception:
        return []

    # Group by category
    by_cat: dict[str, list[tuple[str, float, float]]] = {}
    for row in rows:
        cat = row["category"]
        by_cat.setdefault(cat, []).append((row["month"], row["limit_amount"], row["actual_amount"]))

    alerts = []
    for cat, entries in by_cat.items():
        # entries already sorted month DESC; find longest consecutive streak of over-budget
        consecutive = 0
        streak_entries = []
        for month, limit_amt, actual_amt in entries:
            if actual_amt > limit_amt:
                consecutive += 1
                streak_entries.append((month, limit_amt, actual_amt))
            else:
                break  # streak broken (sorted DESC, so first non-over breaks it)

        if consecutive >= 3:
            overspend_pcts = [
                ((actual - limit) / limit * 100)
                for _, limit, actual in streak_entries
            ]
            avg_pct = sum(overspend_pcts) / len(overspend_pcts)
            avg_pct_r = round(avg_pct, 1)
            # Suggest new limit = avg actual rounded up to nearest 10
            avg_actual = sum(a for _, _, a in streak_entries) / len(streak_entries)
            suggested = round(avg_actual / 10 + 0.5) * 10

            alerts.append({
                "type": "budget_pattern",
                "category": cat,
                "months_over": consecutive,
                "avg_overspend_pct": avg_pct_r,
                "message": (
                    f"Your {cat} spending has been over budget {consecutive} months in a row "
                    f"— about {avg_pct_r}% over on average. That's starting to look like a "
                    f"habit rather than a one-off."
                ),
                "suggestion": (
                    f"Either raise the limit to around €{suggested:.0f} to reflect reality, "
                    f"or let's talk about what's driving it."
                ),
            })

    # Sort by months_over desc for deterministic ordering
    alerts.sort(key=lambda a: -a["months_over"])
    return alerts


# ── Check 2: Overdue Commitments ──────────────────────────────────────────────

def check_overdue_commitments(conn: sqlite3.Connection) -> list[dict]:
    """Find open journal commitments past their due date."""
    today = _today()
    try:
        rows = conn.execute(
            """
            SELECT title, due_date
            FROM journal_entries
            WHERE entry_type = 'commitment'
              AND status = 'open'
              AND due_date IS NOT NULL
              AND due_date < ?
            ORDER BY due_date ASC
            """,
            (today.isoformat(),),
        ).fetchall()
    except Exception:
        # Table may not exist yet
        return []

    alerts = []
    for row in rows:
        try:
            due = date.fromisoformat(row["due_date"])
        except (ValueError, TypeError):
            continue
        days_over = (today - due).days
        alerts.append({
            "type": "overdue_commitment",
            "title": row["title"],
            "due_date": row["due_date"],
            "days_overdue": days_over,
            "message": (
                f"You said you'd {row['title'].lower()} — that was due "
                f"{days_over} day{'s' if days_over != 1 else ''} ago. Still on the list?"
            ),
        })
    return alerts


# ── Check 3: Goal Drift ────────────────────────────────────────────────────────

def check_goal_drift(conn: sqlite3.Connection) -> list[dict]:
    """Find active savings goals falling more than 20% behind required monthly pace."""
    today = _today()
    try:
        rows = conn.execute(
            """
            SELECT id, name, target_amount, current_amount, target_date, created_at
            FROM goals
            WHERE status = 'active'
              AND target_date IS NOT NULL
            """
        ).fetchall()
    except Exception:
        return []

    alerts = []
    for row in rows:
        try:
            target_dt = date.fromisoformat(row["target_date"][:10])
            created_dt = date.fromisoformat(row["created_at"][:10])
        except (ValueError, TypeError):
            continue

        if target_dt <= today:
            continue  # already past deadline

        # Months since creation (at least 1 to avoid division by zero)
        months_elapsed = (
            (today.year - created_dt.year) * 12 + (today.month - created_dt.month)
        )
        months_elapsed = max(months_elapsed, 1)

        # Months remaining
        months_remaining = (
            (target_dt.year - today.year) * 12 + (target_dt.month - today.month)
        )
        if months_remaining <= 0:
            continue

        current = float(row["current_amount"] or 0)
        target = float(row["target_amount"])

        actual_monthly = current / months_elapsed
        needed_total = target - current
        required_monthly = needed_total / months_remaining

        if required_monthly <= 0:
            continue  # already fully funded

        # Only alert if more than 20% behind pace
        if actual_monthly >= required_monthly * 0.8:
            continue

        shortfall = required_monthly - actual_monthly
        alerts.append({
            "type": "goal_drift",
            "goal_name": row["name"],
            "required_monthly": round(required_monthly, 2),
            "actual_monthly": round(actual_monthly, 2),
            "months_remaining": months_remaining,
            "shortfall_per_month": round(shortfall, 2),
            "message": (
                f"Your '{row['name']}' goal is falling behind — you've been putting in "
                f"about €{actual_monthly:.0f}/month, but you need €{required_monthly:.0f}/month "
                f"to hit it in time. That's {months_remaining} months from now."
            ),
        })
    return alerts


# ── Check 4: Savings Rate Decline ─────────────────────────────────────────────

def check_savings_rate_trend(conn: sqlite3.Connection) -> list[dict]:
    """Detect if savings rate has been declining for 3+ consecutive months."""
    months = _months_back(6)

    try:
        earliest = months[-1] + "-01"
        rows = conn.execute(
            """
            SELECT strftime('%Y-%m', date) AS month,
                   SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS income,
                   SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) AS expenses
            FROM transactions
            WHERE date >= ?
              AND type NOT IN ('transfer', 'investment', 'debt_payment')
            GROUP BY month
            """,
            (earliest,),
        ).fetchall()
    except Exception:
        return []

    # Build month -> savings_rate map
    rate_by_month: dict[str, float] = {}
    for row in rows:
        ym = row["month"]
        income = float(row["income"] or 0)
        expenses = float(row["expenses"] or 0)
        if income > 0:
            rate_by_month[ym] = (income - expenses) / income

    # Need rates for last 6 months in chronological order (oldest first)
    ordered = list(reversed(months))  # oldest → newest
    rates = [rate_by_month.get(ym) for ym in ordered]

    # Find the longest consecutive declining streak ending at the most recent month
    # Walk from most recent backwards
    rates_newest_first = list(reversed(rates))
    months_declining = 0
    prev = None
    for r in rates_newest_first:
        if r is None:
            break
        if prev is None:
            prev = r
            continue
        if r > prev:
            # r is older, prev is newer — declining means newer < older
            months_declining += 1
            prev = r
        else:
            break

    if months_declining < 3:
        return []

    # Current rate = most recent non-None
    current_rate = next((r for r in rates_newest_first if r is not None), None)
    peak_rate = max((r for r in rates if r is not None), default=None)

    if current_rate is None or peak_rate is None:
        return []

    return [{
        "type": "savings_rate_decline",
        "months_declining": months_declining,
        "current_rate": round(current_rate, 4),
        "peak_rate": round(peak_rate, 4),
        "message": (
            f"Your savings rate has been drifting down {months_declining} months in a row — "
            f"you're at {current_rate*100:.1f}% now, compared to {peak_rate*100:.1f}% at the peak. "
            f"Worth understanding what changed."
        ),
    }]


# ── Check 5: Category Creep ───────────────────────────────────────────────────

def check_category_creep(conn: sqlite3.Connection) -> list[dict]:
    """Find categories where recent 3-month avg spending is >20% above prior 3-month avg."""
    months = _months_back(6)  # most recent first
    recent_months = set(months[:3])
    prior_months = set(months[3:])
    earliest = months[-1] + "-01"

    try:
        rows = conn.execute(
            """
            SELECT strftime('%Y-%m', date) AS month,
                   category,
                   SUM(ABS(amount)) AS total
            FROM transactions
            WHERE date >= ?
              AND amount < 0
              AND type NOT IN ('transfer', 'investment', 'debt_payment')
            GROUP BY month, category
            """,
            (earliest,),
        ).fetchall()
    except Exception:
        return []

    # Aggregate per category
    recent_by_cat: dict[str, list[float]] = {}
    prior_by_cat: dict[str, list[float]] = {}

    for row in rows:
        cat = row["category"] or "uncategorized"
        ym = row["month"]
        total = float(row["total"] or 0)
        if ym in recent_months:
            recent_by_cat.setdefault(cat, []).append(total)
        elif ym in prior_months:
            prior_by_cat.setdefault(cat, []).append(total)

    alerts = []
    all_cats = set(recent_by_cat) | set(prior_by_cat)
    for cat in all_cats:
        prior_vals = prior_by_cat.get(cat, [])
        recent_vals = recent_by_cat.get(cat, [])

        if not prior_vals:
            continue
        prior_avg = sum(prior_vals) / len(prior_vals)
        if prior_avg <= 20:
            continue  # ignore tiny categories

        if not recent_vals:
            continue
        recent_avg = sum(recent_vals) / len(recent_vals)

        if recent_avg <= prior_avg * 1.20:
            continue

        pct_increase = (recent_avg - prior_avg) / prior_avg * 100
        alerts.append({
            "type": "category_creep",
            "category": cat,
            "recent_avg": round(recent_avg, 2),
            "prior_avg": round(prior_avg, 2),
            "pct_increase": round(pct_increase, 1),
            "message": (
                f"Your {cat} spending has crept up {pct_increase:.0f}% — "
                f"averaging €{recent_avg:.0f}/month lately versus €{prior_avg:.0f}/month before. "
                f"Could be fine, but worth a look."
            ),
        })

    alerts.sort(key=lambda a: -a["pct_increase"])
    return alerts


# ── Main Entry Point ───────────────────────────────────────────────────────────

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

_TYPE_SEVERITY: dict[str, str] = {
    "overdue_commitment": "high",
    "budget_pattern": "medium",   # overridden to high for 4+ months below
    "goal_drift": "medium",
    "savings_rate_decline": "medium",
    "category_creep": "low",
}


def _assign_severity(alert: dict) -> str:
    t = alert["type"]
    if t == "budget_pattern":
        return "high" if alert["months_over"] >= 4 else "medium"
    return _TYPE_SEVERITY.get(t, "low")


def get_accountability_alerts(conn=None) -> list[dict]:
    """
    Run all accountability checks and return combined list sorted by severity.
    Priority: overdue_commitment > budget_pattern (months_over desc) > goal_drift
              > savings_rate_decline > category_creep
    """
    _type_priority = {
        "overdue_commitment": 0,
        "budget_pattern": 1,
        "goal_drift": 2,
        "savings_rate_decline": 3,
        "category_creep": 4,
    }

    def _run(c: sqlite3.Connection) -> list[dict]:
        alerts: list[dict] = []
        alerts.extend(check_overdue_commitments(c))
        alerts.extend(check_budget_patterns(c))
        alerts.extend(check_goal_drift(c))
        alerts.extend(check_savings_rate_trend(c))
        alerts.extend(check_category_creep(c))

        for a in alerts:
            a["severity"] = _assign_severity(a)

        alerts.sort(key=lambda a: (
            _SEVERITY_ORDER.get(a["severity"], 99),
            _type_priority.get(a["type"], 99),
            -a.get("months_over", 0),   # budget_pattern: more months = higher priority
        ))
        return alerts

    if conn is not None:
        return _run(conn)

    get_conn = _get_conn_ctx()
    with get_conn() as c:
        return _run(c)
