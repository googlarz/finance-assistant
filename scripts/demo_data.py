"""
Demo data seeder for Finance Assistant.

Creates a realistic sample dataset for "Alex" — a Berlin-based renter.
Idempotent: skips if demo data already exists (detected by "DKB Demo" account).
"""

from __future__ import annotations

import os
import sys
import random

# Ensure scripts/ is importable when run standalone
sys.path.insert(0, os.path.dirname(__file__))

from profile_manager import update_profile, get_profile
from account_manager import list_accounts, add_account, delete_account
from transaction_logger import add_transaction
from goal_tracker import add_goal, delete_goal
from debt_optimizer import add_debt, delete_debt
from investment_tracker import add_holding, delete_holding

# Deterministic IDs seeded by _seed_accounts/_seed_goals/_seed_debts/
# _seed_investments — the single source of truth for what wipe_demo_data()
# removes, so seed and wipe can never drift out of sync.
DEMO_ACCOUNT_IDS = ("dkb-demo", "ing-savings-demo", "scalable-depot-demo")
DEMO_GOAL_IDS = ("demo-emergency-fund", "demo-japan-trip")
DEMO_DEBT_IDS = ("demo-credit-card",)
DEMO_HOLDING_IDS = ("demo-world-etf",)
# Descriptions the seed writes — lets wipe recognise rows seeded before they
# were tagged import_source="demo" (installs from v4.0.x and earlier).
DEMO_DESCRIPTIONS = {"Salary Alex", "Miete Berlin", "REWE Einkauf", "BVG Ticket",
                     "Restaurant & Café", "Streaming & Cloud Abo", "Misc Ausgaben"}


def seed_demo_data() -> bool:
    """Seed demo data. Returns True if seeded, False if already exists."""
    # Idempotency check
    accounts = list_accounts()
    if any(a.get("name") == "DKB Demo" for a in accounts):
        return False

    _seed_profile()
    account_ids = _seed_accounts()
    _seed_transactions(account_ids["checking"])
    _seed_goals(account_ids["savings"])
    _seed_debts()
    _seed_investments(account_ids["depot"])
    return True


def _seed_profile() -> None:
    update_profile({
        "personal": {"name": "Alex"},
        "employment": {"annual_gross": 58000},
        "housing": {"type": "renter", "monthly_cost": 1100, "city": "Berlin"},
        "tax_profile": {"filing_status": "single"},
        "meta": {"country": "DE", "locale": "de", "created": True},
    })


def _seed_accounts() -> dict:
    checking = add_account({
        "id": DEMO_ACCOUNT_IDS[0],
        "name": "DKB Demo",
        "type": "checking",
        "current_balance": 4200.0,
        "currency": "EUR",
        "institution": "DKB",
    })
    savings = add_account({
        "id": DEMO_ACCOUNT_IDS[1],
        "name": "ING Savings Demo",
        "type": "savings",
        "current_balance": 12800.0,
        "currency": "EUR",
        "institution": "ING",
    })
    depot = add_account({
        "id": DEMO_ACCOUNT_IDS[2],
        "name": "Scalable Depot Demo",
        "type": "investment",
        "current_balance": 24500.0,
        "currency": "EUR",
        "institution": "Scalable Capital",
    })
    return {
        "checking": checking["id"],
        "savings": savings["id"],
        "depot": depot["id"],
    }


def _seed_transactions(account_id: str) -> None:
    from datetime import date, timedelta

    today = date.today()
    # Generate 6 months of transactions
    monthly_data = [
        # (income, housing, groceries, transport, restaurants, subscriptions)
        (3100, 1100, 295, 89, 185, 45),
        (3100, 1100, 310, 89, 210, 45),
        (3100, 1100, 280, 89, 165, 45),
        (3100, 1100, 305, 89, 195, 45),
        (3100, 1100, 318, 89, 175, 45),
        (3100, 1100, 290, 89, 220, 45),
    ]

    for months_ago, (income, rent, groceries, transport, restaurants, subs) in enumerate(reversed(monthly_data)):
        # Approximate first of month
        month_offset = today.replace(day=15) - timedelta(days=months_ago * 30)
        ym = month_offset.strftime("%Y-%m")

        add_transaction(f"{ym}-01", "income", income, "salary", "Salary Alex", account_id, import_source="demo")
        add_transaction(f"{ym}-02", "expense", -rent, "housing", "Miete Berlin", account_id, import_source="demo")
        add_transaction(f"{ym}-05", "expense", -groceries, "groceries", "REWE Einkauf", account_id, import_source="demo")
        add_transaction(f"{ym}-10", "expense", -transport, "transport", "BVG Ticket", account_id, import_source="demo")
        add_transaction(f"{ym}-15", "expense", -restaurants, "restaurants", "Restaurant & Café", account_id, import_source="demo")
        add_transaction(f"{ym}-20", "expense", -subs, "subscriptions", "Streaming & Cloud Abo", account_id, import_source="demo")
        add_transaction(f"{ym}-25", "expense", -120, "miscellaneous", "Misc Ausgaben", account_id, import_source="demo")


def _seed_goals(savings_account_id: str) -> None:
    add_goal({
        "id": DEMO_GOAL_IDS[0],
        "name": "Emergency Fund",
        "type": "emergency_fund",
        "target_amount": 15000.0,
        "current_amount": 12800.0,
        "currency": "EUR",
        "monthly_contribution": 200.0,
        "linked_account_id": savings_account_id,
        "priority": "high",
    })
    add_goal({
        "id": DEMO_GOAL_IDS[1],
        "name": "Japan Trip",
        "type": "travel",
        "target_amount": 3000.0,
        "current_amount": 840.0,
        "currency": "EUR",
        "monthly_contribution": 140.0,
        "target_date": "2026-04-01",
        "priority": "medium",
    })


