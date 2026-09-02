# Changelog

## v4.0.1 — 2026-08-21

### Fixed — 13 bugs found in a targeted audit (money-correctness, crashes, silent data loss)

**Tax correctness (locales submodule):**
- DE: Günstigerprüfung (§ 31 EStG) dropped the Kindergeld clawback when the Kinderfreibetrag was more favorable — overstated refunds by exactly the annual Kindergeld amount (€3,060 in the verified case, married filer, 1 child, €600k income).
- DE: 2024's non-advised filing deadline was hardcoded to 2026-04-30, contradicting its own inline comment and the documented § 149 Abs. 2 AO rule; 2025's advised deadline had the same one-year-late defect. Both now computed from the standard rule.
- FR: the plafonnement du quotient familial compared against a flat 1-part reference regardless of marital status, wrongly capping the uncapped base marital-splitting benefit — ~€19,339 overtaxed for a childless married couple at €400k.
- UK: 2026's tax-year rules had no `scottish_bands` key — Scottish taxpayers silently fell back to rUK bands/rates, mislabeled `tax_system="UK (rUK)"`.
- NL: the 30%-regeling was detected (`expat_30_ruling_detected` surfaced in the breakdown) but never applied — ruling expats were taxed on 100% of gross.

**Logic and crashes:**
- `scenario_engine.compare_debt_payoff_vs_invest`: double-counted the cost of debt (subtracted both remaining principal and cumulative interest), biasing the comparison toward "pay debt first".
- `scenario_engine.compare_rent_vs_buy`: dropped `maintenance_rate` from the renter's investable-savings calculation, biasing toward "buy".
- `monte_carlo._simulate_net_worth`: property appreciation and debt paydown were computed but never credited to the running net-worth total — verified a mortgaged homeowner could simulate to a *lower* net worth than an identical debt-free household.
- `investment_returns.xirr_value()`: crashed with `TypeError` on `approximate_xirr()`'s documented "insufficient data" result; now returns `None`.
- `household.log_shared_expense`: an all-zero expense split raised an uncaught `ZeroDivisionError` instead of a clean `ValueError`.
- `mt940_importer`: field 61's reversal marks (RC/RD) were silently dropped — the regex only matched plain C/D.
- `ofx_importer`: comma-decimal amounts from non-compliant European OFX exports were inflated 100x by the thousands-separator stripping logic.
- `receipt_scanner._preprocess_image`: image file handles were never deterministically closed, risking fd exhaustion on a batch of receipts.

Every fix is revert-verified (a regression test that genuinely fails without it). Full suite: 1,534 passed (was 1,519).

## v4.0.0 — 2026-08-21

### Breaking — Python 3.10+ required

Project minimum bumped from 3.9 to 3.10 — Python 3.9 reached end-of-life
October 2025, and the new MCP server (below) needs 3.10+. The base
skill/CLI install is otherwise unaffected.

### Fixed — SQLite/JSON split-brain (the DB-present code path was never tested)

`tests/conftest.py`'s isolated_finance_dir fixture never called `init_db()`,
so every dual-write bug below shipped invisibly behind 1,434 green tests
that only ever exercised the JSON branch. Added an opt-in
`isolated_finance_dir_db` fixture and DB-present regression tests
throughout.

- `accounts.balance` never matched the JSON schema's `current_balance`
  field, and `is_asset`/`as_of`/`include_in_net_worth`/`include_in_budget`/
  `notes` didn't exist as SQLite columns at all — every SQLite-backed
  account read defaulted `is_asset` to `True`, silently misclassifying
  every liability as an asset. Migrated (schema v3→v4), backfills
  `is_asset` for existing rows.
- 6 `TRANSACTION_SCHEMA` fields (`is_recurring`, `tags`, `tax_relevant`,
  `tax_category`, `business_use_pct`, `import_ref`) were dropped on the
  SQLite `INSERT` despite the normalizer/recurring engine/receipt scanner
  populating them on write.
- `net_worth_engine._to_primary()` did `cash_assets += convert(...)`
  directly — `convert()` returns `(amount, confidence)`, so any second
  currency crashed `calculate_net_worth()` with a `TypeError`. Reproduced,
  fixed; debt balances and the display label are now currency-aware too.
