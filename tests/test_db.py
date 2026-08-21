"""
Tests for the SQLite data layer (db.py) and migration (db_migrate.py).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure scripts/ is on path (conftest also does this, but be explicit)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_db():
    from db import init_db, get_conn, is_initialized, get_db_path
    return init_db, get_conn, is_initialized, get_db_path


# ── Schema creation ───────────────────────────────────────────────────────────

EXPECTED_TABLES = [
    "profile", "accounts", "transactions", "budget_categories", "goals",
    "holdings", "debts", "snapshots", "recurring_items", "scenarios",
    "thresholds", "insurance_policies",
]


def test_init_db_creates_all_tables():
    from db import init_db, get_conn
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    table_names = {r["name"] for r in rows}
    for table in EXPECTED_TABLES:
        assert table in table_names, f"Missing table: {table}"


def test_wal_mode_enabled():
    from db import init_db, get_conn
    init_db()
    with get_conn() as conn:
        row = conn.execute("PRAGMA journal_mode").fetchone()
    assert row[0] == "wal"


# ── is_initialized ────────────────────────────────────────────────────────────

def test_is_initialized_false_before_init(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    from db import is_initialized
    assert is_initialized() is False


def test_is_initialized_true_after_init():
    from db import init_db, is_initialized
    init_db()
    assert is_initialized() is True


# ── Transaction insert + read roundtrip ───────────────────────────────────────

def test_transaction_insert_read_roundtrip():
    from db import init_db, get_conn
    init_db()
    now = "2026-04-01T10:00:00"
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO transactions
               (id, account_id, date, amount, currency, category, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("txn-001", "checking", "2026-04-01", -50.0, "EUR", "food", "Supermarket", now),
        )
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM transactions WHERE id='txn-001'").fetchone()
    assert row is not None
    assert row["amount"] == -50.0
    assert row["category"] == "food"
    assert row["account_id"] == "checking"


# ── get_transactions account_id filter ───────────────────────────────────────

def test_get_transactions_account_filter():
    from db import init_db, get_conn
    init_db()
    now = "2026-04-01T10:00:00"
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO transactions
               (id, account_id, date, amount, currency, category, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("t1", "acc-a", "2026-04-01", -10.0, "EUR", "food", "A", now),
                ("t2", "acc-b", "2026-04-01", -20.0, "EUR", "dining", "B", now),
                ("t3", "acc-a", "2026-04-02", -30.0, "EUR", "food", "C", now),
            ],
        )
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE account_id = ?", ("acc-a",)
        ).fetchall()
    assert len(rows) == 2
    ids = {r["id"] for r in rows}
    assert ids == {"t1", "t3"}


# ── get_transactions date range filter ───────────────────────────────────────

def test_get_transactions_date_range_filter():
    from db import init_db, get_conn
    init_db()
    now = "2026-04-01T10:00:00"
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO transactions
               (id, account_id, date, amount, currency, category, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("r1", "acc", "2026-03-15", -5.0, "EUR", "food", "March", now),
                ("r2", "acc", "2026-04-10", -10.0, "EUR", "food", "April", now),
                ("r3", "acc", "2026-05-01", -15.0, "EUR", "food", "May", now),
            ],
        )
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE date LIKE ?", ("2026-04-%",)
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == "r2"


# ── Deduplication ─────────────────────────────────────────────────────────────

def test_insert_same_id_twice_yields_one_row():
    from db import init_db, get_conn
    init_db()
    now = "2026-04-01T10:00:00"
    sql = """INSERT OR IGNORE INTO transactions
             (id, account_id, date, amount, currency, category, description, created_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
    row_data = ("dup-001", "acc", "2026-04-01", -50.0, "EUR", "food", "Store", now)
    with get_conn() as conn:
        conn.execute(sql, row_data)
        conn.execute(sql, row_data)  # second insert should be ignored
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM transactions WHERE id='dup-001'"
        ).fetchone()["c"]
    assert count == 1


# ── Budget variance query ─────────────────────────────────────────────────────

def test_budget_variance_query():
    from db import init_db, get_conn
    init_db()
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO budget_categories
               (month, category, limit_amount, actual_amount, currency)
               VALUES (?, ?, ?, ?, ?)""",
            [
                ("2026-04", "food", 500.0, 420.0, "EUR"),
                ("2026-04", "dining", 200.0, 250.0, "EUR"),
                ("2026-04", "transport", 150.0, 150.0, "EUR"),
            ],
        )
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT category,
                      limit_amount,
                      actual_amount,
                      (limit_amount - actual_amount) as variance
               FROM budget_categories
               WHERE month = '2026-04'
               ORDER BY category""",
        ).fetchall()
    result = {r["category"]: dict(r) for r in rows}
    assert result["food"]["variance"] == pytest.approx(80.0)
    assert result["dining"]["variance"] == pytest.approx(-50.0)
    assert result["transport"]["variance"] == pytest.approx(0.0)


# ── Migration ─────────────────────────────────────────────────────────────────

