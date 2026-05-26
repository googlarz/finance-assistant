# Product Hunt launch (draft)

## Name
Finance Assistant

## Tagline (≤ 60 chars)
Local-first personal finance copilot. No cloud, no banks.

## Description (260 chars)
A Claude Code skill that turns your bank CSVs into a private finance copilot. Budgets, taxes, FIRE simulations, subscription detection, debt strategies — all on your machine. 6 locales, 14 bank importers, encrypted backups, weekly digests.

## First comment

Hey PH 👋

I'm Dawid, the maker.

Finance Assistant exists because every PFM I tried asked me to hand over my bank credentials in exchange for category tagging. This one runs entirely on your laptop:

- Drop a bank CSV in an inbox folder → it's parsed and queued
- Ask Claude "did I overspend on dining last month?" → real answer with numbers
- Run "what's my real after-tax on €80k freelance in Berlin" → bracket-accurate calculation
- Detects recurring subscriptions, flags double-billings, compares debt-payoff strategies

What this is NOT (yet): a Plaid-style bank-sync app. v1 is CSV-import. Real-time sync is on the v3.8 roadmap.

Try the no-install demo first: https://googlarz.github.io/finance-assistant/

Happy to answer anything. Bug reports, locale requests (especially AT/CH where I have placeholder scaffolds), and architecture questions all welcome.

## Topics
Personal finance · Productivity · Open Source · Privacy · Claude

## Gallery suggestions
1. Session start with live alerts (screenshot from docs/index.html demo)
2. German tax calculation breakdown
3. FIRE Monte Carlo result chart
4. Bank import reconciliation ("87 parsed · 74 new · 13 duplicates skipped")
