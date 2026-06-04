# Changelog

## v3.11.1 — 2026-06-04

### Conversation experience
- **Session-open overwhelm fixed**: immediate alerts were looped uncapped — a busy user could open to a wall of lines before saying a word. Now capped at 3, critical-first, with `…and N more — say 'show all alerts'` for the rest. Matches §2's own "pick the 2-3 things that matter."
- **On-voice guard**: voice-lint test scans all user-facing formatters' string literals (AST — comments/docstrings never trip it) for SKILL.md §2's banned robotic phrases ("Analysis complete", "Confidence: medium", etc.). The code surface where robotic strings can drift in is now locked.
- **Session-start block marked speak-from, not paste**: SKILL.md §4 now explicitly tells Claude the monitor output is structured input to speak from — never to relay verbatim.
- **Multi-turn conversation example**: §2 now has a worked 3-turn exchange showing correction and follow-up handled in-voice.
- **Local-model voice tradeoff**: SKILL.md and `docs/sovereignty.md` now state the two-layer hit — reasoning and voice degrade, numbers don't — with guidance for the local-model path.

## v3.11.0 — 2026-06-04

### Onboarding — guiding the user
- **Load-time health nudge**: if the install is degraded (missing dependencies or an uninitialised `locales/` submodule — the #1 "it doesn't work" cause), every session now opens with a one-line, friendly pointer to `python3 skill.py --doctor` instead of leaving the user stranded. Healthy installs see nothing. New `_health_nudge()` is cheap and never raises (covered by tests).
- **Demo offered before any real numbers**: the conversational onboarding (SKILL.md) now explicitly offers `--demo` as a no-commitment first step, matching what the programmatic greeting already did — so a user who just talks to Claude gets the try-first path, not only README readers.
- **Privacy nuance surfaced at onboarding**: privacy-motivated users are now told the two-layer truth up front — data stays on disk, but the *conversation* goes to Anthropic by default unless they run a local model (Sovereignty mode).
- **claude.ai surface expectations set up front**: the Projects template (`PROJECT_INSTRUCTIONS.md`) now states what works in the browser (conversational math) vs what needs the Claude Code install (file import, SQLite, live prices, Monte Carlo), so users don't hit silent walls.

## v3.10.1 — 2026-06-04

### Fixed — Database
- **Migration ordering bricked DB startup on upgrade**: `init_db()` ran `CREATE INDEX ... ON transactions(type)` (part of the schema script) *before* the column migration that adds `transactions.type`. On any DB created before the `type` column shipped, the index creation threw `no such column: type`, aborting the whole script before the migration could run — so the column was never added, `schema_version` was never stamped, and `Warning: DB bootstrap failed: no such column: type` printed on every command, permanently. Indexes are now applied *after* column migrations, and the version is stamped only after both succeed (self-healing on the next run if anything fails).

### Fixed — Usability
- **`--help` did nothing**: the hand-rolled CLI had no `--help`/`-h` handler, so it fell through to a default session. Added a grouped usage listing for all commands.
- **Warnings leaked into normal output**: the bootstrap and permissions warnings printed to the session log on every run. The DB warning is gone (see above); the permissions check now auto-hardens instead of nagging.
- **Permissions hint referenced an internal function**: the message told users to "Run `harden_permissions()`" (a Python function name). `.finance/` is now auto-hardened on session start; if that fails, the message points to `python3 skill.py --doctor`.

## v3.2.0 — 2026-04-29

### Fixed — Financial Correctness
- **Monte Carlo log-normal returns**: Was sampling arithmetic normal (could produce returns < -100%; geometric mean systematically ~0.72%/yr too optimistic). Now uses log-normal: `μ = log(1+r) - 0.5σ²`. FIRE projections are now mathematically correct.
- **Monthly compounding**: Was applying `real_return / 12` (linear). Now uses `(1 + real_return)^(1/12) - 1` (geometric). Affects all Monte Carlo simulators.
- **Net worth multi-currency**: Account and holding balances are now converted to `primary_currency` before summing. Previously a USD brokerage + EUR account were added as raw numbers.
- **DE Kirchensteuer missing from output**: `total_tax_due` excluded Kirchensteuer, understating liability for ~30% of German taxpayers. Now included. `breakdown` exposes `kirchensteuer` and `kirchensteuer_rate`.
- **UK Scottish income tax**: Scottish taxpayers got rUK rates (20%/40%/45%). Scottish Parliament rates now applied when `region=Scotland` (starter 19%, basic 20%, intermediate 21%, higher 42%, advanced 45%, top 48%). Difference: ~£1,500/yr at £50k income.
- **Goal completion date truncated fractional months**: `int(months_to_go)` dropped fractional months. Now uses `timedelta(days=int(months_to_go * 30.44))`.
- **Budget "unbudgeted" category**: Spending in a category with no budget limit showed `status="on_budget"`. Now correctly `status="unbudgeted"`. Added `"warn"` tier at 85% of limit.
- **XIRR single-cashflow returned initial guess**: With 1 cashflow, Newton's method returned `xirr_pct=10.0` (the seed). Now returns `{xirr_pct: None, error: "insufficient data"}`.
- **Past-deadline goals silently dropped**: Goals past their target date generated no alert. Now emit a `"missed_deadline"` high-priority alert.

### Fixed — Security
- **SQL injection surface**: `finance_storage.load_from_db` and `save_to_db` f-stringed table and column names into SQL with no validation. Added `_ALLOWED_TABLES` whitelist and `_validate_column()` regex guard.
- **CSV formula injection**: Merchant/description fields starting with `=`, `+`, `-`, `@` are now prefixed with `'` to neutralize spreadsheet formula execution.
- **No file size limit on import**: A 500 MB CSV could OOM the process. Now enforces 50 MB limit in both `import_router` and `csv_importer`.
- **`SECURITY.md`**: Added responsible disclosure process and security model documentation.

### Infra / Docs
- **`requirements.txt`**: All dependencies now pinned with compatible upper bounds (`cryptography>=42,<45`, etc.). Numpy added as commented optional.
- **`pyproject.toml`**: Added — project is now `pip install -e .` installable with `full` and `dev` extras.
- **Past-deadline goal alerts**: `session_alerts` now surfaces ⏰ missed-deadline alerts.
- **Currency cache staleness**: Corrupt `cached_at` timestamp now logs a warning instead of silently falling back.
- **SKILL.md**: Added CLI Usage table (`--version`, `--doctor`, `--demo`, `--dashboard`). Added `delete_transaction` availability note.

### Tests (+7)
- Updated 2 stale test assertions (budget warn tier, XIRR single-cashflow)
- Added `test_xirr_single_cashflow_returns_error`, `test_xirr_same_date_cashflows_returns_error`

---

## v3.1.2 — 2026-04-29

### Fixed
- **`data_coach` — 5 permanently-locked insights**: `fire_timeline` required `preferences.fire_target_age` (non-existent key, now `fire_target`); `emergency_fund_adequacy` required phantom profile keys `savings_balance`/`monthly_expenses` (now `transactions:1mo`); `tax_optimization` and `tax_refund_estimate` required `tax_profile.tax_class` (German-only, locked for all US/UK/FR/NL/PL users, now `meta.locale`); `insurance_gap` required always-truthy `"employment"` dict (now `employment.annual_gross`).
- **US Additional Medicare Tax ignored filing status**: `estimate_fica()` always applied the single-filer $200k threshold regardless of filing status. MFJ filers at $240k were incorrectly told they owed Additional Medicare Tax ($250k threshold applies). MFS filers at $130k were incorrectly exempt ($125k threshold applies).
- **SE tax missing Additional Medicare**: `estimate_self_employment_tax()` did not apply the 0.9% Additional Medicare surtax on high-income self-employed filers — silently understating SE tax for earners above the threshold.
- **`tax_engine` missing `get_social_contributions()`**: The gateway layer had no proxy for FICA/social contribution queries, leaving SKILL.md's tool contract with a dead end.
- **Profile locale defaulted to `"de"`**: New users who skipped onboarding got German tax routing silently. Now defaults to `None` (no locale until explicitly set).
- **`--version` hardcoded `3.1.0`**: Version string now reads `3.1.2`.
- **`_setup_db()` swallowed all errors silently**: DB bootstrap failures now print to stderr.

### Security / Ops
- **`--doctor` now checks for `cryptography` package**: Missing package caused an obscure `ImportError` on first encrypt/decrypt; now a clear `fail` with the install command.
- **CI adds `ruff` lint step**: Catches type and style regressions that were invisible before.

### Tests
- **14 new tests**: 6 US bank CSV format detection/parsing tests (Chase, BofA, Wells Fargo, Mint, Monarch, Capital One); 3 Additional Medicare edge case tests; 5 `data_coach` insight catalog correctness tests.

### Docs
- **SKILL.md**: Mode count corrected (18, not 11); onboarding wizard corrected (9 steps, not 7); US state tax out-of-scope note added; `data_coach` and `session_alerts` added to Tool Contract.

---

## v3.1.1 — 2026-04-29

### New
- **US bank import** — Chase, Bank of America, Wells Fargo, Mint, Monarch Money, and Capital One CSV formats now auto-detected and parsed. Handles split Debit/Credit columns (Capital One), positional no-header format (Wells Fargo), and Mint's `Transaction Type` debit/credit convention.
- **Submodule doctor check** — `--doctor` now detects an uninitialised `locales/` submodule and prints the exact fix command.
- **Troubleshooting docs** — README and CONTRIBUTING.md both document the submodule init step and locale contribution workflow.

---

## v3.1.0 — 2026-04-29

### New
- **US locale** — federal income tax calculator for 2024/2025: brackets, standard deductions, FICA/Medicare, SE tax, 401(k)/HSA/IRA contribution limits, filing deadlines (including quarterly estimated payments for self-employed filers). All rules sourced from IRS Rev. Procs with provenance tracking.
- **Data coach** — progressive insight unlocking: after each data addition, the skill now surfaces what's available now and leads the conversation toward the next most valuable thing to add.
- **Conversational onboarding** — 9-step guided setup with warm value previews at each step, resumable mid-wizard, locale-aware tax prompts (DE/UK/FR/NL/PL/US).
- **SKILL.md triggers** — skill now auto-loads on natural finance keywords (budget, tax, savings, debt, FIRE, net worth, investments, etc.) without requiring explicit invocation.
- **CONTRIBUTING.md** — full guide for adding new locales and CSV importers.
- **Interactive HTML dashboard** — `python3 skill.py --dashboard` generates a fully-populated `~/.finance/dashboard.html` from real data with Chart.js visualizations, spending heatmap, scenario comparison, and cashflow forecast.

### Fixed
- US locale not in `ALLOWED_LOCALES` in `tax_engine.py` — US users crashed on any tax question.
- Additional Medicare Tax threshold was always $200k regardless of filing status (correct: $250k for MFJ, $125k for MFS).
- `withheld` field in US tax calculator now documented as federal income tax only (W-2 Box 2), with backward-compatible key `withheld_federal`.
- `decrypt_file()` now uses atomic write (tmp → rename), matching `encrypt_file()`. Previously could corrupt data on interrupted write.
- `ensure_gitignore_protection()` now walks up to find the actual git repo root instead of always using the immediate parent directory.
- `get_step_prompt()` locale defaulted to `"de"` — non-German users got German tax questions. Now defaults to generic fallback.
- Benchmark messages now include source year ("based on ECB HFCS 2021 data") so users understand the reference point.
- Investment onboarding prompt now uses the user's actual currency instead of hardcoded `€`, and removes German-specific broker example.

### Security
- `decrypt_sensitive_files()` now returns a `reminder` field; SKILL.md instructs Claude to surface it after every decryption.
- SKILL.md passphrase handling guidance added: Claude will never echo a passphrase, and recommends the `FINANCE_CRED_PASSPHRASE` env var.

---

## v3.0.0 — 2026-04-20

- SQLite as primary store (WAL mode), JSON kept as human-readable backup
- Monte Carlo projections (1,000-run simulation, p10/p50/p90 outcomes)
- Timeline engine: trend, seasonality, correlation, anomaly detection
- Financial journal, accountability engine, life events tracker
- 5 locales: DE, UK, FR, NL, PL
- 861 tests
