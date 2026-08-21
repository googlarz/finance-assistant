# Architecture

How Finance Assistant is put together — for contributors and the curious. For
what it does and how to install, see the [README](../README.md).

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                    Claude Code / Cowork                         │
│                                                                 │
│   You ──► skill.py ──► profile_manager ──► session_alerts      │
│                │                                                │
│                ▼                                                │
│         ┌──────────────────────────────────────────┐           │
│         │              20+ Modes                   │           │
│         │  Budget · Transactions · Goals           │           │
│         │  Investments · Debt · Tax · Insurance    │           │
│         │  Net Worth · Import · Monte Carlo        │           │
│         │  Scenarios · Tax What-Ifs · Handoff      │           │
│         └──────────────┬───────────────────────────┘           │
│                        │                                        │
│              ┌─────────▼──────────┐                            │
│              │   scripts/*.py     │  ◄── locale plugins        │
│              │  (real math, not   │    locales/de · uk · us    │
│              │   hallucination)   │    locales/fr · nl · pl    │
│              └─────────┬──────────┘                            │
│                        │                                        │
│              ┌─────────▼──────────┐                            │
│              │  SQLite + .finance/ │  local only, never uploaded│
│              │  profile · budgets  │  optional export encryption│
│              │  investments · tax  │  chmod 600, git-ignored    │
│              │  (WAL-mode DB)      │  auto-migrates from JSON   │
│              └────────────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
```

### Profile-First Architecture

Every session starts by loading your stored profile with `profile_manager.py`. All scripts operate on this profile + the `.finance/` data directory. Nothing is hardcoded; everything adapts to your locale, currency, and situation.

### Insight Pipeline

The insight engine (`insight_engine.py`) runs after every major data update. It dispatches to domain-specific generators:

```
budget_insights → savings_insights → investment_insights
→ debt_insights → insurance_insights → tax_insights → net_worth_insights
```

Each insight carries a 4-level status:
- `ready` — actionable right now
- `needs_input` — needs one more fact from you
- `needs_evidence` — needs a document or statement
- `detected` — background risk found, FYI

And a confidence label: `Definitive` | `Likely` | `Debatable` | `Avoid`

### Locale Plugin System

Tax rules are country-specific plugins in `locales/<country_code>/`. Each locale exports a standard interface:

```python
LOCALE_CODE = "de"
SUPPORTED_YEARS = [2024, 2025, 2026]
def get_tax_rules(year) -> dict
def calculate_tax(profile, year) -> dict
def get_filing_deadlines(year) -> list[dict]
def get_social_contributions(gross, year) -> dict
def generate_tax_claims(profile, year) -> list[dict]
```

The `tax_engine.py` layer is country-agnostic — it loads the active locale via `importlib` and normalizes the (divergent) return shapes through `get_tax_summary()`. All locales are bundled via the `locales/` git submodule; new locales can be scaffolded automatically via `scripts/scaffold_locale.py`.

### Multi-Currency

All amounts use the `Money` class (backed by `Decimal`) to avoid floating-point errors. Exchange rates are cached in `.finance/exchange_rates.json` with a 24-hour TTL; fallback rates are clearly marked as lower confidence.

---

## Data Storage Layout

All data is project-local in `.finance/`. No cloud sync, no external APIs, no telemetry.

As of v3.0, the primary store is **SQLite** (`finance.db`, WAL mode). JSON files are kept as a human-readable backup and for compatibility; new writes go to both.

```
.finance/
├── finance.db                    # SQLite database (WAL mode, FK constraints)
│                                 # tables: profile, accounts, transactions, budget_categories,
│                                 #         goals, holdings, debts, snapshots, recurring_items,
│                                 #         scenarios, thresholds, insurance_policies, schema_version
├── finance_profile.json          # JSON mirror of profile (human-readable backup)
├── accounts/
│   ├── accounts.json             # Account registry mirror
│   └── transactions/
│       └── <account>_<year>.json # Transaction log mirror
├── budgets/
│   ├── 2025.json                 # Annual budget mirror
│   └── 2025-04.json             # Monthly budget mirror
├── goals/
│   └── goals.json               # Savings goals mirror
├── investments/
│   ├── portfolio.json            # Holdings mirror
│   └── snapshots/
│       └── 2025-04-01.json      # Point-in-time portfolio snapshots
├── debt/
│   ├── debts.json               # Debt registry mirror
│   └── payoff_plans/
│       └── <plan_id>.json       # Avalanche/snowball simulation results
├── insurance/
│   └── policies.json            # Insurance policies mirror
├── net_worth/
│   └── snapshots/
│       └── 2025-04-01.json      # Monthly net worth snapshots
├── taxes/
│   └── de/
│       ├── 2024.json            # Tax year data
│       └── 2024-claims.json     # Deduction claims for filing
├── imports/
│   └── import_log.json          # Import history for deduplication
├── workspace/
│   └── 2025.json                # Financial health dashboard
├── subscriptions/
│   └── actions.json             # Subscription cancel/keep tracking
├── household/
│   ├── household.json           # Members + shared config
│   ├── shared_expenses.json     # Split expense ledger
│   └── shared_goals.json        # Household goals with per-member contributions
├── telemetry/
│   └── locale_usage.jsonl       # Which locales get used (no financial data)
├── exchange_rates.json           # Cached FX rates (24h TTL)
├── audit.log                     # Append-only mutation log (every change)
└── audit/
    └── access_log.json           # Audit trail of all data access
```

### Migration

On first boot after upgrading to v3.0, `skill.py` automatically migrates all existing JSON data into SQLite using `db_migrate.py`. The migration is idempotent — safe to re-run.

**What is never stored:**
- Bank login credentials, passwords, PINs, TANs
- Full IBAN or bank account numbers
- Credit card numbers or CVV codes
- Tax IDs, passport numbers, national IDs
- Raw document contents

---

## Bank Statement Import

### Supported Formats

| Format | Banks / Sources |
|--------|----------------|
| CSV (auto-detected by header fingerprint) | **14 formats** — 🇩🇪 DKB, ING, Sparkasse, Commerzbank, N26 · 🇺🇸 Chase, Bank of America, Wells Fargo, Capital One · 🌍 Wise, Revolut · 📊 Mint, Monarch, YNAB · plus a generic fallback |
| MT940 | Any German bank (SWIFT standard) |
| OFX / QFX | Most German brokers, international banks |
| PDF | Statement parsing for supported layouts |
| Image (receipt) | Photo → transaction via receipt scanner |
| **Anything else** | **No parser? Claude reads it.** Unusual bank, foreign layout, copy-pasted table, scanned PDF, screenshot — the LLM extracts the transactions directly, then they run through the *same* sanitize → categorize → dedupe → preview pipeline. |

> **Why "anything else" works:** this is an LLM-native product, not a pile of regex parsers. The 14 bundled formats are a fast path; when none match, Finance Assistant doesn't fail — it hands the raw content to Claude (the session you're already in) to extract. Nothing extra leaves your machine, and LLM-extracted rows get no special trust: same deduplication, same CSV-injection sanitization, same confirm-before-commit flow as a built-in parser.

### Import Flow

1. **Detect format** — header fingerprinting identifies the bank automatically
2. **Preserve original** — source file is copied to `~/.finance/originals/YYYY-MM-DD_HH-MM-SS_<filename>` before any parsing. You always have the raw file, regardless of what happens next. Pass `keep_original=False` to skip.
3. **Parse** — extract date, amount, payee, description
4. **Preview** — show first 10 transactions for review
5. **Confirm** — user approves before any data is written
6. **Auto-categorize** — keyword + payee rules assign categories
7. **Deduplicate** — exact-match deduplication against existing transactions
8. **Update** — account balance and budget actuals refreshed

### Auto-Categorization

`transaction_normalizer.py` maps transactions to 30 categories across 8 domains. `category_learner.py` remembers corrections and applies them to future imports from the same payee — the categorization improves over time.

### Import Assumptions

If you're writing a new format parser or touching multi-account/transfer handling, read this first.

**Default is still one file = one account.** `import_file(file_path, account_id, ...)` stamps every row with the single `account_id` you pass, unless you opt in to per-row routing (below). This applies to the 14 known-format parsers, the generic CSV fallback, and the LLM-extraction path.

**Multi-account exports (`route_by_account=True`)** ([#8](https://github.com/googlarz/finance-assistant/issues/8)). Three of the 14 bundled formats carry a per-row account field — Mint (`Account Name`), Monarch (`Account`), YNAB (`Account`). Pass `route_by_account=True` and `import_file()` resolves each row's account name against existing Finance Assistant accounts (case-insensitive exact match on `name`) and imports it there instead of the single passed-in `account_id`. Names that don't resolve fall back to `account_id` and are listed in `result["unmapped_accounts"]` — SKILL.md hard-stops on that field the same way it does on `multi_account_warning`, so the caller decides (create the account / map it / accept the fallback) instead of it happening silently. Without the flag, behavior is unchanged from before #8.

**Transfer detection is tiered, not a single heuristic** ([#7](https://github.com/googlarz/finance-assistant/issues/7), [#8](https://github.com/googlarz/finance-assistant/issues/8)):
- **Tier 1 — category/structural signal, at import time.** `csv_importer.TRANSFER_CATEGORIES` maps known transfer-ish category strings per source format (Monarch `Transfer`/`Credit Card Payment`/`Balance Adjustments`; Mint `Transfer`/`Credit Card Payment`) and YNAB's `Transfer : <Account>` payee convention. `transaction_normalizer.normalize_transactions()` types a matching row `transfer` directly — this is what makes `type` correct enough for the engines fixed in #7 to actually exclude it from income/spending.
- **Tier 2 — leg linking, `transfer_matcher.link_tier2_transfers()`.** Among rows *already* typed `transfer`, finds each row's matching leg in a different account (opposite sign, equal amount — or, cross-currency, within `FX_MATCH_TOLERANCE` (2%) of the current cached-or-fallback exchange rate — ±3 days / ±5 for anything subcategorized as a credit-card payment) and records it via `transfer_peer_id`. Only touches rows Tier 1 already excluded from analytics, so a bad link can't misclassify a real expense — it can only mislink which transfer connects to which. Matches must be **mutually unique**: if a row has more than one same-window opposite-amount candidate in a different account, it's skipped, not force-matched to a guess.
- **Tier 3 — suggestions, `transfer_matcher.suggest_transfer_pairs()`.** Same matcher, run over *ordinary* income/expense rows with no category signal. Read-only — returns candidates for the user to confirm, never mutates. A same-window, cross-account, unique-match heuristic without this gate has empirically false-matched real pairs (a refund landing near an unrelated recurring charge) on a live dataset — this is why it's confirmation-only.
- **Retro-typing existing data, `transfer_matcher.retro_type_transfers()`.** Legacy imports never captured the original bank category, so retroactive detection is necessarily the Tier 3 heuristic applied to already-stored transactions. Defaults to `dry_run=True` (preview, no mutation); `dry_run=False` applies and audit-logs each pair. Idempotent — a second run finds no new candidates once both legs of a pair are already `transfer`-typed and linked.

`transfer_peer_id` (nullable, added in schema v3) is the only new column; the flat transaction store is otherwise unchanged — this was a deliberate choice over a double-entry rewrite (see [#8](https://github.com/googlarz/finance-assistant/issues/8) for the alternatives considered).

---

## Module Reference

### Core

| Module | Purpose |
|--------|---------|
| `skill.py` | Session entry: load profile, run security checks, surface alerts |
| `finance_storage.py` | Path resolution and JSON persistence |
| `profile_manager.py` | v2 profile schema, deep-merge updates |
| `currency.py` | `Money` dataclass (Decimal), exchange rates with 24h cache |

### Accounts & Transactions

| Module | Purpose |
|--------|---------|
| `account_manager.py` | CRUD for checking/savings/investment/loan accounts |
| `transaction_logger.py` | Log income/expense with auto-categorization (30 categories) |
| `recurring_engine.py` | Auto-generate recurring transactions (rent, salary, subscriptions) |
| `category_learner.py` | Learn from corrections to improve future auto-categorization |

### Planning & Goals

| Module | Purpose |
|--------|---------|
| `budget_engine.py` | Create budgets, 50/30/20 auto-distribution, variance analysis |
| `goal_tracker.py` | Savings goals with completion projections |

### Wealth

| Module | Purpose |
|--------|---------|
| `investment_tracker.py` | Portfolio CRUD, allocation, FIRE number, monthly snapshots |
| `price_sync.py` | Live prices — Yahoo Finance for stocks/ETFs, CoinGecko for crypto (no API key), 6h TTL |
| `subscription_detector.py` | Detect recurring charges from transaction history (monthly/yearly cadence, duplicates, price changes) |
| `subscription_actions.py` | Flag → remind → cancel loop; alerts if a flagged sub keeps charging |
| `investment_returns.py` | TWR, XIRR (Newton's method), per-holding performance |
| `debt_optimizer.py` | Avalanche/snowball simulation, mortgage optimization, debt-free date |
| `insurance_analyzer.py` | Policy tracking, coverage gaps, renewal alerts |
| `net_worth_engine.py` | Aggregate assets + investments − liabilities, JSON snapshots |

### Tax

| Module | Purpose |
|--------|---------|
| `tax_engine.py` | Country-agnostic interface, delegates to locale plugin via `importlib`; `get_tax_summary()` normalizer |
| `tax_brief.py` | Accountant/Steuerberater filing brief: computed tax + rules + deduction + doc checklist |
| `tax_scenarios.py` | Law-accurate what-if comparisons (W-2 vs 1099, single vs MFJ, pre-tax savings), saveable |
| `locale_telemetry.py` | Privacy-safe record of which locales get used (locale + operation only) |
| `locale_registry.py` | Rule provenance (source URL, verification date, confidence) |
| `locale_loader.py` | Dynamic locale import, on-demand skeleton builder for new countries |
| `locales/de/` | German locale: income tax, Soli, social contributions, 2024–2026 |
| `locales/uk/` | UK locale: income tax, NI, personal allowance taper £100k–£125,140 |
| `locales/us/` | US locale: federal brackets, standard deduction, SE tax + §199A QBI |
| `locales/fr/` | French locale: quotient familial, décote, CSG/CRDS assiette réduite |
| `locales/nl/` | Dutch locale: Box 1/2/3, heffingskorting, arbeidskorting, Box 3 uncertainty |
| `locales/pl/` | Polish locale: Polski Ład 12%/32%, 30k PLN free amount, składka zdrowotna |
| `locales/validation/` | 33 official test cases (BMF, HMRC, DGFiP, Belastingdienst, KAS, IRS) — all pass |

### Data & Simulation

| Module | Purpose |
|--------|---------|
| `db.py` | WAL-mode SQLite schema, `get_conn()` context manager, schema versioning |
| `db_migrate.py` | Idempotent JSON → SQLite migration |
| `monte_carlo.py` | 10,000-simulation Monte Carlo: FIRE, savings, debt payoff, net worth |

### Import

| Module | Purpose |
|--------|---------|
| `import_router.py` | Format detection and routing |
| `csv_importer.py` | 14 bank formats (DKB, ING, Sparkasse, Commerzbank, N26, Chase, BofA, Wells Fargo, Capital One, Wise, Revolut, Mint, Monarch, YNAB) + currency-symbol-aware parsing + generic fallback |
| `mt940_importer.py` | SWIFT MT940 with graceful fallback if library not installed |
| `ofx_importer.py` | OFX/QFX with normalized date parsing |
| `transaction_normalizer.py` | Auto-categorize, deduplicate, normalize amounts |
| `llm_import.py` | LLM-native fallback for any unrecognized format — Claude extracts, same sanitize/normalize/dedupe pipeline |

### Intelligence & Output

| Module | Purpose |
|--------|---------|
| `insight_engine.py` | Cross-domain insights, 4-status model, sorted by urgency |
| `scenario_engine.py` | Salary comparison, FIRE projection, rent-vs-buy, debt-vs-invest, mortgage |
| `workspace_builder.py` | 7-domain weighted health score |
| `output_builder.py` | Structured deliverables assembled into an output suite |
| `report_renderer.py` | Markdown and HTML reports |
| `snapshot_scheduler.py` | Monthly auto-snapshots (portfolio and net worth) |
| `session_alerts.py` | Proactive session nudges (budget, bills, deadlines, FIRE) |
| `document_sorter.py` | Classify financial documents by type |
| `adviser_handoff.py` | Structured referral brief for Steuerberater or adviser |

### Security & Operations

| Module | Purpose |
|--------|---------|
| `data_safety.py` | Fernet AES encryption, permissions hardening, git guard, export, delete, sanitize, audit |
| `audit_log.py` | Append-only mutation log (`~/.finance/audit.log`) — every change, with rotation |
| `backup.py` | Encrypted `.tar.gz` backup/restore (PBKDF2 + Fernet) to disk or iCloud |
| `sovereignty_check.py` | Measures local-model (Ollama) tax accuracy vs the deterministic engine |
| `household.py` | Shared household: members, expense splits, settle-up, shared goals |

---

## Testing

```bash
# Full suite (main + locales + official validation)
python3 -m pytest tests/ locales/tests/ locales/validation/ -q
# 1,237 tests — all modules, all locales, all official tax authority cases

python3 -m pytest tests/ -v                    # main skill only
python3 -m pytest locales/tests/ -v            # locale tax tests
python3 -m pytest locales/validation/ -v       # official authority validation
```

Tests use an isolated `.finance/` directory per test via the `isolated_finance_dir` autouse fixture — they never touch real data.

| File | What it tests |
|------|-------------|
| `tests/test_data_safety.py` | Encryption roundtrip, wrong passphrase, unique salts, permissions, git guard, encrypted export, sanitize |
| `tests/test_session_alerts.py` | Budget warnings, goal deadline alerts, urgency sorting, suppression footer |
| `tests/test_scenario_engine.py` | FIRE, salary comparison, rent-vs-buy, debt-vs-invest, real-engine tax wiring |
| `tests/test_tax_scenarios.py` | W-2 vs 1099, single vs MFJ, pre-tax contribution comparisons |
| `tests/test_investment_tracker.py` | FIRE number, portfolio growth projection, snapshots |
| `tests/test_debt_optimizer.py` | Avalanche vs snowball, interest savings, debt-free date |
| `tests/test_db.py` | SQLite schema init, CRUD operations, idempotent migration |
| `tests/test_monte_carlo.py` | All 4 simulators, percentile ordering, probability bounds, seeded reproducibility |
| `locales/tests/test_validation.py` | Official authority validation runner across all 6 locales |
| `locales/validation/*/` | 33 cases from BMF, HMRC, DGFiP, Belastingdienst, KAS, IRS |
