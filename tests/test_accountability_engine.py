# tests/test_accountability_engine.py

"""Tests for accountability_engine.py — ≥15 test cases."""

import sqlite3
from datetime import date, timedelta

import pytest

# The isolated_finance_dir fixture (autouse) from conftest.py sets FINANCE_PROJECT_DIR
# so get_db_path() resolves to a temp file automatically.

from accountability_engine import (
    check_budget_patterns,
    check_overdue_commitments,
    check_goal_drift,
    check_savings_rate_trend,
    check_category_creep,
    get_accountability_alerts,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def conn(isolated_finance_dir):
    """In-memory SQLite connection with required schema."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE budget_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,
            category TEXT NOT NULL,
            limit_amount REAL NOT NULL,
            actual_amount REAL DEFAULT 0,
            currency TEXT DEFAULT 'EUR',
            UNIQUE(month, category)
        );
        CREATE TABLE journal_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_type TEXT NOT NULL,
            date TEXT,
            title TEXT,
            description TEXT,
            status TEXT DEFAULT 'open',
            outcome TEXT,
            linked_metrics TEXT,
            due_date TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE goals (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            target_amount REAL NOT NULL,
            current_amount REAL DEFAULT 0,
            target_date TEXT,
            currency TEXT DEFAULT 'EUR',
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE transactions (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL,
            category TEXT,
            description TEXT,
            source TEXT DEFAULT 'manual',
            payee TEXT,
            type TEXT DEFAULT 'expense',
            created_at TEXT NOT NULL
        );
    """)
    c.commit()
    yield c
    c.close()