def test_migration_imports_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    # Write a JSON accounts file
    accounts_dir = tmp_path / ".finance" / "accounts"
    accounts_dir.mkdir(parents=True)
    (accounts_dir / "accounts.json").write_text(json.dumps({
        "accounts": [
            {"id": "dkb", "name": "DKB", "type": "checking",
             "current_balance": 1000, "currency": "EUR",
             "institution": "DKB", "as_of": "2026-04-01"},
        ]
    }))
    from db import init_db, is_initialized
    from db_migrate import migrate_all
    from finance_storage import get_finance_dir
    init_db()
    result = migrate_all(get_finance_dir())
    assert "accounts" in result["migrated"]
    assert result["migrated"]["accounts"] == 1
    assert not result["errors"]

    from db import get_conn
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id='dkb'").fetchone()
    assert row is not None
    assert row["name"] == "DKB"


def test_migration_imports_transactions(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    txn_dir = tmp_path / ".finance" / "accounts" / "transactions"
    txn_dir.mkdir(parents=True)
    (txn_dir / "default_2026.json").write_text(json.dumps({
        "transactions": [
            {"id": "t1", "account_id": "default", "date": "2026-04-01",
             "amount": -50.0, "currency": "EUR", "category": "food",
             "description": "Store"},
            {"id": "t2", "account_id": "default", "date": "2026-04-05",
             "amount": 2000.0, "currency": "EUR", "category": "salary",
             "description": "Paycheck"},
        ]
    }))
    from db import init_db
    from db_migrate import migrate_all
    from finance_storage import get_finance_dir
    init_db()
    result = migrate_all(get_finance_dir())
    assert result["migrated"].get("transactions") == 2

    from db import get_conn
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) as c FROM transactions").fetchone()["c"]
    assert count == 2


def test_migration_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    accounts_dir = tmp_path / ".finance" / "accounts"
    accounts_dir.mkdir(parents=True)
    (accounts_dir / "accounts.json").write_text(json.dumps({
        "accounts": [
            {"id": "abc", "name": "ABC Bank", "type": "savings",
             "current_balance": 500, "currency": "EUR",
             "institution": "ABC", "as_of": "2026-04-01"},
        ]
    }))
    from db import init_db, get_conn
    from db_migrate import migrate_all
    from finance_storage import get_finance_dir
    init_db()
    finance_dir = get_finance_dir()

    # Run migration twice
    result1 = migrate_all(finance_dir)
    result2 = migrate_all(finance_dir)

    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) as c FROM accounts WHERE id='abc'").fetchone()["c"]
    assert count == 1  # still only one row after second run
    assert not result1["errors"]
    assert not result2["errors"]


# ── Legacy DB upgrade (migration ordering) ──────────────────────────────────────

def _make_legacy_v0_db(tmp_path):
    """Create a pre-`type`-column transactions table with no schema_version row,
    simulating a DB created before SCHEMA_VERSION 2 shipped."""
    import sqlite3
    from db import get_db_path
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE transactions (
            id TEXT PRIMARY KEY,
            account_id TEXT,
            date TEXT,
            amount REAL,
            currency TEXT,
            category TEXT,
            description TEXT,
            source TEXT,
            payee TEXT,
            created_at TEXT
        );
        INSERT INTO transactions (id, account_id, date, amount, currency, category, created_at)
        VALUES ('t1', 'a1', '2026-01-01', -50.0, 'EUR', 'food', '2026-01-01T00:00:00');
        """
    )
    conn.commit()
    conn.close()
    return path


def test_init_db_upgrades_legacy_db_without_type_column(tmp_path, monkeypatch):
    """Regression: init_db() must self-heal a v0 DB — add transactions.type,
    create the type index, and stamp the version — without raising."""
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    _make_legacy_v0_db(tmp_path)

    from db import init_db, get_conn, SCHEMA_VERSION
    init_db()  # must not raise "no such column: type"

    with get_conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()}
        assert "type" in cols, "migration did not add transactions.type"

        idx = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
        assert "idx_transactions_type" in idx, "type index not created after migration"

        ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert ver == SCHEMA_VERSION, f"version not stamped: {ver}"

        # Existing row backfilled from amount sign (negative -> expense)
        t = conn.execute("SELECT type FROM transactions WHERE id='t1'").fetchone()[0]
        assert t == "expense"


def test_init_db_legacy_upgrade_is_idempotent(tmp_path, monkeypatch):
    """Running init_db() twice on a legacy DB stays clean."""
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    _make_legacy_v0_db(tmp_path)
    from db import init_db, get_conn, SCHEMA_VERSION
    init_db()
    init_db()
    with get_conn() as conn:
        ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert ver == SCHEMA_VERSION


# ── v2 → v3 upgrade: transfer_peer_id column (#8) ────────────────────────────

def _make_v2_db(tmp_path):
    """A DB with the type column but no transfer_peer_id, version stamped 2 —
    simulating an install that pre-dates SCHEMA_VERSION 3."""
    import sqlite3
    from db import get_db_path
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
        CREATE TABLE transactions (
            id TEXT PRIMARY KEY,
            account_id TEXT,
            date TEXT,
            amount REAL,
            type TEXT DEFAULT 'expense',
            currency TEXT,
            category TEXT,
            description TEXT,
            source TEXT,
            payee TEXT,
            created_at TEXT
        );
        INSERT INTO schema_version (version) VALUES (2);
        INSERT INTO transactions (id, account_id, date, amount, type, currency, created_at)
        VALUES ('t1', 'a1', '2026-01-01', -50.0, 'expense', 'EUR', '2026-01-01T00:00:00');
        """
    )
    conn.commit()
    conn.close()
    return path


