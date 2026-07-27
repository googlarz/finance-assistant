"""
Finance Assistant Budget Engine.

Create, track, and analyze budgets with variance reporting.
Supports monthly and annual budgets with category-level tracking.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

try:
    from finance_storage import get_budget_path, load_json, save_json
    from transaction_logger import get_totals as get_transaction_totals, get_transactions, EXPENSE_CATEGORIES, is_expense_flow
    from currency import format_money
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import get_budget_path, load_json, save_json
    from transaction_logger import get_totals as get_transaction_totals, get_transactions, EXPENSE_CATEGORIES, is_expense_flow
    from currency import format_money


_DB_AVAILABLE: Optional[bool] = None


def _db_available() -> bool:
    global _DB_AVAILABLE
    if _DB_AVAILABLE is None:
        try:
            from db import is_initialized
            _DB_AVAILABLE = is_initialized()
        except Exception:
            _DB_AVAILABLE = False
    return _DB_AVAILABLE


BUDGET_METHODS = {
    "custom":      "Custom category limits",
    "50-30-20":    "50% needs, 30% wants, 20% savings",
    "zero-based":  "Every dollar has a job (income - expenses = 0)",
    "envelope":    "Fixed envelopes per category",
    "80-20":       "80% spending, 20% savings",
}

# 50-30-20 category classification
NEEDS_CATEGORIES = {"housing", "food", "transport", "insurance", "healthcare", "childcare", "telecom", "taxes"}
WANTS_CATEGORIES = {"dining", "entertainment", "subscriptions", "clothing", "travel", "personal_care", "gifts", "pets"}
SAVINGS_CATEGORIES = {"savings", "debt_payment"}


# ── Public API ───────────────────────────────────────────────────────────────

def create_budget(
    year: int,
    month: Optional[int] = None,
    method: str = "custom",
    income_target: Optional[float] = None,
    category_limits: Optional[dict] = None,
    currency: str = "EUR",
) -> dict:
    """Create a new budget. Returns the budget dict."""
    budget = {
        "created_at": datetime.now().isoformat(),
        "year": year,
        "month": month,
        "method": method,
        "currency": currency,
        "income_target": income_target or 0.0,
        "category_limits": category_limits or {},
        "actuals": {},
    }

    # Auto-generate limits for 50-30-20
    if method == "50-30-20" and income_target:
        needs = income_target * 0.50
        wants = income_target * 0.30
        savings = income_target * 0.20
        budget["method_breakdown"] = {
            "needs": round(needs, 2),
            "wants": round(wants, 2),
            "savings": round(savings, 2),
        }
        if not category_limits:
            budget["category_limits"] = _distribute_50_30_20(income_target)

    elif method == "80-20" and income_target:
        budget["method_breakdown"] = {
            "spending": round(income_target * 0.80, 2),
            "savings": round(income_target * 0.20, 2),
        }

    # Dual-write: upsert category rows to SQLite, then write JSON backup
    if _db_available():
        try:
            from db import get_conn
            month_key = f"{year}-{month:02d}" if month else str(year)
            limits = budget.get("category_limits", {})
            with get_conn() as conn:
                for cat, limit_val in limits.items():
                    conn.execute(
                        """INSERT INTO budget_categories
                           (month, category, limit_amount, actual_amount, currency)
                           VALUES (?, ?, ?, 0, ?)
                           ON CONFLICT(month, category) DO UPDATE SET
                               limit_amount = excluded.limit_amount,
                               currency = excluded.currency""",
                        (month_key, cat, float(limit_val), currency),
                    )
        except Exception as exc:
            import sys
            print(f"Warning: budget SQLite write failed (JSON backup still saved): {exc}", file=sys.stderr)

    save_json(get_budget_path(year, month), budget)
    return budget


def get_budget(year: int, month: Optional[int] = None) -> Optional[dict]:
    """Load budget. Reads from SQLite if available, reconstructs dict; else JSON."""
    if _db_available():
        try:
            from db import get_conn
            month_key = f"{year}-{month:02d}" if month else str(year)
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM budget_categories WHERE month = ?", (month_key,)
                ).fetchall()
            if rows:
                limits = {r["category"]: r["limit_amount"] for r in rows}
                actuals = {
                    r["category"]: {"spent": r["actual_amount"], "earned": 0.0, "count": 0}
                    for r in rows
                }
                currency = rows[0]["currency"] if rows else "EUR"
                return {
                    "year": year,
                    "month": month,
                    "method": "custom",
                    "currency": currency,
                    "income_target": 0.0,
                    "category_limits": limits,
                    "actuals": actuals,
                }
        except Exception as exc:
            import sys
            print(f"Warning: budget SQLite read failed, falling back to JSON: {exc}", file=sys.stderr)
    return load_json(get_budget_path(year, month))


def update_actual(month: str, category: str, amount: float) -> bool:
    """Update actual_amount for a budget category row in SQLite + JSON.
    month: 'YYYY-MM' or 'YYYY'
    Returns True on success.
    """
    if _db_available():
        try:
            from db import get_conn
            with get_conn() as conn:
                conn.execute(
                    """UPDATE budget_categories
                       SET actual_amount = ?
                       WHERE month = ? AND category = ?""",
                    (round(amount, 2), month, category),
                )
            return True
        except Exception as exc:
            import sys
            print(f"Warning: budget actual update failed for '{category}': {exc}", file=sys.stderr)
    return False


def get_variance(month: str) -> list[dict]:
    """Return limit vs actual per category for a month key ('YYYY-MM' or 'YYYY').
    Reads from SQLite if available, else falls back to get_budget_variance.
    """
    if _db_available():
        try:
            from db import get_conn
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM budget_categories WHERE month = ? ORDER BY category",
                    (month,),
                ).fetchall()
            return [
                {
                    "category": r["category"],
                    "limit": r["limit_amount"],
                    "actual": r["actual_amount"],
                    "variance": round(r["limit_amount"] - r["actual_amount"], 2),
                    "pct_used": round(r["actual_amount"] / r["limit_amount"] * 100, 1) if r["limit_amount"] > 0 else (None if r["actual_amount"] > 0 else 0),
                    "status": "unbudgeted" if r["limit_amount"] == 0 and r["actual_amount"] > 0 else (
                        "over" if r["actual_amount"] > r["limit_amount"] > 0 else
                        ("warn" if r["actual_amount"] > r["limit_amount"] * 0.85 > 0 else "under")
                    ),
                }
                for r in rows
            ]
        except Exception as exc:
            import sys
            print(f"Warning: budget variance SQLite read failed, falling back to JSON: {exc}", file=sys.stderr)
    # JSON fallback: parse the month key
    parts = month.split("-")
    year = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else None
    result = get_budget_variance(year, m)
    cats = result.get("categories", {})
    return [
        {"category": c, "limit": v["planned"], "actual": v["actual"],
         "variance": v["variance"], "pct_used": v["pct_used"]}
        for c, v in cats.items()
    ]


def update_budget_actuals(
    year: int,
    month: Optional[int] = None,
    account_id: str = "default",
) -> dict:
    """Refresh actuals from transaction log. Returns updated budget."""
    budget = get_budget(year, month)
    if not budget:
        return {"error": f"No budget found for {year}" + (f"-{month:02d}" if month else "")}

    totals = get_transaction_totals(account_id=account_id, year=year, month=month)
    actuals = {}
    for cat, data in totals.items():
        actuals[cat] = {
            "spent": data.get("expense", 0.0),
            "earned": data.get("income", 0.0),
            "count": data.get("count", 0),
        }

    budget["actuals"] = actuals
    budget["last_refreshed"] = datetime.now().isoformat()
    save_json(get_budget_path(year, month), budget)
    return budget


def get_budget_variance(year: int, month: Optional[int] = None) -> dict:
    """Compare planned vs actual. Returns variance by category."""
    budget = get_budget(year, month)
    if not budget:
        return {"error": "No budget found"}

    limits = budget.get("category_limits", {})
    actuals = budget.get("actuals", {})
    variance = {}

    all_cats = set(limits.keys()) | set(actuals.keys())
    for cat in sorted(all_cats):
        planned = float(limits.get(cat, 0))
        actual_data = actuals.get(cat, {})
        spent = float(actual_data.get("spent", 0)) if isinstance(actual_data, dict) else float(actual_data)
        diff = planned - spent
        if planned == 0 and spent > 0:
            status = "unbudgeted"
            pct_used = None
        elif planned > 0:
            pct_used = round(spent / planned * 100, 1)
            status = "over" if spent > planned else ("warn" if spent > planned * 0.85 else "under")
        else:
            pct_used = 0
            status = "on_budget"
        variance[cat] = {
            "planned": round(planned, 2),
            "actual": round(spent, 2),
            "variance": round(diff, 2),
            "pct_used": pct_used,
            "status": status,
        }

    total_planned = sum(float(limits.get(c, 0)) for c in limits)
    total_actual = sum(
        float(actuals[c].get("spent", 0)) if isinstance(actuals.get(c), dict) else 0
        for c in actuals
    )

    return {
        "year": year,
        "month": month,
        "method": budget.get("method"),
        "income_target": budget.get("income_target"),
        "total_planned": round(total_planned, 2),
        "total_actual": round(total_actual, 2),
        "total_variance": round(total_planned - total_actual, 2),
        "categories": variance,
        "overspend_categories": [c for c, v in variance.items() if v["status"] == "over"],
        "underspend_categories": [c for c, v in variance.items() if v["status"] == "under" and v["variance"] > 50],
    }


def suggest_budget_from_history(
    account_id: str = "default",
    year: Optional[int] = None,
    months_back: int = 3,
) -> dict:
    """Suggest category limits based on recent spending history."""
    year = year or datetime.now().year
    current_month = datetime.now().month

    # Collect needed (year, month) pairs
    needed: list[tuple[int, int]] = []
    for offset in range(months_back):
        m = current_month - offset
        y = year
        if m <= 0:
            m += 12
            y -= 1
        needed.append((y, m))

    # Load each distinct year's transactions once (1-2 reads vs months_back reads)
    year_txns: dict[int, list[dict]] = {}
    for y in {y for y, _ in needed}:
        year_txns[y] = get_transactions(account_id=account_id, year=y)

    all_totals: dict = {}
    months_counted = 0

    for y, m in needed:
        month_str = f"{m:02d}"
        txns = [t for t in year_txns[y] if t.get("date", "")[5:7] == month_str]
        if not txns:
            continue
        months_counted += 1
        for t in txns:
            if is_expense_flow(t):
                cat = t.get("category") or "other_expense"
                all_totals[cat] = all_totals.get(cat, 0.0) + abs(float(t.get("amount", 0)))

    if months_counted == 0:
        return {"error": "No transaction history found for suggestion."}

    suggested = {}
    for cat, total in sorted(all_totals.items()):
        avg = total / months_counted
        # Round up to nearest 10 for a comfortable buffer
        suggested[cat] = round(((avg + 9) // 10) * 10, 2)

    return {
        "based_on_months": months_counted,
        "suggested_limits": suggested,
        "total_suggested": round(sum(suggested.values()), 2),
    }


def format_budget_display(budget: dict) -> str:
    """Format budget for display."""
    if "error" in budget:
        return budget["error"]

    year = budget.get("year")
    month = budget.get("month")
    method = BUDGET_METHODS.get(budget.get("method", ""), budget.get("method", ""))
    period = f"{year}-{month:02d}" if month else str(year)

    lines = [
        f"Budget for {period}",
        f"Method: {method}",
        f"Income target: {format_money(budget.get('income_target', 0), budget.get('currency', 'EUR'))}",
        "",
    ]

    limits = budget.get("category_limits", {})
    actuals = budget.get("actuals", {})

    if limits:
        lines.append(f"{'Category':<25} {'Planned':>10} {'Actual':>10} {'Remaining':>10}")
        lines.append("-" * 58)
        for cat in sorted(limits.keys()):
            planned = float(limits[cat])
            actual_data = actuals.get(cat, {})
            spent = float(actual_data.get("spent", 0)) if isinstance(actual_data, dict) else 0
            remaining = planned - spent
            flag = " (!)" if remaining < 0 else ""
            lines.append(
                f"  {cat:<23} {planned:>10,.0f} {spent:>10,.0f} {remaining:>10,.0f}{flag}"
            )

    if budget.get("method_breakdown"):
        lines.append("")
        lines.append("Method breakdown:")
        for key, val in budget["method_breakdown"].items():
            lines.append(f"  {key}: {format_money(val, budget.get('currency', 'EUR'))}")

    return "\n".join(lines)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _distribute_50_30_20(monthly_income: float) -> dict:
    """Auto-distribute income into needs/wants/savings categories."""
    needs_budget = monthly_income * 0.50
    wants_budget = monthly_income * 0.30
    savings_budget = monthly_income * 0.20

    limits = {}
    # Distribute needs proportionally
    needs_list = [c for c in NEEDS_CATEGORIES if c in EXPENSE_CATEGORIES]
    if needs_list:
        per_need = needs_budget / len(needs_list)
        for c in needs_list:
            limits[c] = round(per_need, 2)

    wants_list = [c for c in WANTS_CATEGORIES if c in EXPENSE_CATEGORIES]
    if wants_list:
        per_want = wants_budget / len(wants_list)
        for c in wants_list:
            limits[c] = round(per_want, 2)

    limits["savings"] = round(savings_budget, 2)
    return limits
