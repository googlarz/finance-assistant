"""
Finance Assistant Transaction Logger.

Logs income and expense transactions with auto-categorization and budget alerts.
Transactions are stored per-account per-year in .finance/accounts/transactions/.
"""

from __future__ import annotations

import re
import sys
import uuid
from datetime import datetime
from typing import Optional

try:
    from finance_storage import (
        get_transactions_path, load_json, save_json,
    )
    from currency import format_money
except ImportError:
    import os, sys as _sys
    _sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import get_transactions_path, load_json, save_json
    from currency import format_money


def _db_available() -> bool:
    """Check DB availability fresh each call.

    Previously this was cached for the session; if the cache was warmed before
    init_db() ran (e.g. a preview happened before _setup_db), SQLite was
    silently disabled for the rest of the session. is_initialized() is cheap.
    """
    try:
        from db import is_initialized
        return is_initialized()
    except Exception:
        return False


# ── Category definitions ─────────────────────────────────────────────────────

EXPENSE_CATEGORIES = {
    "housing":          "Housing (rent, mortgage, utilities)",
    "food":             "Food & Groceries",
    "dining":           "Dining & Restaurants",
    "transport":        "Transport (fuel, transit, car)",
    "insurance":        "Insurance Premiums",
    "healthcare":       "Healthcare & Medical",
    "education":        "Education & Training",
    "childcare":        "Childcare",
    "clothing":         "Clothing & Personal",
    "entertainment":    "Entertainment & Leisure",
    "subscriptions":    "Subscriptions & Memberships",
    "telecom":          "Phone, Internet & TV",
    "household":        "Household & Maintenance",
    "equipment":        "Equipment & Electronics",
    "gifts":            "Gifts & Donations",
    "travel":           "Travel & Vacation",
    "taxes":            "Taxes & Government Fees",
    "debt_payment":     "Debt Payments (beyond minimum)",
    "savings":          "Savings & Investments",
    "fees":             "Bank & Service Fees",
    "pets":             "Pets",
    "personal_care":    "Personal Care & Beauty",
    "other_expense":    "Other Expense",
}

INCOME_CATEGORIES = {
    "salary":           "Salary / Wages",
    "freelance":        "Freelance / Contract Income",
    "business":         "Business Income",
    "investment":       "Investment Income (dividends, interest)",
    "rental":           "Rental Income",
    "pension":          "Pension / Retirement Income",
    "benefits":         "Government Benefits",
    "gift_received":    "Gifts / Inheritance Received",
    "refund":           "Tax Refund",
    "other_income":     "Other Income",
}

ALL_CATEGORIES = {**EXPENSE_CATEGORIES, **INCOME_CATEGORIES}

TRANSACTION_SCHEMA = {
    "id": None,
    "date": None,
    "account_id": None,
    "type": None,                  # "income"|"expense"|"transfer"|"investment"|"debt_payment"
    "amount": None,
    "currency": None,
    "category": None,
    "subcategory": None,
    "description": None,
    "payee": None,
    "is_recurring": False,
    "tags": [],
    "tax_relevant": False,
    "tax_category": None,
    "business_use_pct": 100.0,
    "import_source": None,
    "import_ref": None,
}


# ── Auto-categorization ─────────────────────────────────────────────────────

_CATEGORY_KEYWORDS = {
    "housing": ["miete", "rent", "mortgage", "hypothek", "nebenkosten", "strom", "gas", "wasser", "utilities"],
    "food": ["rewe", "edeka", "aldi", "lidl", "penny", "netto", "kaufland", "grocery", "supermarket", "lebensmittel"],
    "dining": ["restaurant", "cafe", "lieferando", "uber eats", "deliveroo", "mcdonald", "starbucks", "gastronomie"],
    "transport": ["db ", "bahn", "bvg", "mvv", "tankstelle", "fuel", "petrol", "parking", "taxi", "uber", "bolt", "shell", "aral"],
    "insurance": ["versicherung", "insurance", "allianz", "huk", "ergo", "axa"],
    "healthcare": ["apotheke", "pharmacy", "arzt", "doctor", "zahnarzt", "dentist", "hospital", "krankenhaus"],
    "education": ["udemy", "coursera", "buch", "book", "kurs", "course", "schule", "university", "uni"],
    "childcare": ["kita", "kindergarten", "daycare", "babysitter"],
    "subscriptions": ["netflix", "spotify", "amazon prime", "disney", "youtube", "gym", "fitnessstudio"],
    "telecom": ["telekom", "vodafone", "o2", "1&1", "internet", "telefon", "phone"],
    "equipment": ["mediamarkt", "saturn", "apple", "amazon", "computer", "laptop"],
    "gifts": ["spende", "donation", "geschenk", "gift"],
    "travel": ["hotel", "airbnb", "booking", "flug", "flight", "ryanair", "lufthansa"],
    "salary": ["gehalt", "salary", "wages", "lohn"],
    "freelance": ["honorar", "invoice", "rechnung"],
    "investment": ["dividende", "dividend", "zinsen", "interest", "kapitalertrag"],
    "refund": ["erstattung", "refund", "rückzahlung"],
}


