"""Tests for net_worth_engine.py."""
from account_manager import add_account
from investment_tracker import add_holding
from debt_optimizer import add_debt
from profile_manager import update_profile
from net_worth_engine import (
    calculate_net_worth, take_snapshot, get_snapshots,
    calculate_net_worth_trend, format_net_worth_display,
    backfill_net_worth_history,
)
from transaction_logger import add_transaction


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


def test_backfill_net_worth_history_derives_past_snapshot(isolated_finance_dir):
    """Regression: calculate_net_worth_trend() returned trend='no_history'
    until months of FORWARD snapshots accumulated — a user importing 2
    years of transaction history got a blank net-worth chart even though
    the data to reconstruct it already existed."""
    from datetime import date, timedelta

    add_account({"name": "Checking", "type": "checking", "current_balance": 1000})
    # Dated today — happened AFTER last month's checkpoint, so it must be
    # subtracted back out to reconstruct last month's balance.
    add_transaction(date.today().isoformat(), "expense", -100, "food", "Groceries", account_id="checking")

    result = backfill_net_worth_history(months=1)
    assert result["created"] == 1

    snaps = get_snapshots()
    assert len(snaps) == 1
    assert snaps[0]["source"] == "derived"
    assert snaps[0]["net_worth"] == 1100.0  # 1000 - (-100) undone


def test_backfill_net_worth_history_never_overwrites_existing_snapshot(isolated_finance_dir):
    from datetime import date
    import calendar
    from net_worth_engine import get_net_worth_snapshot_path
    from finance_storage import save_json

    add_account({"name": "Checking", "type": "checking", "current_balance": 1000})

    today = date.today()
    y, m = today.year, today.month - 1 or 12
    if today.month == 1:
        y -= 1
    last_day = calendar.monthrange(y, m)[1]
    existing_date = date(y, m, last_day).isoformat()
    save_json(get_net_worth_snapshot_path(existing_date), {"date": existing_date, "net_worth": 99999.0})

    result = backfill_net_worth_history(months=1)
    assert result["created"] == 0
    assert result["skipped"] == 1

    snaps = get_snapshots()
    assert snaps[0]["net_worth"] == 99999.0  # untouched


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