def _months_back(n, ref=None):
    """Helper: list of YYYY-MM strings, most recent first."""
    today = ref or date.today()
    result = []
    year, month = today.year, today.month
    for _ in range(n):
        result.append(f"{year}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return result


# ── check_budget_patterns ─────────────────────────────────────────────────────

class TestBudgetPatterns:
    def test_three_months_over_detected(self, conn):
        months = _months_back(3)
        for m in months:
            conn.execute(
                "INSERT INTO budget_categories (month, category, limit_amount, actual_amount) VALUES (?, 'Food', 200, 280)",
                (m,),
            )
        conn.commit()
        alerts = check_budget_patterns(conn)
        assert len(alerts) == 1
        a = alerts[0]
        assert a["type"] == "budget_pattern"
        assert a["category"] == "Food"
        assert a["months_over"] == 3
        assert a["avg_overspend_pct"] == pytest.approx(40.0, abs=0.5)

    def test_two_months_over_not_detected(self, conn):
        months = _months_back(3)
        # First month (oldest) under budget
        conn.execute(
            "INSERT INTO budget_categories (month, category, limit_amount, actual_amount) VALUES (?, 'Food', 200, 180)",
            (months[2],),
        )
        for m in months[:2]:
            conn.execute(
                "INSERT INTO budget_categories (month, category, limit_amount, actual_amount) VALUES (?, 'Food', 200, 260)",
                (m,),
            )
        conn.commit()
        alerts = check_budget_patterns(conn)
        assert alerts == []

    def test_four_months_over_returns_correct_count(self, conn):
        months = _months_back(5)
        # 4 most recent over, 1 oldest under
        conn.execute(
            "INSERT INTO budget_categories (month, category, limit_amount, actual_amount) VALUES (?, 'Dining', 100, 80)",
            (months[4],),
        )
        for m in months[:4]:
            conn.execute(
                "INSERT INTO budget_categories (month, category, limit_amount, actual_amount) VALUES (?, 'Dining', 100, 150)",
                (m,),
            )
        conn.commit()
        alerts = check_budget_patterns(conn)
        assert len(alerts) == 1
        assert alerts[0]["months_over"] == 4

    def test_no_rows_returns_empty(self, conn):
        assert check_budget_patterns(conn) == []


# ── check_overdue_commitments ─────────────────────────────────────────────────

class TestOverdueCommitments:
    def test_past_due_detected(self, conn):
        past = (date.today() - timedelta(days=5)).isoformat()
        conn.execute(
            "INSERT INTO journal_entries (entry_type, title, status, due_date) VALUES ('commitment', 'Save €500', 'open', ?)",
            (past,),
        )
        conn.commit()
        alerts = check_overdue_commitments(conn)
        assert len(alerts) == 1
        a = alerts[0]
        assert a["type"] == "overdue_commitment"
        assert a["title"] == "Save €500"
        assert a["days_overdue"] == 5

    def test_future_due_not_detected(self, conn):
        future = (date.today() + timedelta(days=10)).isoformat()
        conn.execute(
            "INSERT INTO journal_entries (entry_type, title, status, due_date) VALUES ('commitment', 'Save €500', 'open', ?)",
            (future,),
        )
        conn.commit()
        assert check_overdue_commitments(conn) == []

    def test_kept_commitment_not_detected(self, conn):
        past = (date.today() - timedelta(days=3)).isoformat()
        conn.execute(
            "INSERT INTO journal_entries (entry_type, title, status, due_date) VALUES ('commitment', 'Old goal', 'kept', ?)",
            (past,),
        )
        conn.commit()
        assert check_overdue_commitments(conn) == []

    def test_missing_table_returns_empty(self, isolated_finance_dir):
        """journal_entries table absent — must not crash."""
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        result = check_overdue_commitments(c)
        assert result == []
        c.close()


# ── check_goal_drift ──────────────────────────────────────────────────────────

class TestGoalDrift:
    def _insert_goal(self, conn, *, current, target, months_to_deadline, months_old):
        today = date.today()
        # created N months ago
        cy, cm = today.year, today.month
        for _ in range(months_old):
            cm -= 1
            if cm == 0:
                cm = 12
                cy -= 1
        created = f"{cy}-{cm:02d}-01"
        # target N months in future
        ty, tm = today.year, today.month
        tm += months_to_deadline
        while tm > 12:
            tm -= 12
            ty += 1
        target_date = f"{ty}-{tm:02d}-01"
        conn.execute(
            """INSERT INTO goals (id, name, target_amount, current_amount, target_date, status, created_at, updated_at)
               VALUES ('g1', 'Emergency Fund', ?, ?, ?, 'active', ?, ?)""",
            (target, current, target_date, created, created),
        )
        conn.commit()

    def test_behind_pace_detected(self, conn):
        # Saved 100 of 2400 after 1 month; needs 200/mo for 12 months remaining
        self._insert_goal(conn, current=100, target=2400, months_to_deadline=12, months_old=1)
        alerts = check_goal_drift(conn)
        assert len(alerts) == 1
        a = alerts[0]
        assert a["type"] == "goal_drift"
        assert a["goal_name"] == "Emergency Fund"
        assert a["shortfall_per_month"] > 0

    def test_on_pace_not_detected(self, conn):
        # Saved 600 of 1200 after 6 months; needs 100/mo and saving 100/mo
        self._insert_goal(conn, current=600, target=1200, months_to_deadline=6, months_old=6)
        alerts = check_goal_drift(conn)
        assert alerts == []

    def test_no_goals_returns_empty(self, conn):
        assert check_goal_drift(conn) == []


# ── check_savings_rate_trend ──────────────────────────────────────────────────

class TestSavingsRateTrend:
    def _insert_month(self, conn, ym, income, expense):
        conn.execute(
            "INSERT INTO transactions (id, account_id, date, amount, currency, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (f"{ym}-inc", "acc", f"{ym}-01", income, "EUR", f"{ym}-01"),
        )
        conn.execute(
            "INSERT INTO transactions (id, account_id, date, amount, currency, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (f"{ym}-exp", "acc", f"{ym}-01", -expense, "EUR", f"{ym}-01"),
        )
        conn.commit()

    def test_three_months_declining_detected(self, conn):
        months = _months_back(6)
        # oldest 3 months: high savings; newest 3 months: declining
        savings_rates = [0.30, 0.28, 0.25, 0.22, 0.18, 0.12]  # oldest→newest
        ordered = list(reversed(months))  # oldest first
        income = 3000
        for i, ym in enumerate(ordered):
            rate = savings_rates[i]
            expense = income * (1 - rate)
            self._insert_month(conn, ym, income, expense)
        alerts = check_savings_rate_trend(conn)
        assert len(alerts) == 1
        a = alerts[0]
        assert a["type"] == "savings_rate_decline"
        assert a["months_declining"] >= 3

    def test_two_months_declining_not_detected(self, conn):
        months = _months_back(6)
        ordered = list(reversed(months))
        # only last 2 months declining
        rates = [0.30, 0.30, 0.30, 0.30, 0.25, 0.20]
        income = 3000
        for i, ym in enumerate(ordered):
            expense = income * (1 - rates[i])
            self._insert_month(conn, ym, income, expense)
        alerts = check_savings_rate_trend(conn)
        assert alerts == []

    def test_no_transactions_returns_empty(self, conn):
        assert check_savings_rate_trend(conn) == []

    def test_transfers_excluded_from_income_and_expenses(self, conn):
        """Issue #7: leaking a transfer into a month's expense total corrupts
        that month's computed savings rate enough to break a genuine 3-month
        declining streak, suppressing an alert the user should get."""
        months = _months_back(6)
        ordered = list(reversed(months))  # oldest -> newest
        income = 3000
        # oldest -> newest rates: 4 months of a clean decline (0.25, 0.20, 0.15, 0.10),
        # then the 2 oldest months break the streak so months_declining == 3 exactly.
        rates = [0.20, 0.20, 0.25, 0.20, 0.15, 0.10]
        for ym, rate in zip(ordered, rates):
            self._insert_month(conn, ym, income, income * (1 - rate))
        conn.commit()

        # Sanity: with clean data alone, the decline is real and should alert.
        baseline_alerts = check_savings_rate_trend(conn)
        assert len(baseline_alerts) == 1
        assert baseline_alerts[0]["months_declining"] == 3

        # Inject a large transfer into one of the declining months (index 3,
        # rate 0.20 → "2026-05"-equivalent). If it leaks into expenses, that
        # month's apparent rate craters below its neighbor's, breaking the
        # streak the moment the loop reaches it.
        xfer_month = ordered[3]
        conn.execute(
            "INSERT INTO transactions (id, account_id, date, amount, currency, type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"{xfer_month}-xfer", "acc", f"{xfer_month}-20", -3000, "EUR", "transfer", f"{xfer_month}-20"),
        )
        conn.commit()

        alerts = check_savings_rate_trend(conn)
        assert len(alerts) == 1
        assert alerts[0]["months_declining"] == 3


# ── check_category_creep ──────────────────────────────────────────────────────

class TestCategoryCreep:
    def _insert_spending(self, conn, ym, category, amount):
        conn.execute(
            "INSERT INTO transactions (id, account_id, date, amount, currency, category, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"{ym}-{category}", "acc", f"{ym}-15", -amount, "EUR", category, f"{ym}-01"),
        )

    def test_over_20pct_increase_detected(self, conn):
        months = _months_back(6)
        recent = months[:3]   # most recent
        prior = months[3:]    # older
        for m in prior:
            self._insert_spending(conn, m, "Entertainment", 100)
        for m in recent:
            self._insert_spending(conn, m, "Entertainment", 150)
        conn.commit()
        alerts = check_category_creep(conn)
        cats = [a["category"] for a in alerts]
        assert "Entertainment" in cats
        ent = next(a for a in alerts if a["category"] == "Entertainment")
        assert ent["pct_increase"] == pytest.approx(50.0, abs=1)

    def test_under_20pct_increase_not_detected(self, conn):
        months = _months_back(6)
        recent = months[:3]
        prior = months[3:]
        for m in prior:
            self._insert_spending(conn, m, "Groceries", 300)
        for m in recent:
            self._insert_spending(conn, m, "Groceries", 310)
        conn.commit()
        alerts = check_category_creep(conn)
        cats = [a["category"] for a in alerts]
        assert "Groceries" not in cats

    def test_credit_card_payment_transfer_excluded(self, conn):
        """Issue #7: a Credit Card Payment transfer must not be counted as
        spending in a category, or it inflates that category's totals."""
        months = _months_back(6)
        recent = months[:3]
        prior = months[3:]
        for m in prior:
            self._insert_spending(conn, m, "Groceries", 300)
        for m in recent:
            self._insert_spending(conn, m, "Groceries", 300)
        # A large credit-card-payment transfer, mis-tagged with the same
        # category, should not register as a spending increase.
        conn.execute(
            "INSERT INTO transactions (id, account_id, date, amount, currency, category, type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"{recent[0]}-cc", "acc", f"{recent[0]}-20", -2000, "EUR", "Groceries", "transfer", f"{recent[0]}-20"),
        )
        conn.commit()
        alerts = check_category_creep(conn)
        cats = [a["category"] for a in alerts]
        assert "Groceries" not in cats

    def test_tiny_category_ignored(self, conn):
        # prior_avg ≤ 20 should be skipped
        months = _months_back(6)
        for m in months[3:]:
            self._insert_spending(conn, m, "Coffee", 10)
        for m in months[:3]:
            self._insert_spending(conn, m, "Coffee", 30)
        conn.commit()
        alerts = check_category_creep(conn)
        cats = [a["category"] for a in alerts]
        assert "Coffee" not in cats

    def test_no_transactions_returns_empty(self, conn):
        assert check_category_creep(conn) == []


# ── get_accountability_alerts ─────────────────────────────────────────────────

class TestGetAccountabilityAlerts:
    def test_returns_list_with_severity(self, conn):
        # Insert an overdue commitment
        past = (date.today() - timedelta(days=2)).isoformat()
        conn.execute(
            "INSERT INTO journal_entries (entry_type, title, status, due_date) VALUES ('commitment', 'Test', 'open', ?)",
            (past,),
        )
        conn.commit()
        alerts = get_accountability_alerts(conn)
        assert isinstance(alerts, list)
        assert len(alerts) >= 1
        for a in alerts:
            assert "severity" in a
            assert a["severity"] in ("high", "medium", "low")

    def test_severity_ordering(self, conn):
        # Insert overdue commitment (high) and budget pattern (medium)
        past = (date.today() - timedelta(days=1)).isoformat()
        conn.execute(
            "INSERT INTO journal_entries (entry_type, title, status, due_date) VALUES ('commitment', 'C1', 'open', ?)",
            (past,),
        )
        months = _months_back(3)
        for m in months:
            conn.execute(
                "INSERT INTO budget_categories (month, category, limit_amount, actual_amount) VALUES (?, 'Food', 200, 260)",
                (m,),
            )
        conn.commit()
        alerts = get_accountability_alerts(conn)
        sev_order = {"high": 0, "medium": 1, "low": 2}
        severities = [sev_order[a["severity"]] for a in alerts]
        assert severities == sorted(severities)

    def test_empty_db_returns_empty_list(self, conn):
        alerts = get_accountability_alerts(conn)
        assert isinstance(alerts, list)
        assert alerts == []

    def test_high_severity_for_four_months_budget_pattern(self, conn):
        months = _months_back(4)
        for m in months:
            conn.execute(
                "INSERT INTO budget_categories (month, category, limit_amount, actual_amount) VALUES (?, 'Transport', 150, 200)",
                (m,),
            )
        conn.commit()
        alerts = get_accountability_alerts(conn)
        budget_alerts = [a for a in alerts if a["type"] == "budget_pattern"]
        assert len(budget_alerts) == 1
        assert budget_alerts[0]["severity"] == "high"

    def test_three_months_budget_pattern_is_medium(self, conn):
        months = _months_back(3)
        for m in months:
            conn.execute(
                "INSERT INTO budget_categories (month, category, limit_amount, actual_amount) VALUES (?, 'Clothing', 100, 140)",
                (m,),
            )
        conn.commit()
        alerts = get_accountability_alerts(conn)
        budget_alerts = [a for a in alerts if a["type"] == "budget_pattern"]
        assert len(budget_alerts) == 1
        assert budget_alerts[0]["severity"] == "medium"
