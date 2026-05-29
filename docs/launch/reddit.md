# Reddit posts (drafts)

---

## /r/personalfinance — DO NOT POST WITHOUT MOD APPROVAL

Title: `I built a local-first personal finance app that runs entirely on your machine — no bank credentials, no cloud, open source`

PF has a no-promotion rule. **Email the mods first**, link to repo, ask if a Show/Save thread is appropriate. If they decline, post in /r/personalfinanceeurope or /r/financialindependence instead.

---

## /r/financialindependence

Title: `Built an open-source FIRE calculator that runs locally — Monte Carlo, multi-locale tax engines, no cloud`

Body:

I needed a FIRE calculator that:
1. Did Monte Carlo (not just deterministic 4% rule projections)
2. Knew German freelance taxes (where I am) so the "what's my real savings rate" question wasn't a fiction
3. Didn't want my bank credentials or a subscription

Couldn't find one, built one. Finance Assistant is a **Claude Code skill** (free CLI from Anthropic — not the web app) that takes bank CSV imports and does the math locally:

- Monte Carlo FIRE simulation (10,000 paths default, configurable)
- 6 country tax engines (DE, FR, NL, PL, UK, US) — actual brackets, not estimates
- Detects recurring subscriptions you forgot about
- Encrypted backup, audit log
- Weekly digest delivered via launchd cron — no Claude session needed

Demo (no install): https://googlarz.github.io/finance-assistant/
Repo: https://github.com/googlarz/finance-assistant

**To use the full thing you need [Claude Code](https://claude.com/product/claude-code) installed** — file system access is required for CSV import, local SQLite, and scheduled digests. There's a claude.ai Projects template if you only want conversational use, but it can't read your statements.

For privacy maximalists: you can route Claude Code through [claude-code-router](https://github.com/musistudio/claude-code-router) + a local [Ollama](https://ollama.com) model so no prompts leave your machine. Answer quality drops though — open local models aren't as sharp on tax brackets and SE calculations.

Not affiliated with Anthropic — just a tool I built for myself. Happy to answer questions about the FIRE math, the tax engines, or the architecture.

---

## /r/ClaudeAI

Title: `Finance Assistant v3.7.1 — a Claude Code skill for personal finance (local, encrypted, multi-locale)`

Body:

Released v3.7.1 of Finance Assistant, a Claude Code skill (not web claude.ai — needs the CLI for filesystem access) that turns your `~/.finance/` directory into a personal finance copilot. New in this release:

- YNAB CSV import (now have 14 bank formats)
- Recurring subscription detection with double-billing alerts
- Crypto holdings via CoinGecko
- Debt avalanche/snowball comparison
- Encrypted backup with PBKDF2
- Audit log of every mutation
- Configurable weekly digest time
- Sample-data toggle in onboarding

Plus a stack of security/integrity fixes from a Codex adversarial review (path traversal, UUID collision, dedup year-boundary, dual-write divergence).

Demo: https://googlarz.github.io/finance-assistant/
Repo: https://github.com/googlarz/finance-assistant

Feedback welcome, especially on the locale system if you're in a country we don't cover yet (AT, CH, ES, IT, …) and want to scaffold it — the generator + source-URL-annotated TODOs make it a ~1-evening contribution.
