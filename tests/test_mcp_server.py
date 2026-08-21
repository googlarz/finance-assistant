"""Tests for scripts/mcp_server.py.

Skipped entirely when the optional `mcp` dependency isn't installed
(Python 3.10+, `pip install finance-assistant[mcp]`) — most of this
repo's users/CI runs don't need it.
"""
import asyncio

import pytest

pytest.importorskip("mcp")

import mcp_server
from account_manager import add_account
from transaction_logger import add_transaction
from db import init_db


def _call(name, args):
    return asyncio.run(mcp_server.mcp.call_tool(name, args))


def test_registers_five_read_only_tools():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "import_preview", "get_totals", "get_budget_variance",
        "get_net_worth", "get_tax_summary",
    }


def test_get_net_worth_reflects_seeded_account(isolated_finance_dir_db):
    add_account({"name": "Checking", "type": "checking", "current_balance": 5000})
    result = _call("get_net_worth", {})
    assert result.is_error is False
    assert '"net_worth": 5000.0' in result.content[0].text


def test_get_totals_reflects_seeded_transaction(isolated_finance_dir_db):
    add_account({"id": "chk", "name": "Checking", "type": "checking"})
    add_transaction("2026-04-01", "expense", -50, "food", "REWE", account_id="chk")
    result = _call("get_totals", {"account_id": "chk", "year": 2026})
    assert '"expense": 50.0' in result.content[0].text


def test_import_preview_never_commits(isolated_finance_dir_db, tmp_path):
    """Regression: import_preview must always dry-run, regardless of what
    a caller passes — there is no write path through this tool at all."""
    add_account({"id": "chk", "name": "Checking", "type": "checking"})
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("Date,Merchant,Category,Amount\n2026-04-01,Test,Food,-10.00\n")

    result = _call("import_preview", {"file_path": str(csv_file), "account_id": "chk"})
    assert '"imported"' not in result.content[0].text  # dry_run result shape, nothing committed

    from transaction_logger import get_transactions
    assert get_transactions(account_id="chk", year=2026) == []  # nothing was actually written