- `budget_engine.update_actual()` had zero callers, so `actual_amount`
  stayed 0 forever once SQLite was active — wired into
  `update_budget_actuals()`, now upserts unbudgeted categories too. Also
  found `budget_engine._db_available()` caching its result in a module
  global forever, unlike every other dual-path module — removed the cache.
- Goals, recurring items, and net-worth snapshots were written to SQLite
  only once, by the first-boot migration, then silently frozen —
  invisible to `accountability_engine.check_goal_drift`,
  `overdraft_detector`'s inflow/outflow projections, and
  `timeline_engine`. Now dual-write on every mutation.
- `account_manager.delete_account()`/`update_account()` were JSON-only —
  `list_accounts()`/`get_account()` prefer SQLite, so deletes and renames
  were silent no-ops once the DB was active. Now dual-store correct, and
  every account mutation is audit-logged (previously zero, despite
  `audit_log.py`'s own docstring claiming coverage).
- `demo_data.py`'s `--wipe-demo` relied on the broken `delete_account()` —
  demo accounts, transactions, goals, debts, the holding, and the "Alex"
  profile all survived a wipe that printed success. Now genuinely wipes
  everything it seeded; SKILL.md now instructs Claude to call it before
  real onboarding, making the "wiped when you start real setup" promise
  true.

### Fixed — Multi-currency correctness

- `account_manager.get_total_balance()` and `transaction_logger.get_totals()`
  summed raw amounts across currencies with no conversion — a USD
  account's balance, or a USD transaction in a EUR account, was counted
  as if it were EUR. Both now convert.
- `currency.sync_exchange_rates()` (new): the claimed 24h-TTL rate cache
  was dead code — nothing ever fetched live rates, so every conversion
  silently used a hardcoded ~2024 fallback table. Explicit/opt-in,
  mirrors `price_sync.sync_prices()`'s pattern. New `--sync-rates` CLI
  flag (`--sync-prices` too — `price_sync.py` had no CLI entry point at
  all before this).

### Fixed — Import correctness

- `transaction_normalizer` discarded the bank's own Category column for
  every non-transfer row in favor of keyword-guess `auto_categorize()`,
  which per issue #6 left "well over half" of a real US export in
  `other_expense`/`other_income`. Added `csv_importer.SOURCE_CATEGORY_MAP`
  (Monarch/Mint default categories → internal taxonomy, best-effort from
  public docs — no real export sample was available).
- Malformed rows were silently dropped via bare `continue` with no
  counter. `import_router.import_file()` now surfaces `rows_skipped`.
- The SQLite dedup path's fallback-key query had no `account_id`
  clause — it deduped **globally** across every account, so an identical
  amount+description in a genuinely different account (a rent split,
  matching card charges) was wrongly dropped. Now scoped per-account,
  matching the JSON path.
- `transfer_matcher.py`'s same-currency-only rule (v3.16.0's documented
  v1 punt, issue #8 Q6) is replaced with rate-window matching:
  cross-currency pairs now match within a 2% tolerance of the current
  exchange rate.
- Per-import transfer residual counters (`transfer_residual` in the
  import result): if a file's own transfer rows don't net close to zero,
  one side of a transfer is likely missing from it. Mechanical half of
  issue #8's balance-assertion-reconciliation roadmap sketch; the
  delta-surfacing half needs a product decision not made here.

### Fixed — US tax law

- `get_estimated_tax_deadlines()` hardcoded Q2/Q3 to 2024's (already
  weekend-shifted) dates for every `tax_year` — 2025's real IRS dates
  were a day off from what was returned. Computed per-year now.
- `calculate_qbi_deduction()` implements the W-2 wages/UBIA limitation
  for high-income non-SSTBs (issue #5's second gap, previously only
  annotated as unimplemented) — defaults to $0 wage limit when not
  provided, the common no-employee sole-proprietor case.

### Added — Transaction correction tools

