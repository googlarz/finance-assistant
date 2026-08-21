"""Tests for net_worth_engine.py."""
from account_manager import add_account
from investment_tracker import add_holding
from debt_optimizer import add_debt
from profile_manager import update_profile
from net_worth_engine import (
    calculate_net_worth, take_snapshot, get_snapshots,
    calculate_net_worth_trend, format_net_worth_display,
)


def test_empty_net_worth(isolated_finance_dir):
    nw = calculate_net_worth()
    assert nw["net_worth"] == 0
    assert nw["total_assets"] == 0


def test_net_worth_with_accounts(isolated_finance_dir):
    add_account({"name": "Checking", "type": "checking", "current_balance": 5000})
    add_account({"name": "Savings", "type": "savings", "current_balance": 10000})
    add_account({"name": "CC", "type": "credit_card", "current_balance": -500})
    nw = calculate_net_worth()
    assert nw["breakdown"]["cash_and_savings"] == 15000.0
    assert nw["breakdown"]["credit_card_balance"] == 500.0


def test_net_worth_with_investments(isolated_finance_dir):
    add_account({"name": "Checking", "type": "checking", "current_balance": 5000})
    add_holding({"symbol": "VWCE", "type": "etf", "current_value": 20000})
    nw = calculate_net_worth()
    assert nw["total_assets"] == 25000.0
    assert nw["breakdown"]["investments"] == 20000.0


def test_net_worth_with_debt(isolated_finance_dir):
    add_account({"name": "Checking", "type": "checking", "current_balance": 10000})
    add_debt({"name": "Loan", "balance": 15000, "interest_rate": 5, "minimum_payment": 200})
    nw = calculate_net_worth()
    assert nw["net_worth"] == -5000.0


def test_take_snapshot(isolated_finance_dir):
    add_account({"name": "Checking", "type": "checking", "current_balance": 5000})
    snap = take_snapshot()
    assert snap["net_worth"] == 5000.0
    assert snap["date"] is not None


def test_get_snapshots(isolated_finance_dir):
    add_account({"name": "Checking", "type": "checking", "current_balance": 5000})
    take_snapshot()
    snaps = get_snapshots()
    assert len(snaps) == 1


def test_trend_no_history(isolated_finance_dir):
    trend = calculate_net_worth_trend()
    assert trend["trend"] == "no_history"


def test_format_display(isolated_finance_dir):
    add_account({"name": "Checking", "type": "checking", "current_balance": 8000})
    add_holding({"symbol": "VWCE", "type": "etf", "current_value": 12000})
    display = format_net_worth_display()
    assert "Net Worth" in display
    assert "20,000" in display


# ── Multi-currency: convert() returns (amount, confidence), not a bare float ──

def test_net_worth_with_second_currency_does_not_crash(isolated_finance_dir):
    """Regression: _to_primary() used to do `cash_assets += convert(...)`
    directly — convert() returns an (amount, confidence) tuple, so adding a
    non-primary-currency account raised TypeError. Reproduced pre-fix."""
    update_profile({"meta": {"primary_currency": "EUR"}})
    add_account({"name": "EUR Checking", "type": "checking", "current_balance": 1000, "currency": "EUR"})
    add_account({"name": "USD Savings", "type": "savings", "current_balance": 1000, "currency": "USD"})

    nw = calculate_net_worth()  # must not raise
    assert nw["currency"] == "EUR"
    # USD 1000 converts to something other than a raw 1000 EUR (fallback rate applied)
    assert nw["total_assets"] != 2000.0
    assert nw["total_assets"] > 1000.0  # both accounts contributed, not just the EUR one


def test_debts_in_non_primary_currency_are_converted(isolated_finance_dir):
    """Regression: debt_total was summed raw with no currency conversion
    despite debts carrying a currency field — a USD debt was silently
    counted as if it were EUR."""
    update_profile({"meta": {"primary_currency": "EUR"}})
    add_debt({"name": "US Loan", "balance": 1000, "interest_rate": 5, "minimum_payment": 50, "currency": "USD"})

    nw = calculate_net_worth()
    # USD 1.08 -> EUR fallback rate means 1000 USD != 1000 EUR liability
    assert nw["total_liabilities"] != 1000.0
    assert nw["total_liabilities"] > 0


def test_take_snapshot_db_present_reaches_timeline_engine(isolated_finance_dir_db):
    """Regression: net worth snapshots were written to SQLite only once, by
    the first-boot migration — a snapshot taken after that point was
    invisible to timeline_engine, which reads the "net_worth" snapshot type
    SQLite-only."""
    from db import get_conn

    add_account({"name": "Checking", "type": "checking", "current_balance": 5000})
    take_snapshot()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT type, date, data FROM snapshots WHERE type = 'net_worth'"
        ).fetchone()
    assert row is not None
    import json
    assert json.loads(row["data"])["net_worth"] == 5000.0


def test_format_display_uses_actual_primary_currency_not_hardcoded_eur(isolated_finance_dir):
    """Regression: format_net_worth_display() hardcoded 'EUR' in every
    format_money() call regardless of the profile's actual primary_currency."""
    update_profile({"meta": {"primary_currency": "USD"}})
    add_account({"name": "Checking", "type": "checking", "current_balance": 1000, "currency": "USD"})

    display = format_net_worth_display()
    assert "$" in display
    assert "€" not in display