def test_init_db_upgrades_v2_db_without_transfer_peer_id(tmp_path, monkeypatch):
    """Regression: init_db() must self-heal a v2 DB — add
    transactions.transfer_peer_id and stamp v3 — without raising, and must
    not disturb the existing row."""
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    _make_v2_db(tmp_path)

    from db import init_db, get_conn, SCHEMA_VERSION
    init_db()  # must not raise "no such column: transfer_peer_id"

    with get_conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()}
        assert "transfer_peer_id" in cols
        assert "subcategory" in cols

        ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert ver == SCHEMA_VERSION

        row = conn.execute("SELECT * FROM transactions WHERE id='t1'").fetchone()
        assert row["type"] == "expense"
        assert row["transfer_peer_id"] is None
        assert row["subcategory"] is None


def test_init_db_v2_upgrade_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    _make_v2_db(tmp_path)
    from db import init_db, get_conn, SCHEMA_VERSION
    init_db()
    init_db()
    with get_conn() as conn:
        ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert ver == SCHEMA_VERSION


def _make_v3_db(tmp_path):
    """A DB with the OLD accounts.balance column name (no current_balance,
    no is_asset), version stamped 3 — simulating an install that pre-dates
    SCHEMA_VERSION 4. Has one liability-type account (credit_card) to prove
    the is_asset backfill classifies it correctly, not just adds the column."""
    import sqlite3
    from db import get_db_path
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
        CREATE TABLE accounts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            balance REAL DEFAULT 0,
            currency TEXT DEFAULT 'EUR',
            institution TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE transactions (
            id TEXT PRIMARY KEY,
            account_id TEXT,
            date TEXT,
            amount REAL,
            type TEXT DEFAULT 'expense',
            currency TEXT,
            category TEXT,
            description TEXT,
            source TEXT,
            payee TEXT,
            subcategory TEXT,
            transfer_peer_id TEXT,
            created_at TEXT
        );
        INSERT INTO schema_version (version) VALUES (3);
        INSERT INTO accounts (id, name, type, balance, currency, updated_at)
        VALUES ('chk', 'Checking', 'checking', 1000.0, 'EUR', '2026-01-01');
        INSERT INTO accounts (id, name, type, balance, currency, updated_at)
        VALUES ('visa', 'Visa', 'credit_card', -450.0, 'EUR', '2026-01-01');
        """
    )
    conn.commit()
    conn.close()
    return path


def test_init_db_upgrades_v3_db_renames_balance_and_backfills_is_asset(tmp_path, monkeypatch):
    """Regression: init_db() must self-heal a v3 DB — rename accounts.balance
    to current_balance (was silently diverging from the JSON schema's field
    name), add is_asset/as_of/include_in_net_worth/include_in_budget/notes,
    and backfill is_asset=0 for existing liability-type rows so they don't
    default to True (misclassified as an asset) — without disturbing the
    existing balances."""
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    _make_v3_db(tmp_path)

    from db import init_db, get_conn, SCHEMA_VERSION
    init_db()  # must not raise "no such column: current_balance"

    with get_conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()}
        assert "current_balance" in cols
        assert "balance" not in cols  # renamed, not duplicated
        assert "is_asset" in cols
        assert "as_of" in cols
        assert "include_in_net_worth" in cols
        assert "include_in_budget" in cols
        assert "notes" in cols

        ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert ver == SCHEMA_VERSION

        chk = conn.execute("SELECT * FROM accounts WHERE id='chk'").fetchone()
        assert chk["current_balance"] == 1000.0
        assert bool(chk["is_asset"]) is True

        visa = conn.execute("SELECT * FROM accounts WHERE id='visa'").fetchone()
        assert visa["current_balance"] == -450.0
        assert bool(visa["is_asset"]) is False  # backfilled, not defaulted to True

        tx_cols = {r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()}
        for col in ("is_recurring", "tags", "tax_relevant", "tax_category", "business_use_pct", "import_ref"):
            assert col in tx_cols


def test_init_db_v3_upgrade_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    _make_v3_db(tmp_path)
    from db import init_db, get_conn, SCHEMA_VERSION
    init_db()
    init_db()
    with get_conn() as conn:
        ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        cols = {r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    assert ver == SCHEMA_VERSION
    assert "current_balance" in cols
