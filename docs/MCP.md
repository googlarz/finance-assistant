# MCP Server

`scripts/mcp_server.py` exposes read-only access to your local `.finance/`
data as MCP tools, so a claude.ai desktop session (or any MCP client) can
see your numbers without a terminal — the structural gap the no-terminal
claude.ai/Cowork paths otherwise hit (no CSV import, no local database, no
bank sync at all).

## Why read-only

This is a v1 scope decision, not a technical limit: every tool either
reads data or previews an import without committing it (`import_preview`
always runs a dry-run). Nothing here writes to `.finance/`. Committing an
import or any other mutation stays a skill/CLI-only action.

## Requirements

- Python 3.10+ (the project's baseline as of this release)
- `pip install "finance-assistant[mcp]"` (or `pip install mcp>=1.0.0`
  alongside the base install)

## Tools

| Tool | Wraps |
|------|-------|
| `import_preview(file_path, account_id="default", currency="EUR")` | `import_router.import_file(..., dry_run=True)` |
| `get_totals(account_id="default", year=None, month=None)` | `transaction_logger.get_totals()` |
| `get_budget_variance(year, month=None)` | `budget_engine.get_budget_variance()` |
| `get_net_worth()` | `net_worth_engine.calculate_net_worth()` |
| `get_tax_summary(year=None)` | `tax_engine.get_tax_summary()` |

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
