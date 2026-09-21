# Plugin / skill directory listing

## Name
Finance Assistant

## Short description (under 160 chars)
Local-first personal finance for Claude Code: deterministic tax engines for 7 countries, bank CSV import, budgets, net worth, FIRE Monte Carlo.

## Long description
Finance Assistant lets Claude Code answer money questions using your real numbers. The language model handles the conversation; deterministic Python engines compute the tax, budget and projection figures.

- Tax engines for Germany, UK, US, France, Netherlands, Poland and Ireland, validated against 39 official tax-authority test cases.
- Imports 14 bank CSV formats; other files (scans, screenshots, foreign banks) are read by Claude through the same dedupe-and-confirm pipeline.
- Budgets, debt avalanche/snowball, net worth, FIRE with a 10,000-path Monte Carlo, saveable tax what-ifs.
- Data stays in a local `.finance/` folder (SQLite/JSON), with optional Fernet encryption and an audit log.
- MCP server (Python 3.10+) exposing read tools plus dry-run-first write tools.

Limits: software, not a licensed advisor. The DE/UK/IE capital-gains estimate uses rates checked against primary sources (2026-09-21) but a simplified model: a planning aid, not a filing figure. Claude Code sends the conversation to Anthropic by default; only on-disk data is local. Opt-in network calls (FX rates, prices, GoCardless bank sync) are listed in docs/SECURITY.md.

## Categories
Finance, Productivity, Data & Analytics, Privacy/Local-first. Suggested tags: personal-finance, tax, budgeting, fire, mcp, local-first.

## Install
```bash
git clone --recurse-submodules https://github.com/googlarz/finance-assistant.git ~/.claude/skills/finance-assistant && pip install -r ~/.claude/skills/finance-assistant/requirements.txt
```
Verify: `python3 ~/.claude/skills/finance-assistant/skill.py --doctor`. Try: `python3 ~/.claude/skills/finance-assistant/skill.py --demo`.

## Repo / license
https://github.com/googlarz/finance-assistant , CC BY 4.0. Version 4.1.0 (4.2.0 in progress).

## Screenshots / media to attach
1. `assets/demo.svg` (animated terminal replay; check the directory accepts SVG, else record a GIF)
2. `assets/dashboard-preview.jpg` (dashboard)
3. Capture of the FIRE Monte Carlo conversation (README example) after re-running it yourself
4. Capture of the W-2 vs 1099 conversation, likewise
