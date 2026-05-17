# Finance Assistant — Claude Projects Template

A personal finance assistant for claude.ai users. No installation, no code, no Python. Just paste and chat.

## What this is

A Claude Project pre-configured to act as your financial thinking partner. It remembers your income, goals, debts, and situation across sessions and gives you straight opinions — not generic disclaimers.

## Setup (3 steps)

1. Go to [claude.ai](https://claude.ai) and create a new **Project**
2. Open Project settings → paste the contents of `PROJECT_INSTRUCTIONS.md` into **Project instructions**
3. Start chatting — the assistant will ask a few questions to build your profile on first use

That's it. No API keys, no spreadsheets, no accounts to connect.

## What works (lite mode)

All conversational, no tools required:

- **Budgeting** — log spending, check monthly status, flag overruns
- **Debt strategy** — avalanche vs snowball with your real numbers and interest savings
- **Savings goals** — track progress, project timelines, catch shortfalls early
- **Net worth** — assets minus liabilities, with context on whether you're moving in the right direction
- **Tax questions** — what you can likely deduct based on your country and situation
- **Scenario thinking** — "what if I go freelance?", "can we afford a baby?", "should I rent or buy?"
- **Persistent memory** — your profile is remembered across sessions within this Project

## What doesn't work in lite mode

| Feature | Lite (this template) | Full skill |
|---|---|---|
| CSV / bank statement import | No | Yes |
| Bank sync | No | Yes |
| Monte Carlo FIRE simulations | No | Yes |
| Live portfolio prices | No | Yes |
| Encrypted local storage | No | Yes |
| Locale-specific tax rules (DE, etc.) | Partial | Full |

## Full skill (for power users)

If you use Claude Code and want CSV import, FIRE modeling, and live prices:
**github.com/googlarz/finance-assistant**
