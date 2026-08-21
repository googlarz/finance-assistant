"""
Finance Assistant MCP server — read-only.

Exposes import preview, totals, budget variance, net worth, and tax
summary as MCP tools, so a claude.ai desktop session (or any MCP client)
can see the same local .finance/ data the skill/CLI use — the
no-terminal/Cowork/claude.ai paths structurally can't reach a local
filesystem or SQLite database, so those users had no route to any of
this at all.

Read-only by design (#12 scope decision): nothing here writes to
.finance/. import_preview() always runs a dry-run — it can never commit
an import. Requires Python 3.10+ and the optional `mcp` dependency
(`pip install finance-assistant[mcp]`).

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
        "Read-only access to a local Finance Assistant .finance/ data store: "
        "transaction totals, budget variance, net worth, tax summary, and "
        "CSV/statement import previews. Never writes or commits anything — "
        "import_preview always runs a dry-run."
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


@mcp.tool()
def import_preview(file_path: str, account_id: str = "default", currency: str = "EUR") -> dict:
    """Preview a bank statement/CSV import WITHOUT committing it. Returns
    total_parsed, to_import, duplicates_removed, a preview of the first
    rows, and any multi_account_warning / rows_skipped / transfer_residual
    flags. Never writes to storage."""
    _setup_db()
    from import_router import import_file
    return import_file(file_path, account_id=account_id, currency=currency, dry_run=True)


@mcp.tool()
def get_totals(account_id: str = "default", year: Optional[int] = None, month: Optional[int] = None) -> dict:
    """Income/expense totals grouped by category for one account, converted
    to that account's own currency. Omit year for the current year."""
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


if __name__ == "__main__":
    mcp.run()
