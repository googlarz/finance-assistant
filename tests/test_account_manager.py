"""Tests for account_manager.py."""
from account_manager import (
    get_accounts, add_account, update_account, delete_account,
    get_account, get_total_balance, display_accounts,
)


def test_empty_accounts(isolated_finance_dir):
    assert get_accounts() == []


def test_add_account(isolated_finance_dir):
    acc = add_account({"name": "DKB Checking", "type": "checking", "institution": "DKB", "current_balance": 5000})
    assert acc["id"] == "dkb-checking"
    assert acc["is_asset"] is True
    assert acc["current_balance"] == 5000


def test_credit_card_is_liability(isolated_finance_dir):
    acc = add_account({"name": "VISA", "type": "credit_card", "current_balance": -450})
    assert acc["is_asset"] is False


def test_get_account(isolated_finance_dir):
    add_account({"name": "Test", "type": "savings", "current_balance": 1000})
    assert get_account("test") is not None
    assert get_account("nonexistent") is None


def test_update_account(isolated_finance_dir):
    add_account({"name": "Test", "type": "savings", "current_balance": 1000})
    updated = update_account("test", {"current_balance": 2000})
    assert updated["current_balance"] == 2000


def test_delete_account(isolated_finance_dir):
    add_account({"name": "Test", "type": "savings"})
    assert delete_account("test") is True
    assert delete_account("test") is False
    assert len(get_accounts()) == 0


def test_total_balance(isolated_finance_dir):
    add_account({"name": "Checking", "type": "checking", "current_balance": 5000})
    add_account({"name": "Savings", "type": "savings", "current_balance": 10000})
    add_account({"name": "Card", "type": "credit_card", "current_balance": -500})
    totals = get_total_balance()
    assert totals["assets"] == 15000.0
    assert totals["liabilities"] == 500.0
    assert totals["net"] == 14500.0


def test_display_accounts(isolated_finance_dir):
    add_account({"name": "DKB", "type": "checking", "institution": "DKB", "current_balance": 3000})
    display = display_accounts()
    assert "DKB" in display
    assert "3,000" in display


def test_unique_ids(isolated_finance_dir):
    add_account({"name": "Test", "type": "checking"})
    add_account({"name": "Test", "type": "checking"})
    accounts = get_accounts()
    ids = [a["id"] for a in accounts]
    assert len(set(ids)) == 2  # IDs are unique


# ── DB-present: SQLite is the read path for list_accounts()/get_account() ──

def test_get_account_db_present_has_current_balance_and_is_asset(isolated_finance_dir_db):
    """Regression: SQLite accounts rows used to have no current_balance/
    is_asset columns at all — list_accounts()/get_account() silently
    returned accounts with current_balance defaulting to 0 and is_asset
    defaulting to True (misclassifying every liability as an asset) the
    moment the DB was active."""
    add_account({"name": "Checking", "type": "checking", "current_balance": 5000})
    add_account({"name": "Visa", "type": "credit_card", "current_balance": -450})

    chk = get_account("checking")
    visa = get_account("visa")
    assert chk["current_balance"] == 5000.0
    assert chk["is_asset"] is True
    assert visa["current_balance"] == -450.0
    assert visa["is_asset"] is False  # not the pre-fix default of True

    accounts = get_accounts()
    assert {a["current_balance"] for a in accounts} == {5000.0, -450.0}


def test_delete_account_db_present_actually_deletes(isolated_finance_dir_db):
    """Regression: delete_account() used to only rewrite the JSON mirror —
    list_accounts() prefers SQLite, so a deleted account kept appearing
    (and its balance kept counting toward net worth) whenever the DB was
    active. Verified as a reproducible no-op before this fix."""
    add_account({"name": "Test", "type": "savings"})
    assert any(a["id"] == "test" for a in get_accounts())

    assert delete_account("test") is True
    assert get_account("test") is None
    assert all(a["id"] != "test" for a in get_accounts())


def test_total_balance_converts_mixed_currencies(isolated_finance_dir):
    """Regression: get_total_balance() used to sum raw balances across
    currencies and stamp the result 'EUR' regardless of composition — a
    USD account's 500 was silently counted as 500 EUR."""
    add_account({"name": "EUR Checking", "type": "checking", "current_balance": 1000, "currency": "EUR"})
    add_account({"name": "USD Savings", "type": "savings", "current_balance": 1000, "currency": "USD"})

    totals = get_total_balance(currency="EUR")
    # USD 1000 -> EUR via the fallback rate table is NOT 1000 flat
    assert totals["assets"] != 2000.0
    assert totals["assets"] > 1000.0
    assert totals["currency"] == "EUR"


def test_update_account_db_present_dual_writes_rename_and_is_asset(isolated_finance_dir_db):
    """Regression: update_account() only mirrored current_balance to SQLite
    — a renamed account or a type change (checking -> loan) never reached
    SQLite, leaving it permanently stale while reads prefer SQLite."""
    add_account({"name": "Old Name", "type": "checking", "current_balance": 100})
    update_account("old-name", {"name": "New Name", "type": "loan", "is_asset": False})

    acc = get_account("old-name")
    assert acc["name"] == "New Name"
    assert acc["type"] == "loan"
    assert acc["is_asset"] is False


# ── Audit logging on account mutations ──────────────────────────────────────

def test_account_mutations_are_audit_logged(isolated_finance_dir):
    """Regression: account_manager had zero log_mutation calls despite
    audit_log.py's own docstring claiming account changes are logged —
    balances and renames could change silently with no trail."""
    from audit_log import read_recent

    add_account({"id": "chk", "name": "Checking", "type": "checking", "current_balance": 100})
    update_account("chk", {"current_balance": 200})
    delete_account("chk")

    entries = read_recent(limit=10)
    actions = {(e["action"], e["target"]) for e in entries}
    assert ("create", "account") in actions
    assert ("update", "account") in actions
    assert ("delete", "account") in actions
