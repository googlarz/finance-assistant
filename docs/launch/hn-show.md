# HN Show post (draft)

## Title (≤ 80 chars)

`Show HN: Finance Assistant — local-first personal finance copilot for Claude Code`

## Body

I built Finance Assistant because every cloud PFM I tried wanted my bank credentials, my account balances, and a monthly subscription — for what amounted to category tagging and pretty charts.

This one lives entirely on your machine. Drop a bank CSV into an inbox folder, get a notification when it's parsed, ask Claude things like "did I overspend on dining this month?" or "what's my real after-tax income on €80k freelance in Berlin?". No cloud sync, no telemetry, no API keys to anyone but you.

What's in this release (v3.7.1):
- 6 country tax engines (DE, AT, CH, UK, US, ES) — actual bracket-accurate calculations, not estimates
- 14 bank CSV importers (DKB, ING, Sparkasse, N26, Chase, Bank of America, Wells Fargo, Monarch, YNAB, Mint, Revolut, Wise, Commerzbank, Capital One)
- SQLite + JSON dual storage, encrypted backup, audit log of every mutation
- Detects recurring subscriptions you forgot about (and flags potential double-billings)
- FIRE calculator with Monte Carlo, debt avalanche/snowball comparison, portfolio drift alerts
- Weekly digest via launchd cron — no Claude session needed for the scheduled run

Hard limits I deliberately kept:
- No bank API integration in v1 (Plaid/SimpleFin is on the roadmap for v3.8). You import CSVs.
- macOS for the launchd-scheduled bits; the rest is plain Python.
- It's a Claude Code skill — you need Claude Code installed.

Live demo (no install): https://googlarz.github.io/finance-assistant/
Repo: https://github.com/googlarz/finance-assistant

Happy to answer questions about the architecture (SQLite schema, dedup strategy, encrypted-at-rest model, why I chose Fernet + PBKDF2 for backup, the locale plugin system).

---

## Notes for posting

- Post on weekday morning US Pacific time (best HN traffic).
- Reply to early questions within 10 minutes — drives engagement.
- Don't editorialize headlines on subsequent comments.
- If asked about "why not Plaid": "Plaid requires backend infrastructure; this is a single-user CLI tool. SimpleFin is on the roadmap because it works without OAuth backend."
