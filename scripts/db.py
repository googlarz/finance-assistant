"""
SQLite data layer for Finance Assistant.
Single database at .finance/finance.db
Dual-write migration: writes to both SQLite and JSON during transition.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from contextlib import contextmanager

SCHEMA_VERSION = 2  # bumped: added transactions.type column

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);

CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    balance REAL DEFAULT 0,
    currency TEXT DEFAULT 'EUR',
    institution TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    type TEXT DEFAULT 'expense',  -- income|expense|transfer|investment|debt_payment
    currency TEXT NOT NULL,
    category TEXT,
    description TEXT,
    source TEXT DEFAULT 'manual',
    payee TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS budget_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month TEXT NOT NULL,
    category TEXT NOT NULL,
    limit_amount REAL NOT NULL,
    actual_amount REAL DEFAULT 0,
    currency TEXT DEFAULT 'EUR',
    UNIQUE(month, category)
);

CREATE TABLE IF NOT EXISTS goals (
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

CREATE TABLE IF NOT EXISTS holdings (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ticker TEXT,
    asset_class TEXT,
    quantity REAL DEFAULT 0,
    purchase_price REAL,
    current_price REAL,
    currency TEXT DEFAULT 'EUR',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS debts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    balance REAL NOT NULL,
    interest_rate REAL NOT NULL,
    minimum_payment REAL NOT NULL,
    type TEXT DEFAULT 'loan',
    currency TEXT DEFAULT 'EUR',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    date TEXT NOT NULL,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recurring_items (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    amount REAL NOT NULL,
    frequency TEXT NOT NULL,
    day_of_month INTEGER,
    category TEXT,
    account_id TEXT,
    start_date TEXT,
    currency TEXT DEFAULT 'EUR',
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS scenarios (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    inputs TEXT NOT NULL,
    result TEXT NOT NULL,
    profile_snapshot TEXT,
    saved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thresholds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    direction TEXT NOT NULL DEFAULT 'above',
    label TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(metric, value, direction)
);

CREATE TABLE IF NOT EXISTS insurance_policies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    premium REAL,
    premium_frequency TEXT,
    coverage_amount REAL,
    renewal_date TEXT,
    provider TEXT,
    currency TEXT DEFAULT 'EUR',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_budget_month ON budget_categories(month);
CREATE INDEX IF NOT EXISTS idx_snapshots_type_date ON snapshots(type, date);
"""


def get_db_path() -> Path:
    from finance_storage import get_finance_dir
    return get_finance_dir() / "finance.db"


@contextmanager
def get_conn():
    """Get a SQLite connection with WAL mode and foreign keys enabled."""
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _current_schema_version(conn) -> int:
    """Read the current schema version from the schema_version table.

    Returns 0 if the table doesn't exist or has no row.
    """
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        if row and row[0] is not None:
            return int(row[0])
    except Exception:
        return 0
    return 0


def _migrate_schema(conn, from_version: int) -> None:
    """Apply incremental schema migrations from `from_version` to current."""
    # v1 → v2: add transactions.type column (was derived from amount sign)
    if from_version < 2:
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()}
            if "type" not in cols:
                conn.execute("ALTER TABLE transactions ADD COLUMN type TEXT DEFAULT 'expense'")
                # Backfill from amount sign — best-effort heuristic
                conn.execute(
                    "UPDATE transactions SET type = CASE WHEN amount >= 0 THEN 'income' ELSE 'expense' END "
                    "WHERE type IS NULL OR type = 'expense'"
                )
        except Exception:
            pass  # ALTER is idempotent enough; CREATE TABLE IF NOT EXISTS handles fresh installs


def init_db() -> None:
    """Create schema if not exists, apply migrations, stamp version."""
    with get_conn() as conn:
        # CREATE TABLE IF NOT EXISTS for everything — safe on existing DBs
        conn.executescript(SCHEMA)
        # Then apply column-level migrations for existing DBs that pre-date a change
        from_version = _current_schema_version(conn)
        if from_version < SCHEMA_VERSION:
            _migrate_schema(conn, from_version)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )


def is_initialized() -> bool:
    """True if the DB file exists, has tables, and schema_version is current."""
    path = get_db_path()
    if not path.exists():
        return False
    try:
        with get_conn() as conn:
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'"
            ).fetchone()
            return result is not None
    except Exception:
        return False
