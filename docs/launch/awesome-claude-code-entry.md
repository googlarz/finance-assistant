# awesome-claude-code PR entry

Submit to: https://github.com/hesreallyhim/awesome-claude-code

Add to the **Skills** section (or **Plugins** — check current taxonomy):

```markdown
- [Finance Assistant](https://github.com/googlarz/finance-assistant) — Personal finance copilot: budgets, multi-locale taxes (DE/AT/CH/UK/US/ES), FIRE Monte Carlo, debt strategies, subscription detection, encrypted backup. Local-first, 14 bank-CSV importers, audit log. Try the [live demo](https://googlarz.github.io/finance-assistant/) without installing.
```

## PR body template

```
Adds Finance Assistant — a personal finance Claude Code skill (1.4k LOC, 1170+ tests).

Categorization: Skills > Personal / Productivity

Live demo (no install required) at https://googlarz.github.io/finance-assistant/ so reviewers can see what it does without committing real data.

What it covers: budgeting, multi-country tax calculations (6 locales), FIRE simulation, debt payoff strategies, recurring subscription detection, encrypted backup, bank CSV import (14 formats incl. DKB, ING, Chase, Monarch, YNAB), weekly digest via launchd cron.

All data lives in the user's `.finance/` directory. No cloud, no API keys to anyone but the user.
```
