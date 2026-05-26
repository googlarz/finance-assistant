"""
Shared project-local storage helpers for Finance Assistant.

Finance Assistant keeps runtime state in the active project's `.finance/` directory.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


PROFILE_DIRNAME = ".finance"


# Allowlist of tables and their allowed column names.
# Any caller passing a table or column not in this set is rejected.
_ALLOWED_TABLES: frozenset[str] = frozenset({
    "accounts", "transactions", "goals", "debts", "holdings",
    "budget_categories", "net_worth_snapshots", "insurance_policies",
    "journal_entries", "life_events", "audit_log", "recurring_patterns",
    "scenario_results", "session_metadata",
})

def _validate_table(table: str) -> str:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Disallowed table name: {table!r}")
    return table

_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def _validate_column(col: str) -> str:
    # Allow only identifier characters (letters, digits, underscore)
    if not _COLUMN_RE.match(col):
        raise ValueError(f"Disallowed column name: {col!r}")
    return col


# Path-segment safety: account_id and other user-supplied path components are
# inserted into filenames. Reject anything that could escape the directory
# (path separators, dots, control characters) or exceed reasonable length.
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_path_segment(value: str, kind: str = "segment") -> str:
    """Validate a string that will be embedded in a filesystem path.

    Rejects path traversal attempts (../, /, \\), control characters, and
    anything outside a safe identifier alphabet. Raises ValueError if invalid.
    """
    if not isinstance(value, str) or not _PATH_SEGMENT_RE.match(value):
        raise ValueError(
            f"Invalid {kind}: {value!r} "
            f"(must match {_PATH_SEGMENT_RE.pattern})"
        )
    return value


# Public alias — other modules use this to sanitize user-supplied path segments
# before passing them to storage functions or filenames.
validate_path_segment = _validate_path_segment


def get_project_dir() -> Path:
    project_dir = (
        os.environ.get("FINANCE_PROJECT_DIR")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    )
    return Path(project_dir).expanduser().resolve()


def get_finance_dir() -> Path:
    return get_project_dir() / PROFILE_DIRNAME


_dirs_ensured: set[Path] = set()


def ensure_finance_dir() -> Path:
    path = get_finance_dir()
    if path not in _dirs_ensured:
        path.mkdir(parents=True, exist_ok=True)
        _dirs_ensured.add(path)
    return path


def ensure_subdir(*parts: str) -> Path:
    path = ensure_finance_dir().joinpath(*parts)
    if path not in _dirs_ensured:
        path.mkdir(parents=True, exist_ok=True)
        _dirs_ensured.add(path)
    return path


# ── Profile ──────────────────────────────────────────────────────────────────

def get_profile_path() -> Path:
    explicit = os.environ.get("FINANCE_PROFILE_PATH")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return ensure_finance_dir() / "finance_profile.json"


# ── Accounts & Transactions ──────────────────────────────────────────────────

def get_accounts_path() -> Path:
    return ensure_subdir("accounts") / "accounts.json"


def get_transactions_path(account_id: str, year: int) -> Path:
    account_id = _validate_path_segment(account_id, kind="account_id")
    return ensure_subdir("accounts", "transactions") / f"{account_id}_{year}.json"


# ── Budgets ──────────────────────────────────────────────────────────────────

def get_budget_path(year: int, month: int | None = None) -> Path:
    if month:
        return ensure_subdir("budgets") / f"{year}-{month:02d}.json"
    return ensure_subdir("budgets") / f"{year}.json"


# ── Goals ────────────────────────────────────────────────────────────────────

def get_goals_path() -> Path:
    return ensure_subdir("goals") / "goals.json"


# ── Investments ──────────────────────────────────────────────────────────────

def get_portfolio_path() -> Path:
    return ensure_subdir("investments") / "portfolio.json"


def get_investment_snapshot_path(date_str: str) -> Path:
    return ensure_subdir("investments", "snapshots") / f"{date_str}.json"


# ── Debt ─────────────────────────────────────────────────────────────────────

def get_debts_path() -> Path:
    return ensure_subdir("debt") / "debts.json"


def get_payoff_plan_path(plan_id: str) -> Path:
    plan_id = _validate_path_segment(plan_id, kind="plan_id")
    return ensure_subdir("debt", "payoff_plans") / f"{plan_id}.json"


# ── Insurance ────────────────────────────────────────────────────────────────

def get_insurance_path() -> Path:
    return ensure_subdir("insurance") / "policies.json"


# ── Net Worth ────────────────────────────────────────────────────────────────

def get_net_worth_snapshot_path(date_str: str) -> Path:
    return ensure_subdir("net_worth", "snapshots") / f"{date_str}.json"


# ── Taxes ────────────────────────────────────────────────────────────────────

def get_tax_path(locale: str, year: int) -> Path:
    locale = _validate_path_segment(locale, kind="locale")
    return ensure_subdir("taxes", locale) / f"{year}.json"


def get_tax_claims_path(locale: str, year: int) -> Path:
    locale = _validate_path_segment(locale, kind="locale")
    return ensure_subdir("taxes", locale) / f"{year}-claims.json"


# ── Workspace ────────────────────────────────────────────────────────────────

def get_workspace_path(year: int) -> Path:
    return ensure_subdir("workspace") / f"{year}.json"


def get_output_suite_path(year: int) -> Path:
    return ensure_subdir("workspace") / f"{year}-outputs.json"


# ── Imports ──────────────────────────────────────────────────────────────────

def get_import_log_path() -> Path:
    return ensure_subdir("imports") / "import_log.json"


# ── Locales ──────────────────────────────────────────────────────────────────

def get_locale_dir(locale_code: str) -> Path:
    locale_code = _validate_path_segment(locale_code, kind="locale_code")
    return ensure_subdir("locales", locale_code)


# ── Source snapshots (for rule updater) ──────────────────────────────────────

def get_source_snapshot_dir() -> Path:
    return ensure_subdir("source_snapshots")


def get_proposal_dir() -> Path:
    return ensure_subdir("proposals")


# ── Generic I/O ──────────────────────────────────────────────────────────────

def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        tmp.replace(path)  # atomic on POSIX
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return path


# ── SQLite helpers ───────────────────────────────────────────────────────────

def load_from_db(table: str, filters: dict | None = None) -> list[dict]:
    """Read rows from SQLite table, filtered by column equality.
    Falls back to empty list if DB not available.
    """
    try:
        from db import get_conn, is_initialized
        if not is_initialized():
            return []
        table = _validate_table(table)
        clauses = []
        params = []
        if filters:
            for col, val in filters.items():
                _validate_column(col)
                clauses.append(f"{col} = ?")
                params.append(val)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with get_conn() as conn:
            rows = conn.execute(f"SELECT * FROM {table}{where}", params).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def save_to_db(table: str, data: dict, pk_col: str = "id") -> bool:
    """Upsert a single row into a SQLite table.
    Returns True on success, False on failure.
    """
    try:
        from db import get_conn, is_initialized
        if not is_initialized():
            return False
        table = _validate_table(table)
        _validate_column(pk_col)
        cols = list(data.keys())
        for c in cols:
            _validate_column(c)
        placeholders = ", ".join("?" for _ in cols)
        col_names = ", ".join(cols)
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != pk_col)
        sql = (
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT({pk_col}) DO UPDATE SET {updates}"
        )
        with get_conn() as conn:
            conn.execute(sql, [data[c] for c in cols])
        return True
    except Exception:
        return False


# ── Inbox (file drop zone — home-anchored for launchd stability) ─────────────

def get_inbox_dir() -> Path:
    """Global inbox: ~/.finance/inbox/ — stable path for launchd WatchPaths."""
    inbox = Path.home() / ".finance" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    return inbox


def get_inbox_manifest_path() -> Path:
    return get_inbox_dir() / "manifest.json"


def get_inbox_queue_path() -> Path:
    return get_inbox_dir() / "queue.json"


# ── Alert Telemetry ───────────────────────────────────────────────────────────

def get_alert_telemetry_dir() -> Path:
    return ensure_subdir("alert_telemetry")


def get_alert_fire_log_path() -> Path:
    return ensure_subdir("alert_telemetry") / "fire_log.jsonl"


# ── Monitor State ─────────────────────────────────────────────────────────────

def get_monitor_state_path() -> Path:
    return ensure_subdir("workspace") / "monitor_state.json"


# ── Migration from .taxde/ ───────────────────────────────────────────────────

def get_legacy_taxde_dir() -> Path:
    return get_project_dir() / ".taxde"


def has_legacy_data() -> bool:
    legacy = get_legacy_taxde_dir()
    return legacy.exists() and (legacy / "taxde_profile.json").exists()
