"""
Finance Assistant MCP server.

Exposes import preview, totals, budget variance, net worth, and tax
summary as MCP tools, so a claude.ai desktop session (or any MCP client)
can see the same local .finance/ data the skill/CLI use — the
no-terminal/Cowork/claude.ai paths structurally can't reach a local
filesystem or SQLite database, so those users had no route to any of
this at all.

Read tools never write. Write tools are deliberately few and follow the
skill's dry-run-first contract: commit_import() refuses unless the caller
passes the exact `to_import` count that import_preview() just reported.
File access is limited to the project directory (or FINANCE_IMPORT_DIR).
Requires Python 3.10+ and the optional `mcp` dependency
(`pip install finance-assistant[mcp]`).

Claude Desktop config (claude_desktop_config.json):

    {"mcpServers": {"finance-assistant": {
        "command": "python3",
        "args": ["/path/to/finance-assistant/scripts/mcp_server.py"],
        "env": {"FINANCE_PROJECT_DIR": "/path/to/your/project"}}}}

Which .finance/ directory this reads: the same FINANCE_PROJECT_DIR /
CLAUDE_PROJECT_DIR / cwd resolution every other entry point uses (see
finance_storage.get_project_dir()). Point your MCP client config's `cwd`
or `env.FINANCE_PROJECT_DIR` at the Claude Code project directory that
holds your real .finance/ data.

Run directly: python3 scripts/mcp_server.py
"""

from __future__ import annotations

import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))

try:
    from mcp.server.mcpserver import MCPServer
except ImportError as exc:
    raise ImportError(
        "The mcp package is required to run the MCP server: "
        "pip install finance-assistant[mcp]  (needs Python 3.10+)"
    ) from exc


mcp = MCPServer(
    name="finance-assistant",
    instructions=(
        "Local Finance Assistant .finance/ data store: totals, budget variance, "
        "net worth, tax summary, capital gains, reconciliation, import previews. "
        "Writes are limited to commit_import (needs the count from import_preview), "
        "add_account, add_transaction, assert_balance and onboard_step."
    ),
)


def _setup_db() -> None:
    """Mirror skill.py's bootstrap — ensure SQLite is initialized before
    any read, since several engines prefer it when available."""
    try:
        from db import init_db, is_initialized
        if not is_initialized():
            init_db()
        else:
            init_db()  # no-op if already current
    except Exception:
        pass  # degrade to JSON-only reads rather than fail the whole call


def _strip_raw_text(obj):
    """Never return raw file contents over MCP (llm_import echoes them)."""
    if isinstance(obj, dict):
        return {k: _strip_raw_text(v) for k, v in obj.items() if k != "raw_text"}
    if isinstance(obj, list):
        return [_strip_raw_text(v) for v in obj]
    return obj


def _allowed_import_path(file_path: str) -> Optional[str]:
    """Resolve file_path; allow only files under the project dir or FINANCE_IMPORT_DIR."""
    from finance_storage import get_project_dir
    real = os.path.realpath(os.path.expanduser(file_path))
    roots = [str(get_project_dir())]
    if os.environ.get("FINANCE_IMPORT_DIR"):
        roots.append(os.environ["FINANCE_IMPORT_DIR"])
    for root in roots:
        root = os.path.realpath(os.path.expanduser(root))
        if real == root or real.startswith(root + os.sep):
            return real
    return None


@mcp.tool()
def import_preview(file_path: str, account_id: str = "default", currency: str = "EUR") -> dict:
    """Preview a bank statement/CSV import WITHOUT committing it. Returns
    total_parsed, to_import, duplicates_removed, a preview of the first
    rows, and any multi_account_warning / rows_skipped / transfer_residual
    flags. Never writes to storage. file_path must be inside the project
    directory or FINANCE_IMPORT_DIR."""
    _setup_db()
    real = _allowed_import_path(file_path)
    if real is None:
        return {"error": "file_path must be inside the project directory or FINANCE_IMPORT_DIR"}
    from import_router import import_file
    return _strip_raw_text(import_file(real, account_id=account_id, currency=currency,
                                       dry_run=True, keep_original=False))


@mcp.tool()
def get_totals(account_id: str = "all", year: Optional[int] = None, month: Optional[int] = None) -> dict:
    """Income/expense totals grouped by category, converted to the account's
    currency (or the primary currency for account_id="all", the default).
    Omit year for the current year."""
    _setup_db()
    from transaction_logger import get_totals as _get_totals
    return _get_totals(account_id=account_id, year=year, month=month)