def _seed_debts() -> None:
    add_debt({
        "id": DEMO_DEBT_IDS[0],
        "name": "Credit Card Demo",
        "type": "credit_card",
        "balance": 2100.0,
        "interest_rate": 18.9,
        "minimum_payment": 63.0,
        "currency": "EUR",
    })


def _seed_investments(depot_account_id: str) -> None:
    add_holding({
        "id": DEMO_HOLDING_IDS[0],
        "name": "World ETF",
        "symbol": "WORLD",
        "type": "etf",
        "units": 120.0,
        "cost_basis": 120 * 190.0,   # average cost basis ~190
        "current_value": 120 * 204.0,
        "currency": "EUR",
        "account_id": depot_account_id,
    })


def wipe_demo_data() -> dict:
    """Remove every entity seed_demo_data() creates, and reset the profile
    so a fresh onboarding isn't short-circuited by meta.created=True from
    the demo seed.

    Regression fix: this used to only call delete_account() per demo
    account — a JSON-only no-op once SQLite was active (list_accounts()
    prefers SQLite), so demo accounts, their transactions, goals, debts,
    the holding, and the "Alex" demo profile all survived a --wipe-demo
    that printed success. delete_account() itself is now dual-store
    correct; this also clears the entities delete_account never touched
    (transactions, goals, debts, holdings, profile).
    """
    removed = {"accounts": 0, "transactions": 0, "goals": 0, "debts": 0, "holdings": 0, "profile_reset": False}

    for account_id in DEMO_ACCOUNT_IDS:
        removed["transactions"] += _delete_demo_transactions(account_id)
        # A user's real rows may live in a demo-named account (e.g. their first
        # import after --demo): keep the account and everything they added.
        if _real_transaction_count(account_id) == 0 and delete_account(account_id):
            removed["accounts"] += 1

    for goal_id in DEMO_GOAL_IDS:
        if delete_goal(goal_id):
            removed["goals"] += 1

    for debt_id in DEMO_DEBT_IDS:
        if delete_debt(debt_id):
            removed["debts"] += 1

    for holding_id in DEMO_HOLDING_IDS:
        if delete_holding(holding_id):
            removed["holdings"] += 1

    removed["profile_reset"] = _reset_demo_profile()

    return removed


def _reset_demo_profile() -> bool:
    """Reset the profile back to blank so real onboarding isn't
    short-circuited by the demo's meta.created=True. NOT profile_manager's
    delete_profile() — that calls data_safety.delete_all_data(), which
    rmtree()s the ENTIRE .finance/ directory (all accounts, transactions,
    everything), not just the profile. Only resets if the profile still
    looks like the untouched demo seed (name "Alex", meta.created True) —
    if the user has since edited it with real info, leave it alone rather
    than guess."""
    profile = get_profile() or {}
    if profile.get("personal", {}).get("name") != "Alex":
        return False
    if not profile.get("meta", {}).get("created"):
        return False

    from profile_manager import PROFILE_SCHEMA
    from finance_storage import get_profile_path, save_json
    import copy
    save_json(get_profile_path(), copy.deepcopy(PROFILE_SCHEMA))
    return True


def _is_demo_txn(t: dict) -> bool:
    return t.get("import_source") == "demo" or t.get("description") in DEMO_DESCRIPTIONS


def _real_transaction_count(account_id: str) -> int:
    from finance_storage import ensure_subdir
    try:
        from db import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT source, description FROM transactions WHERE account_id = ?", (account_id,)
            ).fetchall()
        return sum(1 for r in rows if not _is_demo_txn({"import_source": r[0], "description": r[1]}))
    except Exception:
        pass
    n = 0
    for f in ensure_subdir("accounts", "transactions").glob(f"{account_id}_*.json"):
        n += sum(1 for t in (_load_json_list(f)) if not _is_demo_txn(t))
    return n


def _load_json_list(path) -> list:
    from finance_storage import load_json
    data = load_json(path, default={})
    return data.get("transactions", []) if isinstance(data, dict) else []


def _delete_demo_transactions(account_id: str) -> int:
    """Delete only demo-seeded transaction rows for account_id, across both
    stores and every year — never rows the user added or imported."""
    from finance_storage import ensure_subdir, load_json, save_json

    count = 0
    try:
        from db import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, source, description FROM transactions WHERE account_id = ?", (account_id,)
            ).fetchall()
            ids = [r[0] for r in rows if _is_demo_txn({"import_source": r[1], "description": r[2]})]
            for tid in ids:
                conn.execute("DELETE FROM transactions WHERE id = ?", (tid,))
            count = len(ids)
    except Exception:
        pass

    json_removed = 0
    for f in ensure_subdir("accounts", "transactions").glob(f"{account_id}_*.json"):
        rows = _load_json_list(f)
        keep = [t for t in rows if not _is_demo_txn(t)]
        json_removed += len(rows) - len(keep)
        if not keep:
            try:
                f.unlink()
            except OSError:
                pass
        elif len(keep) != len(rows):
            data = load_json(f, default={})
            data["transactions"] = keep
            data["transaction_count"] = len(keep)
            save_json(f, data)

    return count or json_removed
