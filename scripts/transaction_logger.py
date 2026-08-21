"""
Finance Assistant Transaction Logger.

Logs income and expense transactions with auto-categorization and budget alerts.
Transactions are stored per-account per-year in .finance/accounts/transactions/.
"""

from __future__ import annotations

import json
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
    "transfer_peer_id": None,   # id of the matching leg in a linked transfer pair (#8)
}

# Types that move money between the user's own accounts/net-worth buckets
# rather than into or out of it — excluded from income/spending analytics.
# See issue #7: engines were classifying flows by amount sign alone, so a
# correctly-typed transfer still counted as spending/income.
NON_FLOW_TYPES = {"transfer", "investment", "debt_payment"}


def is_income_flow(txn: dict) -> bool:
    """True if a transaction counts as income for flow analytics (budgets,
    forecasts, summaries). Sign is only used as a fallback when type is missing."""
    t = txn.get("type")
    if t in NON_FLOW_TYPES:
        return False
    if t == "income":
        return True
    if not t:
        return float(txn.get("amount", 0) or 0) > 0
    return False


def is_expense_flow(txn: dict) -> bool:
    """True if a transaction counts as spending for flow analytics. Sign is
    only used as a fallback when type is missing."""
    t = txn.get("type")
    if t in NON_FLOW_TYPES:
        return False
    if t == "expense":
        return True
    if not t:
        return float(txn.get("amount", 0) or 0) < 0
    return False


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


def _row_to_transaction(row) -> dict:
    """SQLite has no list/boolean type — tags is stored JSON-encoded and
    is_recurring/tax_relevant as 0/1 INTEGER. Convert back so a SQLite-sourced
    transaction looks identical to a JSON-sourced one."""
    txn = dict(row)
    if "tags" in txn:
        try:
            txn["tags"] = json.loads(txn["tags"]) if txn["tags"] else []
        except (TypeError, ValueError):
            txn["tags"] = []
    for col in ("is_recurring", "tax_relevant"):
        if col in txn and txn[col] is not None:
            txn[col] = bool(txn[col])
    return txn


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
                                category, description, source, payee, subcategory,
                                transfer_peer_id, is_recurring, tags, tax_relevant,
                                tax_category, business_use_pct, import_ref, created_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                                txn.get("subcategory"),
                                txn.get("transfer_peer_id"),
                                int(bool(txn.get("is_recurring"))),
                                json.dumps(txn.get("tags") or []),
                                int(bool(txn.get("tax_relevant"))),
                                txn.get("tax_category"),
                                txn.get("business_use_pct"),
                                txn.get("import_ref"),
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

    # Audit log — best-effort, must never block
    try:
        from audit_log import log_mutation
        log_mutation(
            action="create",
            target="transaction",
            target_id=txn["id"],
            after={
                "date": txn["date"],
                "amount": txn["amount"],
                "category": txn.get("category"),
                "description": (txn.get("description") or "")[:80],
                "account_id": txn["account_id"],
            },
            source=txn.get("import_source", "manual"),
        )
    except Exception:
        pass

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
            return [_row_to_transaction(r) for r in rows]
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


def _account_currency(account_id: str) -> str:
    try:
        from account_manager import get_account
        acc = get_account(account_id)
        if acc:
            return acc.get("currency", "EUR")
    except Exception:
        pass
    return "EUR"


def get_totals(
    account_id: str = "default",
    year: Optional[int] = None,
    month: Optional[int] = None,
    group_by: str = "category",
) -> dict:
    """Return totals grouped by category or type, converted to the account's
    own currency.

    Regression fix: this used to sum transaction amounts ignoring each
    row's currency field entirely — a USD statement imported into an EUR
    account had its dollar amounts counted as euros with no conversion.
    """
    txns = get_transactions(account_id=account_id, year=year, month=month)
    target_currency = _account_currency(account_id)
    totals: dict = {}
    for t in txns:
        key = t.get(group_by, "other")
        if key not in totals:
            totals[key] = {"count": 0, "income": 0.0, "expense": 0.0, "net": 0.0}
        totals[key]["count"] += 1
        amt = float(t.get("amount", 0))
        txn_currency = t.get("currency") or target_currency
        if txn_currency != target_currency:
            try:
                from currency import convert
                amt, _confidence = convert(amt, txn_currency, target_currency)
            except Exception:
                pass  # fall back to raw amount rather than dropping the transaction
        if is_income_flow(t):
            totals[key]["income"] += amt
        elif is_expense_flow(t):
            totals[key]["expense"] += abs(amt)
        totals[key]["net"] += amt

    for key in totals:
        for field in ("income", "expense", "net"):
            totals[key][field] = round(totals[key][field], 2)

    return totals


# Columns updatable via update_transaction_fields — deliberately narrow so
# callers can't accidentally rewrite amount/date/account_id through this path.
_UPDATABLE_FIELDS = {"type", "category", "subcategory", "transfer_peer_id"}


def update_transaction_fields(account_id: str, year: int, txn_id: str, updates: dict) -> bool:
    """Update a subset of fields on an existing transaction (both SQLite and
    JSON). Used by transfer detection/linking (#8) — not a general editor.

    Returns True if a matching transaction was found and updated.
    """
    updates = {k: v for k, v in updates.items() if k in _UPDATABLE_FIELDS}
    if not updates:
        return False

    updated = False

    if _db_available():
        try:
            from db import get_conn
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            with get_conn() as conn:
                cur = conn.execute(
                    f"UPDATE transactions SET {set_clause} WHERE id = ?",
                    (*updates.values(), txn_id),
                )
                updated = cur.rowcount > 0
        except Exception as exc:
            print(f"[finance_assistant] SQLite update failed: {exc}", file=sys.stderr)

    transactions = _load_transactions(account_id, year)
    for t in transactions:
        if t.get("id") == txn_id:
            t.update(updates)
            _save_transactions(account_id, year, transactions)
            updated = True
            break

    return updated