@mcp.tool()
def get_budget_variance(year: int, month: Optional[int] = None) -> dict:
    """Planned vs. actual spending by category for a budget period."""
    _setup_db()
    from budget_engine import get_budget_variance as _get_budget_variance
    return _get_budget_variance(year, month)


@mcp.tool()
def get_net_worth() -> dict:
    """Current net worth: total assets, total liabilities, and a
    cash/investments/credit-card/debt breakdown, converted to the
    profile's primary currency."""
    _setup_db()
    from net_worth_engine import calculate_net_worth
    return calculate_net_worth()


@mcp.tool()
def get_tax_summary(year: Optional[int] = None) -> dict:
    """Locale-normalized tax summary for the active profile: gross,
    income_tax, payroll_tax, total_tax, net. Uses the profile's own
    locale/tax settings."""
    _setup_db()
    from tax_engine import get_tax_summary as _get_tax_summary
    return _get_tax_summary(year=year)


@mcp.tool()
def commit_import(file_path: str, expected_to_import: int, account_id: str = "default",
                  currency: str = "EUR") -> dict:
    """Commit an import. Run import_preview first and pass its `to_import`
    count as expected_to_import; a mismatch (file changed, different
    account) refuses to write and returns the fresh preview instead."""
    _setup_db()
    real = _allowed_import_path(file_path)
    if real is None:
        return {"error": "file_path must be inside the project directory or FINANCE_IMPORT_DIR"}
    from import_router import import_file
    preview = import_file(real, account_id=account_id, currency=currency,
                          dry_run=True, keep_original=False)
    if preview.get("error") or preview.get("to_import") != expected_to_import:
        return _strip_raw_text({"error": "preview does not match expected_to_import; nothing written",
                                "preview": preview})
    return _strip_raw_text(import_file(real, account_id=account_id, currency=currency, dry_run=False))


@mcp.tool()
def add_account(name: str, type: str = "checking", currency: str = "EUR",
                current_balance: float = 0.0) -> dict:
    """Create an account (checking, savings, investment, credit_card, loan, mortgage)."""
    _setup_db()
    from account_manager import add_account as _add
    return _add({"name": name, "type": type, "currency": currency,
                 "current_balance": current_balance})


@mcp.tool()
def add_transaction(date: str, amount: float, description: str, account_id: str = "default",
                    category: Optional[str] = None, currency: str = "EUR") -> dict:
    """Add one transaction (negative amount = spending). Category is guessed
    from the description (and past corrections) when omitted."""
    _setup_db()
    from transaction_logger import add_transaction as _add
    ttype = "income" if amount > 0 else "expense"
    return _add(date, ttype, amount, category, description, account_id, currency)["transaction_added"]


@mcp.tool()
def assert_balance(account_id: str, balance: float, on: Optional[str] = None) -> dict:
    """Record a stated account balance (from a statement) for reconciliation."""
    _setup_db()
    from reconciliation import assert_balance as _assert
    return _assert(account_id, balance, on)


@mcp.tool()
def check_reconciliation() -> dict:
    """Money the ledger can't explain between stated balances, per account."""
    _setup_db()
    from reconciliation import check_all, format_alerts
    deltas = check_all()
    return {"deltas": deltas, "messages": format_alerts(deltas)}


@mcp.tool()
def get_capital_gains(year: int, locale: Optional[str] = None) -> dict:
    """Realized capital gains (FIFO) for a year plus a simplified tax estimate
    for the profile's locale (de, uk, ie). Planning aid, not a filing figure."""
    _setup_db()
    from capital_gains import estimate_tax
    return estimate_tax(year, locale)


@mcp.tool()
def onboard_step(step: str, answer: str) -> dict:
    """Parse the user's free-text answer for a setup step (basics, employment,
    housing, goals, debts, investments, accounts, tax, budget), save it, and
    return the parsed data plus what onboarding still needs."""
    _setup_db()
    from onboarding import complete_step, parse_step_response
    parsed = parse_step_response(step, answer)
    if parsed.get("needs_clarification"):
        return parsed
    state = complete_step(step, parsed)
    return {"parsed": parsed, "completed_steps": state.get("completed_steps", [])}


if __name__ == "__main__":
    mcp.run()
