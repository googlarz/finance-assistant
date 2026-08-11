"""Tests for transaction_logger.py."""
from transaction_logger import (
    add_transaction, get_transactions, get_totals,
    get_summary_display, auto_categorize, deduplicate,
    is_income_flow, is_expense_flow, update_transaction_fields,
)


def test_add_transaction(isolated_finance_dir):
    result = add_transaction("2026-04-01", "expense", -45.50, "food", "REWE Supermarket")
    txn = result["transaction_added"]
    assert txn["amount"] == -45.50
    assert txn["category"] == "food"


def test_get_transactions(isolated_finance_dir):
    add_transaction("2026-04-01", "expense", -50, "food", "REWE")
    add_transaction("2026-04-02", "expense", -30, "dining", "Restaurant")
    txns = get_transactions(year=2026)
    assert len(txns) == 2


def test_get_transactions_filtered(isolated_finance_dir):
    add_transaction("2026-04-01", "expense", -50, "food", "REWE")
    add_transaction("2026-04-01", "income", 3000, "salary", "Gehalt")
    txns = get_transactions(year=2026, type="income")
    assert len(txns) == 1
    assert txns[0]["category"] == "salary"


def test_get_totals(isolated_finance_dir):
    add_transaction("2026-04-01", "expense", -100, "food", "REWE")
    add_transaction("2026-04-02", "expense", -50, "food", "ALDI")
    add_transaction("2026-04-01", "income", 3000, "salary", "Gehalt")
    totals = get_totals(year=2026)
    assert totals["food"]["expense"] == 150.0
    assert totals["salary"]["income"] == 3000.0


def test_get_totals_excludes_transfers_and_investments(isolated_finance_dir):
    """Issue #7: transfer/investment/debt_payment rows must not be counted
    as income or expense by get_totals(), even though their sign matches."""
    add_transaction("2026-04-01", "expense", -100, "food", "REWE")
    add_transaction("2026-04-02", "transfer", -5000, "savings", "Move to savings")
    add_transaction("2026-04-03", "transfer", 5000, "savings", "Move to savings (other leg)")
    add_transaction("2026-04-04", "investment", -1000, "investment", "Buy ETF")
    add_transaction("2026-04-05", "debt_payment", -300, "debt_payment", "Mortgage principal")
    totals = get_totals(year=2026)

    assert totals["food"]["expense"] == 100.0
    assert totals["savings"]["income"] == 0.0
    assert totals["savings"]["expense"] == 0.0
    assert totals["investment"]["income"] == 0.0
    assert totals["investment"]["expense"] == 0.0
    assert totals["debt_payment"]["income"] == 0.0
    assert totals["debt_payment"]["expense"] == 0.0


def test_is_income_flow():
    assert is_income_flow({"type": "income", "amount": 100}) is True
    assert is_income_flow({"type": "expense", "amount": 100}) is False
    assert is_income_flow({"type": "transfer", "amount": 100}) is False
    assert is_income_flow({"type": "investment", "amount": 100}) is False
    assert is_income_flow({"type": "debt_payment", "amount": 100}) is False
    # No type set: falls back to sign
    assert is_income_flow({"amount": 100}) is True
    assert is_income_flow({"amount": -100}) is False


def test_is_expense_flow():
    assert is_expense_flow({"type": "expense", "amount": -100}) is True
    assert is_expense_flow({"type": "income", "amount": -100}) is False
    assert is_expense_flow({"type": "transfer", "amount": -100}) is False
    assert is_expense_flow({"type": "investment", "amount": -100}) is False
    assert is_expense_flow({"type": "debt_payment", "amount": -100}) is False
    # No type set: falls back to sign
    assert is_expense_flow({"amount": -100}) is True
    assert is_expense_flow({"amount": 100}) is False


# ── update_transaction_fields (#8) ───────────────────────────────────────────

def test_update_transaction_fields_updates_type_and_peer(isolated_finance_dir):
    r = add_transaction("2026-04-01", "expense", -100, "food", "Groceries")
    txn_id = r["transaction_added"]["id"]

    ok = update_transaction_fields("default", 2026, txn_id, {
        "type": "transfer", "transfer_peer_id": "other-txn-id",
    })
    assert ok is True

    txns = get_transactions(account_id="default", year=2026)
    t = next(t for t in txns if t["id"] == txn_id)
    assert t["type"] == "transfer"
    assert t["transfer_peer_id"] == "other-txn-id"


def test_update_transaction_fields_ignores_unknown_id(isolated_finance_dir):
    assert update_transaction_fields("default", 2026, "does-not-exist", {"type": "transfer"}) is False


def test_update_transaction_fields_rejects_non_updatable_fields(isolated_finance_dir):
    """Amount/date/account_id must not be rewritable through this path."""
    r = add_transaction("2026-04-01", "expense", -100, "food", "Groceries")
    txn_id = r["transaction_added"]["id"]

    ok = update_transaction_fields("default", 2026, txn_id, {"amount": -9999})
    assert ok is False  # no updatable fields survive filtering

    txns = get_transactions(account_id="default", year=2026)
    t = next(t for t in txns if t["id"] == txn_id)
    assert t["amount"] == -100


def test_auto_categorize():
    cat, _ = auto_categorize("REWE Berlin Supermarkt", -45)
    assert cat == "food"
    cat, _ = auto_categorize("Netflix Subscription", -12.99)
    assert cat == "subscriptions"
    cat, _ = auto_categorize("Gehalt April", 3500)
    assert cat == "salary"


def test_deduplicate():
    existing = [{"date": "2026-04-01", "amount": -45.50, "description": "REWE"}]
    new = [
        {"date": "2026-04-01", "amount": -45.50, "description": "REWE"},  # duplicate
        {"date": "2026-04-02", "amount": -30.00, "description": "ALDI"},  # unique
    ]
    unique = deduplicate(new, existing)
    assert len(unique) == 1
    assert unique[0]["description"] == "ALDI"


def test_summary_display(isolated_finance_dir):
    add_transaction("2026-04-01", "expense", -100, "food", "REWE")
    display = get_summary_display(year=2026, month=4)
    assert "food" in display.lower() or "Food" in display
