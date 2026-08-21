"""Tests for transaction_logger.py."""
from transaction_logger import (
    add_transaction, get_transactions, get_totals,
    get_summary_display, auto_categorize, deduplicate,
    is_income_flow, is_expense_flow, update_transaction_fields,
    delete_transaction, unlink_transfer_pair, delete_import,
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


def test_deduplicate_db_present_does_not_dedupe_across_accounts(isolated_finance_dir_db):
    """Regression: the SQLite dedup path's fallback-key query had no
    account_id clause — it deduped GLOBALLY across every account, so an
    identical rent split across two people's checking accounts (or two
    matching card charges in different accounts) was wrongly dropped."""
    add_transaction("2026-04-01", "expense", -1200.00, "housing", "Rent split", account_id="alice-chk")

    # Same date/amount/description, but a genuinely different account —
    # must NOT be treated as a duplicate.
    new = [{"date": "2026-04-01", "amount": -1200.00, "description": "Rent split", "account_id": "bob-chk"}]
    unique = deduplicate(new, existing_transactions=[], account_id="bob-chk")
    assert len(unique) == 1


def test_deduplicate_db_present_still_catches_same_account_duplicate(isolated_finance_dir_db):
    add_transaction("2026-04-01", "expense", -45.50, "food", "REWE", account_id="chk")
    new = [{"date": "2026-04-01", "amount": -45.50, "description": "REWE", "account_id": "chk"}]
    unique = deduplicate(new, existing_transactions=[], account_id="chk")
    assert len(unique) == 0


def test_summary_display(isolated_finance_dir):
    add_transaction("2026-04-01", "expense", -100, "food", "REWE")
    display = get_summary_display(year=2026, month=4)
    assert "food" in display.lower() or "Food" in display


def test_get_totals_converts_transaction_currency_to_account_currency(isolated_finance_dir):
    """Regression: get_totals() used to sum transaction amounts ignoring
    each row's currency field entirely — a USD statement imported into a
    EUR account had its dollar amounts counted as euros with no conversion."""
    from account_manager import add_account

    add_account({"id": "eur-account", "name": "EUR Checking", "type": "checking", "currency": "EUR"})
    add_transaction("2026-04-01", "expense", -100, "food", "USD purchase",
                     account_id="eur-account", currency="USD")

    totals = get_totals(account_id="eur-account", year=2026)
    # USD 100 -> EUR via the fallback rate table is NOT a flat 100
    assert totals["food"]["expense"] != 100.0
    assert totals["food"]["expense"] > 0


# ── DB-present: 6 TRANSACTION_SCHEMA fields used to be silently dropped ──

def test_db_present_round_trips_previously_dropped_fields(isolated_finance_dir_db):
    """Regression: the SQLite INSERT only listed 13 columns while
    TRANSACTION_SCHEMA has 18 — is_recurring, tags, tax_relevant,
    tax_category, business_use_pct, and import_ref were silently dropped on
    the SQLite side, even though transaction_normalizer/recurring_engine/
    receipt_scanner all populate them on write. Since get_transactions()
    prefers SQLite when available, these fields vanished from every read
    once the DB was active."""
    add_transaction(
        "2026-04-01", "expense", -45.50, "subscriptions", "Netflix",
        is_recurring=True, tags=["streaming", "monthly"],
        tax_relevant=True, tax_category="home_office",
        business_use_pct=30.0, import_ref="import-abc123",
    )

    txns = get_transactions(year=2026)
    assert len(txns) == 1
    t = txns[0]
    assert t["is_recurring"] is True
    assert t["tags"] == ["streaming", "monthly"]
    assert t["tax_relevant"] is True
    assert t["tax_category"] == "home_office"
    assert t["business_use_pct"] == 30.0
    assert t["import_ref"] == "import-abc123"


# ── Transaction correction tools (Phase 5) ──────────────────────────────────

def test_delete_transaction_json(isolated_finance_dir):
    """Regression: delete_transaction() didn't exist anywhere — the only
    documented workaround for a bad import was deleting the whole account."""
    add_transaction("2026-04-01", "expense", -20.0, "food", "Wrong entry", account_id="chk")
    txn_id = get_transactions(account_id="chk", year=2026)[0]["id"]

    assert delete_transaction("chk", txn_id) is True
    assert get_transactions(account_id="chk", year=2026) == []
    assert delete_transaction("chk", txn_id) is False  # already gone


def test_delete_transaction_db_present(isolated_finance_dir_db):
    add_transaction("2026-04-01", "expense", -20.0, "food", "Wrong entry", account_id="chk")
    txn_id = get_transactions(account_id="chk", year=2026)[0]["id"]

    from db import get_conn
    assert delete_transaction("chk", txn_id) is True
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    assert row is None
    assert get_transactions(account_id="chk", year=2026) == []


def test_unlink_transfer_pair_clears_both_legs(isolated_finance_dir):
    from account_manager import add_account
    add_account({"id": "chk", "name": "Checking", "type": "checking"})
    add_account({"id": "sav", "name": "Savings", "type": "savings"})
    a = add_transaction("2026-04-01", "transfer", -500.0, "savings", "To savings", account_id="chk")["transaction_added"]
    b = add_transaction("2026-04-02", "transfer", 500.0, "savings", "From checking", account_id="sav")["transaction_added"]
    update_transaction_fields("chk", 2026, a["id"], {"transfer_peer_id": b["id"]})
    update_transaction_fields("sav", 2026, b["id"], {"transfer_peer_id": a["id"]})

    assert unlink_transfer_pair("chk", a["id"], 2026) is True

    chk_txn = get_transactions(account_id="chk", year=2026)[0]
    sav_txn = get_transactions(account_id="sav", year=2026)[0]
    assert chk_txn["transfer_peer_id"] is None
    assert sav_txn["transfer_peer_id"] is None  # peer also cleared, not just the one asked for


def test_delete_import_removes_only_that_imports_rows(isolated_finance_dir):
    """Regression: import_ref was never actually generated by any parser —
    it was always None, so there was no way to target 'everything from
    this import' for deletion even after delete_import() existed."""
    from account_manager import add_account
    add_account({"id": "chk", "name": "Checking", "type": "checking"})

    add_transaction("2026-04-01", "expense", -10.0, "food", "From import A", account_id="chk", import_ref="import-A")
    add_transaction("2026-04-02", "expense", -20.0, "food", "From import B", account_id="chk", import_ref="import-B")
    add_transaction("2026-04-03", "expense", -30.0, "food", "Manual entry", account_id="chk")

    result = delete_import("import-A")
    assert result["deleted_count"] == 1

    remaining = {t["description"] for t in get_transactions(account_id="chk", year=2026)}
    assert remaining == {"From import B", "Manual entry"}