# Pre-compiled per-category patterns — built once at import, not on every call
_CATEGORY_PATTERNS: list[tuple[str, re.Pattern]] = [
    (cat, re.compile("|".join(re.escape(kw) for kw in kws), re.IGNORECASE))
    for cat, kws in _CATEGORY_KEYWORDS.items()
]


def auto_categorize(description: str, amount: float) -> tuple[str, Optional[str]]:
    """Guess category from description keywords. Returns (category, None)."""
    desc = description or ""
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(desc):
            return category, None
    return ("other_income" if amount > 0 else "other_expense"), None


# ── Transaction Storage ──────────────────────────────────────────────────────

def _load_transactions(account_id: str, year: int) -> list[dict]:
    data = load_json(get_transactions_path(account_id, year), default={"transactions": []})
    return data.get("transactions", []) if isinstance(data, dict) else []


def _save_transactions(account_id: str, year: int, transactions: list[dict]) -> None:
    save_json(get_transactions_path(account_id, year), {
        "account_id": account_id,
        "year": year,
        "last_updated": datetime.now().isoformat(),
        "transaction_count": len(transactions),
        "transactions": transactions,
    })


# ── Public API ───────────────────────────────────────────────────────────────

def add_transaction(
    date: str,
    type: str,
    amount: float,
    category: str,
    description: str,
    account_id: str = "default",
    currency: str = "EUR",
    **kwargs,
) -> dict:
    """Add a transaction. Returns the new transaction plus updated totals."""
    # Normalize date
    try:
        parsed = datetime.fromisoformat(date)
        year = parsed.year
    except (ValueError, TypeError):
        date = datetime.now().date().isoformat()
        year = datetime.now().year

    # Auto-categorize if category is unknown
    if category not in ALL_CATEGORIES:
        category, _ = auto_categorize(description, amount)

    # Infer type from amount sign if not explicit
    if type not in ("income", "expense", "transfer", "investment", "debt_payment"):
        type = "income" if amount > 0 else "expense"

    txn = dict(TRANSACTION_SCHEMA)
    txn.update({
        "id": str(uuid.uuid4()),  # full UUID — 8-char prefix had ~1.15% collision rate at 10k txns
        "date": date,
        "account_id": account_id,
        "type": type,
        "amount": round(amount, 2),
        "currency": currency,
        "category": category,
        "description": description,
    })
    txn.update(kwargs)

    # Dual-write: SQLite first, then JSON backup.
    # Use INSERT (not INSERT OR IGNORE) with explicit IntegrityError handling so
    # collisions cause an ID regeneration rather than silent data loss.
    if _db_available():
        import sqlite3
        from db import get_conn
        try:
            for attempt in range(2):
                try:
                    with get_conn() as conn:
                        conn.execute(
                            """INSERT INTO transactions
                               (id, account_id, date, amount, type, currency,
                                category, description, source, payee, created_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                txn["id"],
                                txn["account_id"],
                                txn["date"],
                                txn["amount"],
                                txn.get("type", "expense"),
                                txn["currency"],
                                txn.get("category"),
                                txn.get("description"),
                                txn.get("import_source", "manual"),
                                txn.get("payee"),
                                datetime.now().isoformat(),
                            ),
                        )
                    break  # success
                except sqlite3.IntegrityError:
                    # ID collision — regenerate once. A second collision against a
                    # fresh full UUID is statistically impossible; if it happens,
                    # surface it rather than swallowing the transaction.
                    if attempt == 0:
                        txn["id"] = str(uuid.uuid4())
                        continue
                    raise
        except Exception as exc:
            # SQLite write failure must not block JSON write, but DO surface it
            # so users learn about a degraded storage layer.
            print(
                f"[finance_assistant] SQLite write failed: {exc}",
                file=sys.stderr,
            )

    transactions = _load_transactions(account_id, year)
    transactions.append(txn)
    transactions.sort(key=lambda t: t.get("date", ""))
    _save_transactions(account_id, year, transactions)

    return {
        "transaction_added": txn,
        "display": _format_transaction_added(txn),
    }


def get_transactions(
    account_id: str = "default",
    year: Optional[int] = None,
    month: Optional[int] = None,
    category: Optional[str] = None,
    type: Optional[str] = None,
) -> list[dict]:
    """Retrieve filtered transactions. Reads from SQLite if available, else JSON."""
    year = year or datetime.now().year

    if _db_available():
        try:
            from db import get_conn
            clauses = ["account_id = ?", "date LIKE ?"]
            params: list = [account_id, f"{year}-%"]
            if month:
                clauses.append("date LIKE ?")
                params.append(f"{year}-{month:02d}-%")
            if category:
                clauses.append("category = ?")
                params.append(category)
            if type:
                # Type is stored as a column since schema v2; matches JSON path semantics
                # (transfer, investment, debt_payment work consistently across backends).
                clauses.append("type = ?")
                params.append(type)
            where = " AND ".join(clauses)
            with get_conn() as conn:
                rows = conn.execute(
                    f"SELECT * FROM transactions WHERE {where} ORDER BY date",
                    params,
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            print(
                f"[finance_assistant] SQLite read failed, falling back to JSON: {exc}",
                file=sys.stderr,
            )

    txns = _load_transactions(account_id, year)
    if month:
        txns = [t for t in txns if t.get("date", "")[5:7] == f"{month:02d}"]
    if category:
        txns = [t for t in txns if t.get("category") == category]
    if type:
        txns = [t for t in txns if t.get("type") == type]
    return txns


def get_totals(
    account_id: str = "default",
    year: Optional[int] = None,
    month: Optional[int] = None,
    group_by: str = "category",
) -> dict:
    """Return totals grouped by category or type."""
    txns = get_transactions(account_id=account_id, year=year, month=month)
    totals: dict = {}
    for t in txns:
        key = t.get(group_by, "other")
        if key not in totals:
            totals[key] = {"count": 0, "income": 0.0, "expense": 0.0, "net": 0.0}
        totals[key]["count"] += 1
        amt = float(t.get("amount", 0))
        if amt >= 0:
            totals[key]["income"] += amt
        else:
            totals[key]["expense"] += abs(amt)
        totals[key]["net"] += amt

    for key in totals:
        for field in ("income", "expense", "net"):
            totals[key][field] = round(totals[key][field], 2)

    return totals


def get_summary_display(
    account_id: str = "default",
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> str:
    """Return a formatted transaction summary."""
    year = year or datetime.now().year
    totals = get_totals(account_id=account_id, year=year, month=month)
    if not totals:
        period = f"{year}-{month:02d}" if month else str(year)
        return f"No transactions logged for {period}."

    period = f"{year}-{month:02d}" if month else str(year)
    lines = [f"Transaction summary for {period}\n"]

    total_income = 0.0
    total_expense = 0.0

    for cat, data in sorted(totals.items()):
        label = ALL_CATEGORIES.get(cat, cat)[:35]
        if data["income"] > 0:
            total_income += data["income"]
            lines.append(f"  + {label:<35} {data['count']:>3} txns  +{format_money(data['income'], 'EUR')}")
        if data["expense"] > 0:
            total_expense += data["expense"]
            lines.append(f"  - {label:<35} {data['count']:>3} txns  -{format_money(data['expense'], 'EUR')}")

    lines.append(f"\n  Total income:   +{format_money(total_income, 'EUR')}")
    lines.append(f"  Total expenses: -{format_money(total_expense, 'EUR')}")
    lines.append(f"  Net:            {format_money(total_income - total_expense, 'EUR')}")

    return "\n".join(lines)


def _format_transaction_added(txn: dict) -> str:
    amt = float(txn.get("amount", 0))
    cur = txn.get("currency", "EUR")
    sign = "+" if amt >= 0 else ""
    label = ALL_CATEGORIES.get(txn.get("category", ""), txn.get("category", ""))
    return (
        f"Transaction logged: {txn['description']}\n"
        f"  {sign}{format_money(amt, cur)}  |  {label}\n"
        f"  Date: {txn['date']}  |  Account: {txn['account_id']}"
    )


def deduplicate(new_transactions: list[dict], existing_transactions: list[dict]) -> list[dict]:
    """Remove likely duplicates based on date + amount + description.
    Uses SQLite EXISTS check when DB is available (faster); falls back to in-memory set.
    """
    if _db_available():
        try:
            from db import get_conn
            unique = []
            with get_conn() as conn:
                for t in new_transactions:
                    txn_id = t.get("id", "")
                    if txn_id:
                        exists = conn.execute(
                            "SELECT 1 FROM transactions WHERE id = ? LIMIT 1", (txn_id,)
                        ).fetchone()
                        if not exists:
                            unique.append(t)
                    else:
                        # Fall back to date+amount+description key
                        key_date = t.get("date", "")
                        key_amt = round(float(t.get("amount", 0)), 2)
                        key_desc = (t.get("description") or "").lower()[:50]
                        exists = conn.execute(
                            """SELECT 1 FROM transactions
                               WHERE date=? AND amount=? AND LOWER(SUBSTR(description,1,50))=?
                               LIMIT 1""",
                            (key_date, key_amt, key_desc),
                        ).fetchone()
                        if not exists:
                            unique.append(t)
            return unique
        except Exception as exc:
            print(
                f"[finance_assistant] SQLite dedup failed, using in-memory fallback: {exc}",
                file=sys.stderr,
            )

    existing_keys = set()
    for t in existing_transactions:
        key = (t.get("date"), round(float(t.get("amount", 0)), 2), (t.get("description") or "").lower()[:50])
        existing_keys.add(key)

    unique = []
    for t in new_transactions:
        key = (t.get("date"), round(float(t.get("amount", 0)), 2), (t.get("description") or "").lower()[:50])
        if key not in existing_keys:
            unique.append(t)
            existing_keys.add(key)

    return unique