`transaction_logger.delete_transaction()`, `unlink_transfer_pair()`, and
`delete_import()` — no `delete_transaction` existed anywhere; the
documented workaround ("delete the account and re-import") relied on a
function that was itself broken until this release. Imports now stamp a
shared `import_ref` (never actually generated before), so
`delete_import(import_ref)` can undo an entire bad import in one call.

### Added — Net-worth history backfill

`net_worth_engine.backfill_net_worth_history(months=N)` derives monthly
snapshots by walking cash-account balances backward through dated
transaction history — a user importing years of data got a blank net
worth chart until months of forward snapshots accumulated.

### Added — MCP server (read-only)

`scripts/mcp_server.py` — `import_preview` (always dry-run), `get_totals`,
`get_budget_variance`, `get_net_worth`, `get_tax_summary` as MCP tools.
Closes the structural dead end where claude.ai/Cowork users had no route
to any local data at all (no CSV import, no local database, no bank
sync). Optional dependency (`pip install finance-assistant[mcp]`). See
`docs/MCP.md`.

### Also

- SKILL.md/skill.py wiring for previously-implemented-but-unreachable
  features: live prices, subscriptions, backup/restore, audit log,
  weekly digest, inbox watcher. Fixed a wrong section cross-reference and
  a duplicate heading.
- `doctor.py` gained a tesseract binary check (receipt OCR silently
  failed without one; `--doctor` previously reported all-clear).
- Found and fixed a real test-hygiene bug along the way: `audit_log.py`
  is deliberately HOME-anchored (`~/.finance/audit.log`, by design), but
  4 test files shadowed the shared test fixture without redirecting it —
  every test run in this repo had been writing real entries into the
  developer's actual home directory (7,249 lines accumulated before this
  was caught). Production behavior is unchanged; only test isolation.

### Tests (+54 in this repo, of which 4 are MCP-only)

Every fix in this release was revert-verified (stashed, confirmed the
new test fails, restored) before merging. Full suite (`tests/` +
`locales/tests/`): 1,519 passed under Python <3.10 (was 1,434 combined
at the start of this work — the locales submodule also picked up 38
tests from an unrelated upstream Irish-locale merge along the way);
1,523 passed with Python 3.10+ and the `mcp` extra installed
(`tests/test_mcp_server.py`'s 4 tests otherwise skip via
`pytest.importorskip`).

## v3.16.0 — 2026-08-11

### Added — First-class transfer support ([#8](https://github.com/googlarz/finance-assistant/issues/8))

