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


def test_registers_expected_tools():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "import_preview", "get_totals", "get_budget_variance",
        "get_net_worth", "get_tax_summary", "commit_import", "add_account",
        "add_transaction", "assert_balance", "check_reconciliation",
        "get_capital_gains", "onboard_step",
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


def test_import_preview_refuses_paths_outside_project(tmp_path, monkeypatch):
    outside = tmp_path.parent / "outside.csv"
    outside.write_text("secret,1\n")
    result = _call("import_preview", {"file_path": str(outside)})
    assert "must be inside the project directory" in result.content[0].text


def test_import_preview_never_returns_raw_text_or_copies_original(isolated_finance_dir):
    f = isolated_finance_dir / "notes.txt"
    f.write_text("SECRET-TOKEN-123 some free text")
    text = _call("import_preview", {"file_path": str(f)}).content[0].text
    assert "SECRET-TOKEN-123" not in text
    assert not list((isolated_finance_dir / ".finance" / "originals").glob("*")) \
        if (isolated_finance_dir / ".finance" / "originals").exists() else True


def test_commit_import_requires_matching_preview_count(isolated_finance_dir):
    f = isolated_finance_dir / "s.csv"
    f.write_text("date,amount,description\n2026-01-04,-42.00,REWE MARKT\n")
    bad = _call("commit_import", {"file_path": str(f), "expected_to_import": 99}).content[0].text
    assert "nothing written" in bad
    ok = _call("commit_import", {"file_path": str(f), "expected_to_import": 1}).content[0].text
    assert '"imported": 1' in ok


def test_write_tools_roundtrip(isolated_finance_dir_db):
    _call("add_account", {"name": "Main", "type": "checking", "current_balance": 10})
    _call("add_transaction", {"date": "2026-02-01", "amount": -25.0,
                              "description": "Coffee", "account_id": "main"})
    totals = _call("get_totals", {"account_id": "main", "year": 2026}).content[0].text
    assert "25.0" in totals
