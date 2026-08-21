"""Tests for recurring_engine.py — focusing on calendar-aware day clamping."""
from datetime import date
from recurring_engine import _calculate_due_dates, add_recurring, delete_recurring


def _make_item(day_of_month: int, freq: str = "monthly", start: str = "2024-01-01") -> dict:
    return {
        "id": "test",
        "frequency": freq,
        "day_of_month": day_of_month,
        "start_date": start,
    }


def test_day31_in_february_clamps_to_28():
    """day_of_month=31 in February must fire on the 28th (non-leap)."""
    item = _make_item(day_of_month=31, freq="monthly", start="2025-01-01")
    after = date(2025, 1, 31)
    up_to = date(2025, 2, 28)
    dates = _calculate_due_dates(item, after, up_to)
    assert date(2025, 2, 28) in dates, f"Expected Feb 28, got {dates}"


def test_day31_in_march_fires_on_31():
    """day_of_month=31 in March must fire on the 31st (March has 31 days)."""
    item = _make_item(day_of_month=31, freq="monthly", start="2025-01-01")
    after = date(2025, 2, 28)
    up_to = date(2025, 3, 31)
    dates = _calculate_due_dates(item, after, up_to)
    assert date(2025, 3, 31) in dates, f"Expected Mar 31, got {dates}"


def test_day30_in_april_clamps_to_30():
    """day_of_month=31 in April (30-day month) must clamp to the 30th."""
    item = _make_item(day_of_month=31, freq="monthly", start="2025-01-01")
    after = date(2025, 3, 31)
    up_to = date(2025, 4, 30)
    dates = _calculate_due_dates(item, after, up_to)
    assert date(2025, 4, 30) in dates, f"Expected Apr 30, got {dates}"


def test_day29_in_february_leap_year():
    """day_of_month=29 must fire on Feb 29 in a leap year."""
    item = _make_item(day_of_month=29, freq="monthly", start="2024-01-01")
    after = date(2024, 1, 31)
    up_to = date(2024, 2, 29)
    dates = _calculate_due_dates(item, after, up_to)
    assert date(2024, 2, 29) in dates, f"Expected Feb 29 (leap year), got {dates}"


def test_quarterly_day31_clamps_correctly():
    """Quarterly recurrings must also clamp day_of_month to the actual month length."""
    item = _make_item(day_of_month=31, freq="quarterly", start="2025-01-01")
    after = date(2025, 3, 31)
    up_to = date(2025, 9, 30)
    dates = _calculate_due_dates(item, after, up_to)
    # Quarterly from Jan 1: Apr 30 (April has 30 days), Jul 31
    assert date(2025, 4, 30) in dates, f"Expected Apr 30, got {dates}"
    assert date(2025, 7, 31) in dates, f"Expected Jul 31, got {dates}"


# ── DB-present: recurring_items used to be SQLite-frozen after migration ──

def test_add_recurring_db_present_reaches_overdraft_projection(isolated_finance_dir_db):
    """Regression: recurring_items were written to SQLite only once, by the
    first-boot migration — an item added after that point was invisible to
    overdraft_detector.project_inflows/project_outflows, which read
    recurring_items SQLite-only."""
    from db import get_conn
    from overdraft_detector import project_outflows

    add_recurring("Netflix", -15.0, "subscriptions", frequency="monthly",
                   account_id="chk", day_of_month=5)

    with get_conn() as conn:
        outflows = project_outflows(conn, days=60)
    assert any("Netflix" in o["description"] for o in outflows)


def test_delete_recurring_db_present_actually_deletes(isolated_finance_dir_db):
    from db import get_conn
    item = add_recurring("Gym", -30.0, "subscriptions")
    assert delete_recurring(item["id"]) is True
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM recurring_items WHERE id = ?", (item["id"],)).fetchone()
    assert row is None