- **Per-row account routing**: `import_file(..., route_by_account=True)` resolves each CSV row's own account (from the bank's Account column, on Mint/Monarch/YNAB) instead of stamping the whole file into one `account_id`. Rows that don't match an existing account are reported in `unmapped_accounts` and hard-stop the import, mirroring the existing multi-account warning behavior.
- **Tier 1 — transfer detection at import time**: rows carrying the bank's own "Transfer"/"Credit Card Payment"/"Balance Adjustments" category (Monarch/Mint) or a YNAB `Transfer : <Account>` payee are typed `transfer` automatically, before any amount-sign heuristic runs. The source category is preserved into a new `subcategory` field for Tier 2's credit-card settlement window.
- **Tier 2 — `transfer_matcher.link_tier2_transfers(year)`**: among rows already typed `transfer`, finds each row's matching leg in a different account (opposite sign, equal amount, same currency, within a ±3 day settlement window — ±5 days for credit-card payments) and links them via a new `transfer_peer_id` field. Requires mutual uniqueness — a pair only links if each side is the other's *only* qualifying candidate — so ambiguous clusters are skipped rather than force-matched. Safe to auto-apply: every row in the pool was already excluded from income/spending by Tier 1.
- **Tier 3 — `transfer_matcher.suggest_transfer_pairs(year)`**: the same matching rule applied to ordinary (non-transfer) rows, for imports with no category signal (legacy formats, hand-entered data). Read-only — returns candidates, never mutates. A naive version of this heuristic false-matched ~19 legitimate pairs (refunds, recurring identical charges) on a real Monarch export during validation — the mutual-uniqueness + same-account-exclusion rules exist specifically to reject those.
- **`transfer_matcher.retro_type_transfers(year, dry_run=True)`**: maintenance command applying the Tier 3 heuristic to already-imported data. Previews by default; `dry_run=False` applies and audit-logs each linked pair.
- New `transactions.transfer_peer_id` and `transactions.subcategory` SQLite columns (schema v2 → v3, idempotent migration for existing installs).
- Known limitation, by design: cross-currency transfers are not matched (same-currency only, v1).
- Reported and scoped by [@felciano](https://github.com/felciano) in [#8](https://github.com/googlarz/finance-assistant/issues/8) with real-data validation of the false-match rate; PR1 of the same report (honoring `type` in analytics) shipped separately in [v3.15.0](#v3150--2026-07-27).

### Fixed
- `transaction_logger.add_transaction()`'s SQLite insert silently dropped `subcategory`/`transfer_peer_id` even when present in the transaction dict (same split-brain risk class as the v3.15.0 fix) — both are now written on every insert.
- `import_router.py` resolved Tier 1's category signal against the generic container format (`"csv"`) instead of the specific bank format (`"monarch"`/`"mint"`/`"ynab"`) — Tier 1 detection silently never fired through the real import pipeline despite passing in isolation. Caught by an end-to-end pipeline test, not unit tests alone.
- Transfer-pair candidate pools now span year boundaries (a settlement window can straddle Dec 31/Jan 1); previously a transfer posted at year-end and settling in January would never link.

### Tests (+34)
- Schema migration (v2 DB gains `transfer_peer_id`/`subcategory`, idempotent). `update_transaction_fields()` unit tests. Tier 1 detection at the normalizer level and through the full `import_file()` pipeline (the integration bug above). 17 tests for `transfer_matcher.py`: mutual-uniqueness, same-account exclusion, ambiguous-cluster skipping, CC-payment window, cross-currency rejection, year-boundary pairing, dry-run/apply/idempotency for `retro_type_transfers`.

## v3.15.0 — 2026-07-27

### Fixed — Analytics classified flows by amount sign, not transaction type

- **`transfer`/`investment`/`debt_payment` transactions were counted as income or spending**: the transaction schema has supported these types since v2, but every analytics engine that aggregated income/expenses classified purely by amount sign — so a correctly-typed transfer between the user's own accounts, an investment purchase, or a debt principal payment still landed in spending/income totals. On a real multi-account export this meant ~$60k of phantom income/expense reaching budgets, forecasts, and tax projections unfiltered ([#6](https://github.com/googlarz/finance-assistant/issues/6)).
- Fixed across every engine that aggregates transaction flows: `accountability_engine` (savings-rate trend, category creep), `annual_summary` (donation total), `budget_engine` (history-based limit suggestions), `cashflow_forecast` (average daily spend), `tax_optimizer` (YTD income/expenses), `timeline_engine` (monthly summary) — plus the shared `transaction_logger.get_totals()` that `annual_summary`'s income summary depends on.
- Added `transaction_logger.is_income_flow()` / `is_expense_flow()`: type-first classification, falling back to amount sign only when type is genuinely unset. All Python-side engines now share this instead of hand-rolling sign checks; SQL-side engines (`accountability_engine`, `tax_optimizer`, `timeline_engine`) gained an explicit `type NOT IN ('transfer', 'investment', 'debt_payment')` filter.
- Reported by [@felciano](https://github.com/felciano) in [#7](https://github.com/googlarz/finance-assistant/issues/7), who also flagged the risk in 5 more engines beyond the 2 in the original repro — confirmed by audit and fixed in all of them.
- Also: promoted the no-terminal (Cowork/claude.ai) install path out of a collapsed section so non-technical readers don't skip past it, and added a one-line disclaimer that applied tax statute isn't licensed advice.

### Tests (+12)
- Regression tests per engine confirming a mis-typed transfer/investment/debt_payment doesn't inflate income, spending, category totals, or (for `accountability_engine`) doesn't mask a genuine 3-month savings-rate decline. Direct unit tests for `is_income_flow()`/`is_expense_flow()`.

## v3.14.0 — 2026-07-06

### Import safety — multi-account files no longer corrupt silently

- **Multi-account export detection**: new `csv_importer.detect_source_accounts()` reads the Account column of Mint/Monarch/YNAB exports (the three bundled formats whose files can span several of the user's accounts). When a file covers more than one account, `import_file()` now attaches a `multi_account_warning` to the preview naming every source account and the single `account_id` all rows would land in.
- **SKILL.md hard-stops on the warning**: Claude must show the account list and ask — import anyway, filter to one account, or split the file — instead of committing a multi-account file silently. Previously the failure mode was invisible: all rows stamped into one account, transfers between the user's own accounts booked as unrelated income/expense (~$60k phantom income on a real-world 2,700-row Monarch export, [#6](https://github.com/googlarz/finance-assistant/issues/6)), discovered only weeks later in the analytics.
- This is the containment half of [#6](https://github.com/googlarz/finance-assistant/issues/6); per-row account routing + transfer typing remains open there.

### Tests (+5)
- Multi-account Monarch file → warning with sorted account list; single-account file → no warning; non-multi-account formats (e.g. DKB) → no false positives; end-to-end `import_file()` dry-run carries the warning.

## v3.13.1 — 2026-07-06

### Fixed — Tax correctness (critical)

- **QBI SSTB phase-out was never wired up**: `calculate_qbi_deduction()` implements the §199A SSTB phase-out correctly, but `calculate_liability()` never passed `is_sstb` to it — so every self-employed filer got the full 20% QBI deduction regardless of income or trade type. For a consultant/lawyer/advisor (an SSTB) above the phase-out threshold, the real deduction is $0. On $400k self-employed net profit (2025, single), this understated federal tax by **$25,810.78** and flipped the headline "1099 nets +$15,951" comparison to 1099 netting *less* — the exact decision this feature exists to inform.
- Added `tax_profile.extra.is_sstb` (bool). When it's not set and taxable income is above the phase-out threshold, the engine no longer silently assumes non-SSTB — it says so in the new `qbi_note` field, which SKILL.md now instructs Claude to check and to ask the user about before running a W-2-vs-1099 comparison above ~$182k/$364k (single/MFJ).
- Reported by [@felciano](https://github.com/felciano) in [#5](https://github.com/googlarz/finance-assistant/issues/5), with a self-contained repro. Thanks for catching this one.

### Merged
- [#3](https://github.com/googlarz/finance-assistant/pull/3) — `--doctor`'s locale check imported a function that doesn't exist (`locale_registry.list_locales`), so it always reported degraded. Fixed to use `tax_engine.get_available_locales()`. (@felciano)
- [#4](https://github.com/googlarz/finance-assistant/pull/4) — bulk file imports (CSV/MT940/OFX) dropped `payee`/`tags`, silently breaking subscription detection and merchant analysis for every non-receipt import. (@felciano)
- [#2](https://github.com/googlarz/finance-assistant/pull/2) — `.claude/settings.json`'s `UserPromptSubmit` hook hardcoded an absolute path, silently no-op-ing the auto-ingest hook on any machine but the original author's. Now uses `$CLAUDE_PROJECT_DIR`. (@astout)

### Tests (+5)
- `locales/tests/test_locale_us.py`: SSTB above threshold → $0 QBI; non-SSTB above threshold keeps the deduction; unset `is_sstb` above threshold warns in `qbi_note`; below threshold, SSTB status doesn't matter.

## v3.13.0 — 2026-07-02

### Conversation
- **SKILL.md now tells Claude to quote `total_burden`**: for "how much do I really pay?" questions, the answer uses `total_burden` (income tax + all employee social contributions) with its `components` note — not `total_tax`, which for a German user hides ~half the real deduction. Burden-based rates are labelled "total burden rate".

### Importers
- **Direct end-to-end importer tests** (`tests/test_importers.py`, 20 tests): whole-file parses for MT940 (debit/credit signs, ISO dates, currency), SGML-style OFX (amounts, timestamps, FITID refs), generic CSV, and PDF helpers. Includes malformed-input robustness — garbage/empty/binary files return empty lists instead of crashing — and a CSV formula-injection regression guard.

### Locale scaffold
- **`scaffold_locale.py` now emits contract-conforming stubs**: generated locales include `CURRENCY` plus working `get_filing_deadlines`, `get_social_contributions`, and `generate_tax_claims` stubs, so a fresh scaffold passes `locales/tests/test_cross_locale_contract.py` out of the box. Contributed locales can no longer silently miss interface functions.

### Error visibility (money paths)
- **`finance_storage.load_from_db` / `save_to_db`**: real DB errors now print a stderr warning instead of silently returning `[]`/`False` (previously a DB failure was indistinguishable from "no data"). Missing-DB-layer `ImportError` stays silent — that's the supported JSON fallback.
- **`budget_engine`**: all four silent `except Exception: pass` blocks (dual-write, read, actual-update, variance) now warn on stderr before falling back.
- **`net_worth_engine`**: failed currency conversions no longer silently sum raw amounts — a stderr warning (once per currency pair) states that net worth mixes currencies. Conversion fallback logic consolidated into one `_to_primary()` helper.

## v3.12.0 — 2026-06-10

### Fixed — Tax correctness

- **FR `income_tax` was silently None**: `get_tax_summary()` looked for `tax`/`federal_income_tax`/`breakdown.income_tax` but FR returns `income_tax` at the top level. The key was never picked up, leaving `income_tax: None` and `total_tax: 0` for all French users. Fixed by including `est.get("income_tax")` in the normaliser chain.
- **FR/UK/PL `total_tax` understated burden**: When a locale's `calculate_tax()` returns `net` but no `total_tax` key, `get_tax_summary()` now falls back to `gross − net` before assembling from components. This captures UK NI (£2,994 for £50k), FR prélèvements sociaux (€4,288 for €45k), and PL ZUS + health (PLN 17,180 for PLN 80k) that were previously missing from `total_tax`.
- **DE social contributions hidden from total burden**: `get_tax_summary()` now adds `social_tax` (employee pension/health/care/unemployment contributions from `get_social_contributions()`) and `total_burden` (= `total_tax + social_tax`) to every response. For €60k German gross, `total_burden` is ~€26,478 vs the previously reported `total_tax` of ~€14,148 — the full 44% real burden vs a misleading 24%.
- **`effective_rate` reflected income-tax-only**: Rate is now always `total_tax / gross`, consistent with what `total_tax` now captures. Previously it used the locale's own rate, which for FR/PL was just income tax over gross (FR: 12% vs actual 22%; PL: 5% vs actual 27%).
- **`get_available_locales()` crashed on `tests/` directory**: The function scanned `locales/` and tried to load every subdirectory with an `__init__.py` as a locale, including the `tests/` package, raising `ValueError: Unknown locale 'tests'`. Now skips entries not in `ALLOWED_LOCALES`.
- **Unknown locale raised `ValueError` instead of returning error dict**: `_load_locale()` raised `ValueError` for unrecognised codes but the caller only caught `ImportError`/`AttributeError`. Added `ValueError` to the catch so all unknown-locale paths return a structured error dict.
- **PL missing `CURRENCY` constant**: `locales/pl/__init__.py` was the only locale without `CURRENCY`. Added `CURRENCY = "PLN"`.
- **`LocaleContext` build failures swallowed silently**: The `except (ImportError, Exception)` that falls back to a raw dict now logs a `Warning:` line to stderr before falling back. This surfaces unexpected crashes during context construction instead of silently producing wrong answers.

### Tests (+107)

- `tests/test_tax_engine.py` (new, 35 tests): direct tests for `get_tax_summary()` parametrised across all 6 locales — required keys, numeric sanity, `net == gross − total_tax`, `effective_rate ∈ (0, 1)`, locale-specific correctness (FR income_tax not None, DE social_tax present, UK/PL/FR total_tax includes contributions), error path.
- `locales/tests/test_cross_locale_contract.py` (new, 72 tests): cross-locale interface contract — every locale must expose `calculate_tax`, `get_tax_rules`, `get_filing_deadlines`, `generate_tax_claims`, `get_social_contributions`, and the four metadata constants.

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
