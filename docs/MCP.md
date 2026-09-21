# MCP Server

`scripts/mcp_server.py` exposes read-only access to your local `.finance/`
data as MCP tools, so a claude.ai desktop session (or any MCP client) can
see your numbers without a terminal — the structural gap the no-terminal
claude.ai/Cowork paths otherwise hit (no CSV import, no local database, no
bank sync at all).

## Read vs. write

Read tools never write. The few write tools follow the skill's
dry-run-first contract: `commit_import` refuses unless you pass the exact
`to_import` count that `import_preview` just reported, so an import can't
be committed blind. `import_preview` and `commit_import` only read files
inside the project directory (or `FINANCE_IMPORT_DIR`), never return raw
file contents, and preview never copies the file into `.finance/originals/`.

## Requirements

- Python 3.10+
- `pip install "finance-assistant[mcp]"` (or `pip install "mcp>=2.0.0"`
  alongside the base install)

## Claude Desktop config

```json
{
  "mcpServers": {
    "finance-assistant": {
      "command": "python3",
      "args": ["/path/to/finance-assistant/scripts/mcp_server.py"],
      "env": {"FINANCE_PROJECT_DIR": "/path/to/your/project"}
    }
  }
}
```

## Tools

| Tool | Kind | Wraps |
|------|------|-------|
| `import_preview(file_path, account_id="default", currency="EUR")` | read | `import_router.import_file(..., dry_run=True)` |
| `get_totals(account_id="all", year=None, month=None)` | read | `transaction_logger.get_totals()` (all accounts, primary currency, by default) |
| `get_budget_variance(year, month=None)` | read | `budget_engine.get_budget_variance()` |
| `get_net_worth()` | read | `net_worth_engine.calculate_net_worth()` |
| `get_tax_summary(year=None)` | read | `tax_engine.get_tax_summary()` |
| `get_capital_gains(year, locale=None)` | read | `capital_gains.estimate_tax()` |
| `check_reconciliation()` | read | `reconciliation.check_all()` |
| `commit_import(file_path, expected_to_import, account_id, currency)` | write | `import_router.import_file(..., dry_run=False)` |
| `add_account(name, type, currency, current_balance)` | write | `account_manager.add_account()` |
| `add_transaction(date, amount, description, account_id, category, currency)` | write | `transaction_logger.add_transaction()` |
| `assert_balance(account_id, balance, on)` | write | `reconciliation.assert_balance()` |
| `onboard_step(step, answer)` | write | `onboarding.parse_step_response()` + `complete_step()` |

## Which `.finance/` directory

Same resolution every other entry point uses: `FINANCE_PROJECT_DIR` env
var, then `CLAUDE_PROJECT_DIR`, then the working directory the server
was launched from. Point your MCP client config's `cwd` (or
`env.FINANCE_PROJECT_DIR`) at the Claude Code project directory that
holds your real `.finance/` data — otherwise the server will look for
data wherever it happens to be launched from and may bootstrap a fresh,
empty store there.

## Running it

```bash
python3 scripts/mcp_server.py
```

Runs over stdio, the standard MCP transport — configure your MCP client
(Claude Desktop, etc.) to launch this command directly.
