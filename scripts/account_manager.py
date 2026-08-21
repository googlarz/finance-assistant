"""
Finance Assistant Account Manager.

Manages financial accounts (checking, savings, credit card, investment, loan, etc.)
stored as structured JSON in .finance/accounts/accounts.json.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

try:
    from finance_storage import get_accounts_path, load_json, save_json
    from currency import format_money
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import get_accounts_path, load_json, save_json
    from currency import format_money


def _db_available() -> bool:
    try:
        from db import is_initialized
        return is_initialized()
    except Exception:
        return False


ACCOUNT_TYPES = {
    "checking":    "Checking Account",
    "savings":     "Savings Account",
    "credit_card": "Credit Card",
    "investment":  "Investment Account",
    "brokerage":   "Brokerage Account",
    "loan":        "Loan",
    "mortgage":    "Mortgage",
    "wallet":      "Digital Wallet",
    "cash":        "Cash",
    "pension":     "Pension / Retirement",
    "other":       "Other",
}

ACCOUNT_SCHEMA = {
    "id": None,
    "name": None,
    "type": None,
    "institution": None,
    "currency": "EUR",
    "current_balance": 0.0,
    "as_of": None,
    "is_asset": True,
    "include_in_net_worth": True,
    "include_in_budget": True,
    "notes": "",
}


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "account"


def _load_accounts() -> list[dict]:
    data = load_json(get_accounts_path(), default={"accounts": []})
    return data.get("accounts", []) if isinstance(data, dict) else []


def _save_accounts(accounts: list[dict]) -> None:
    save_json(get_accounts_path(), {
        "last_updated": datetime.now().isoformat(),
        "accounts": accounts,
    })


# ── Public API ───────────────────────────────────────────────────────────────

_BOOL_COLUMNS = ("is_asset", "include_in_net_worth", "include_in_budget")


def _row_to_account(row) -> dict:
    """SQLite has no boolean type — these are stored as 0/1 INTEGER. Convert
    back to Python bool so callers doing `is True`/`is False` (as this
    module's own smoke test does) see the same type as the JSON path."""
    acc = dict(row)
    for col in _BOOL_COLUMNS:
        if col in acc and acc[col] is not None:
            acc[col] = bool(acc[col])
    return acc


def list_accounts() -> list[dict]:
    """List all accounts. Reads from SQLite if available, else JSON."""
    if _db_available():
        try:
            from db import get_conn
            with get_conn() as conn:
                rows = conn.execute("SELECT * FROM accounts ORDER BY name").fetchall()
            return [_row_to_account(r) for r in rows]
        except Exception:
            pass
    return _load_accounts()


def get_accounts() -> list[dict]:
    return list_accounts()


def get_account(account_id: str) -> Optional[dict]:
    """Get a single account by id. Reads from SQLite if available."""
    if _db_available():
        try:
            from db import get_conn
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM accounts WHERE id = ?", (account_id,)
                ).fetchone()
            if row:
                return _row_to_account(row)
        except Exception:
            pass
    for acc in _load_accounts():
        if acc["id"] == account_id:
            return acc
    return None


def add_account(account_data: dict) -> dict:
    accounts = _load_accounts()
    new = dict(ACCOUNT_SCHEMA)
    new.update(account_data)

    if not new["id"]:
        base = _slugify(new.get("name") or new.get("type") or "account")
        existing_ids = {a["id"] for a in accounts}
        slug = base
        counter = 2
        while slug in existing_ids:
            slug = f"{base}-{counter}"
            counter += 1
        new["id"] = slug

    if not new["as_of"]:
        new["as_of"] = datetime.now().date().isoformat()

    # Debts are liabilities
    if new["type"] in ("loan", "mortgage", "credit_card"):
        new["is_asset"] = False

    # Dual-write: SQLite then JSON backup
    if _db_available():
        try:
            from db import get_conn
            with get_conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO accounts
                       (id, name, type, current_balance, currency, institution,
                        is_asset, as_of, include_in_net_worth, include_in_budget,
                        notes, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        new["id"],
                        new["name"],
                        new["type"],
                        float(new.get("current_balance") or 0),
                        new.get("currency", "EUR"),
                        new.get("institution"),
                        int(bool(new.get("is_asset", True))),
                        new["as_of"],
                        int(bool(new.get("include_in_net_worth", True))),
                        int(bool(new.get("include_in_budget", True))),
                        new.get("notes"),
                        new["as_of"],
                    ),
                )
        except Exception:
            pass

    accounts.append(new)
    _save_accounts(accounts)
    return new


def update_balance(account_id: str, balance: float) -> Optional[dict]:
    """Update only the balance of an account. Dual-writes to SQLite + JSON."""
    now = datetime.now().date().isoformat()
    if _db_available():
        try:
            from db import get_conn
            with get_conn() as conn:
                conn.execute(
                    "UPDATE accounts SET current_balance = ?, updated_at = ? WHERE id = ?",
                    (round(balance, 2), now, account_id),
                )
        except Exception:
            pass
    return update_account(account_id, {"current_balance": round(balance, 2)})