def delete_transaction(account_id: str, txn_id: str) -> bool:
    """Delete a single transaction by id (both stores).

    Regression fix: no delete_transaction existed anywhere — SKILL.md's
    documented workaround ("delete the account and re-import") relied on
    account_manager.delete_account(), which was itself a no-op before
    Phase 1's fix, and even correctly deleting the whole account was
    always a nuclear option for one bad row.

    The JSON side doesn't know which year the transaction is in, so it
    searches every {account_id}_*.json file and stops at the first match.
    """
    deleted = False

    if _db_available():
        try:
            from db import get_conn
            with get_conn() as conn:
                cur = conn.execute(
                    "DELETE FROM transactions WHERE id = ? AND account_id = ?",
                    (txn_id, account_id),
                )
                deleted = cur.rowcount > 0
        except Exception as exc:
            print(f"[finance_assistant] SQLite delete failed: {exc}", file=sys.stderr)

    from finance_storage import ensure_subdir
    txn_dir = ensure_subdir("accounts", "transactions")
    for f in sorted(txn_dir.glob(f"{account_id}_*.json")):
        transactions = load_json(f, default={"transactions": []}).get("transactions", [])
        filtered = [t for t in transactions if t.get("id") != txn_id]
        if len(filtered) != len(transactions):
            save_json(f, {
                "account_id": account_id,
                "last_updated": datetime.now().isoformat(),
                "transaction_count": len(filtered),
                "transactions": filtered,
            })
            deleted = True
            break

    if deleted:
        try:
            from audit_log import log_mutation
            log_mutation(action="delete", target="transaction", target_id=txn_id,
                         source="delete_transaction", metadata={"account_id": account_id})
        except Exception:
            pass

    return deleted


def unlink_transfer_pair(account_id: str, txn_id: str, year: int) -> bool:
    """Clear transfer_peer_id on a wrongly-linked transfer pair — the leg
    at (account_id, year, txn_id) AND whatever it was linked to. Does not
    change the transaction's type; use update_transaction_fields for that.
    """
    txns = get_transactions(account_id=account_id, year=year)
    txn = next((t for t in txns if t.get("id") == txn_id), None)
    if not txn:
        return False

    peer_id = txn.get("transfer_peer_id")
    ok_a = update_transaction_fields(account_id, year, txn_id, {"transfer_peer_id": None})

    if peer_id:
        # Peer may be in a different account/year — search for it.
        try:
            from account_manager import list_accounts
            for acc in list_accounts():
                for search_year in (year - 1, year, year + 1):
                    peer_txns = get_transactions(account_id=acc["id"], year=search_year)
                    if any(t.get("id") == peer_id for t in peer_txns):
                        update_transaction_fields(acc["id"], search_year, peer_id, {"transfer_peer_id": None})
                        break
        except Exception:
            pass

    return ok_a


def delete_import(import_ref: str) -> dict:
    """Undo an entire import in one call — deletes every transaction
    stamped with this import_ref, across every account. import_router.py
    and llm_import.py generate one shared import_ref per non-dry-run
    import() call and return it in the result dict as result['import_ref'].
    """
    from account_manager import list_accounts

    deleted_count = 0
    for acc in list_accounts():
        account_id = acc["id"]
        matching_ids = set()
        if _db_available():
            try:
                from db import get_conn
                with get_conn() as conn:
                    rows = conn.execute(
                        "SELECT id FROM transactions WHERE account_id = ? AND import_ref = ?",
                        (account_id, import_ref),
                    ).fetchall()
                matching_ids.update(r["id"] for r in rows)
            except Exception:
                pass

        from finance_storage import ensure_subdir
        txn_dir = ensure_subdir("accounts", "transactions")
        for f in txn_dir.glob(f"{account_id}_*.json"):
            transactions = load_json(f, default={"transactions": []}).get("transactions", [])
            matching_ids.update(t["id"] for t in transactions if t.get("import_ref") == import_ref)

        for txn_id in matching_ids:
            if delete_transaction(account_id, txn_id):
                deleted_count += 1

    return {"import_ref": import_ref, "deleted_count": deleted_count}


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


def deduplicate(
    new_transactions: list[dict],
    existing_transactions: list[dict],
    account_id: Optional[str] = None,
) -> list[dict]:
    """Remove likely duplicates based on date + amount + description.
    Uses SQLite EXISTS check when DB is available (faster); falls back to in-memory set.

    account_id, when passed, scopes the fallback-key match to that account
    (both stores). Regression fix: the SQLite branch's fallback-key query
    used to have no account_id clause at all — it deduped GLOBALLY across
    every account, so an identical amount+description in a DIFFERENT
    account (e.g. the same rent split across two people's accounts, or
    matching card charges) was wrongly dropped as a duplicate. The JSON
    branch was already effectively per-account (existing_transactions is
    caller-supplied, already scoped), so this only changes SQLite's
    behavior to match.
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
                        target_account = account_id or t.get("account_id")
                        if target_account:
                            exists = conn.execute(
                                """SELECT 1 FROM transactions
                                   WHERE date=? AND amount=? AND LOWER(SUBSTR(description,1,50))=?
                                     AND account_id=?
                                   LIMIT 1""",
                                (key_date, key_amt, key_desc, target_account),
                            ).fetchone()
                        else:
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