# Columns SQLite actually has — only these can be dual-written; anything
# else in ACCOUNT_SCHEMA (e.g. "id") stays JSON-only.
_SQLITE_ACCOUNT_COLUMNS = {
    "name", "type", "current_balance", "currency", "institution",
    "is_asset", "include_in_net_worth", "include_in_budget", "notes",
}


def update_account(account_id: str, updates: dict) -> Optional[dict]:
    accounts = _load_accounts()
    for i, acc in enumerate(accounts):
        if acc["id"] == account_id:
            acc.update(updates)
            acc["as_of"] = datetime.now().date().isoformat()
            accounts[i] = acc
            # Dual-write to SQLite — any updated field SQLite has a column for,
            # not just current_balance (a rename/type change used to leave
            # SQLite permanently stale since only current_balance was mirrored).
            sqlite_updates = {k: v for k, v in updates.items() if k in _SQLITE_ACCOUNT_COLUMNS}
            if _db_available() and sqlite_updates:
                try:
                    from db import get_conn
                    set_clause = ", ".join(f"{k} = ?" for k in sqlite_updates)
                    values = [
                        int(bool(v)) if k in _BOOL_COLUMNS else v
                        for k, v in sqlite_updates.items()
                    ]
                    with get_conn() as conn:
                        conn.execute(
                            f"UPDATE accounts SET {set_clause}, as_of = ?, updated_at = ? WHERE id = ?",
                            (*values, acc["as_of"], acc["as_of"], account_id),
                        )
                except Exception:
                    pass
            _save_accounts(accounts)
            return acc
    return None


def delete_account(account_id: str) -> bool:
    accounts = _load_accounts()
    filtered = [a for a in accounts if a["id"] != account_id]
    if len(filtered) == len(accounts):
        return False
    if _db_available():
        try:
            from db import get_conn
            with get_conn() as conn:
                conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        except Exception:
            pass
    _save_accounts(filtered)
    return True


def get_total_balance(account_type: Optional[str] = None, currency: str = "EUR") -> dict:
    """Sum balances by asset/liability. Optionally filter by type."""
    accounts = _load_accounts()
    if account_type:
        accounts = [a for a in accounts if a["type"] == account_type]

    assets = 0.0
    liabilities = 0.0
    for acc in accounts:
        bal = float(acc.get("current_balance") or 0.0)
        if acc.get("is_asset", True):
            assets += bal
        else:
            liabilities += abs(bal)

    return {
        "assets": round(assets, 2),
        "liabilities": round(liabilities, 2),
        "net": round(assets - liabilities, 2),
        "account_count": len(accounts),
        "currency": currency,
    }


def display_accounts() -> str:
    accounts = _load_accounts()
    if not accounts:
        return "No accounts set up yet. Add your first account to get started."

    lines = ["═══ Your Accounts ═══\n"]

    by_type: dict[str, list[dict]] = {}
    for acc in accounts:
        t = acc.get("type", "other")
        by_type.setdefault(t, []).append(acc)

    total_assets = 0.0
    total_liabilities = 0.0

    for acc_type, accs in sorted(by_type.items()):
        label = ACCOUNT_TYPES.get(acc_type, acc_type)
        lines.append(f"  {label}:")
        for acc in accs:
            bal = float(acc.get("current_balance") or 0.0)
            cur = acc.get("currency", "EUR")
            formatted = format_money(bal, cur)
            is_asset = acc.get("is_asset", True)
            if is_asset:
                total_assets += bal
            else:
                total_liabilities += abs(bal)
            institution = f" ({acc['institution']})" if acc.get("institution") else ""
            lines.append(f"    {acc['name']}{institution}: {formatted}")
        lines.append("")

    lines.append(f"  Total assets:      {format_money(total_assets, 'EUR')}")
    lines.append(f"  Total liabilities: {format_money(total_liabilities, 'EUR')}")
    lines.append(f"  Net:               {format_money(total_assets - total_liabilities, 'EUR')}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing account_manager...")
    # Quick smoke test
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["FINANCE_PROJECT_DIR"] = tmpdir
        assert get_accounts() == []

        acc = add_account({"name": "DKB Checking", "type": "checking", "institution": "DKB", "current_balance": 5000})
        assert acc["id"] == "dkb-checking"
        assert acc["is_asset"] is True

        acc2 = add_account({"name": "VISA Card", "type": "credit_card", "institution": "DKB", "current_balance": -450})
        assert acc2["is_asset"] is False

        assert len(get_accounts()) == 2
        totals = get_total_balance()
        assert totals["assets"] == 5000.0
        assert totals["liabilities"] == 450.0

        print(display_accounts())

        delete_account("dkb-checking")
        assert len(get_accounts()) == 1

        del os.environ["FINANCE_PROJECT_DIR"]
        print("All account_manager tests passed.")
