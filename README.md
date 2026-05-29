# Finance Assistant

[![version](https://img.shields.io/badge/version-3.9.2-blue)](https://github.com/googlarz/finance-assistant/releases)
[![tests](https://img.shields.io/badge/tests-1%2C226%20passing-brightgreen)](#running-tests)
[![tax cases](https://img.shields.io/badge/tax%20law-29%20official%20cases-success)](#locales)
[![locales](https://img.shields.io/badge/locales-DE·UK·US·FR·NL·PL-orange)](#locales)
[![local-first](https://img.shields.io/badge/local--first-no%20cloud-black)](#security--privacy)
[![license](https://img.shields.io/badge/license-CC%20BY%204.0-lightgrey)](LICENSE)

**Real math. Real law. Your machine.**

The precision of a tax accountant. The patience of a financial advisor.
The privacy of a local app. Open source. Free forever.

`6 locales` · `14 bank formats + any file via LLM` · `7 financial domains` · `Monte Carlo FIRE`

> **Built for Claude Code.** Full power runs in [Claude Code](https://claude.com/product/claude-code) (CSV import, SQLite, encrypted backup, inbox watcher, weekly digest, live prices).
> A claude.ai Projects template is included for conversational use, but most features require a local install. See [Where this runs](#where-this-runs) for the matrix.

**[→ Live demo](https://googlarz.github.io/finance-assistant/)** — see a real conversation without installing

---

### See it work — real output, not a mockup

```
You:  What's my FIRE confidence level?
FA:   Running 10,000 simulations (return 7%±12%, inflation 2%±0.8%)...

      Retirement probability: 73% success at 2042 target
      ┌─────────────────────────────────┐
      │  p10   $420k  ████             │
      │  p25   $580k  ██████           │
      │  p50   $790k  ████████         │  ← median
      │  p75  $1.05M  ██████████       │
      │  p90  $1.38M  █████████████    │
      └─────────────────────────────────┘
      Current: $180k  target: $900k

      +$200/month raises success to 81%.
```

That's deterministic math on your numbers — not a model guessing. [More examples ↓](#example-conversations)

### Try it in 30 seconds

```bash
git clone --recurse-submodules https://github.com/googlarz/finance-assistant.git
cd finance-assistant && pip install -r requirements.txt
python3 skill.py --demo        # seeds sample data → opens a dashboard
```

Then add it as a [Claude Code](https://claude.com/product/claude-code) skill and ask *"What's my financial health?"* — [full setup ↓](#quick-start).

---

Most people have a vague relationship with their finances. A rough sense of what they earn, a guess at what they owe in taxes, a hope that retirement will work out. Every tool that could help wants a monthly subscription and access to your bank account.

Finance Assistant is different. It runs on your machine, stores everything in a local SQLite database, and uses Claude to turn your real numbers into real answers — not estimates, not vibes, not "consult a professional." When you ask about your SE tax, it applies IRS Rev. Proc. 2024-40 to your actual income. When you ask about your UK pension, it pulls HMRC's carry-forward rules for the last three years. When you run a FIRE simulation, it runs 10,000 Monte Carlo paths, not a back-of-napkin multiple.

It works conversationally — no forms, no dashboards to fill in first. You tell it what you earn, what you owe, what you want. It remembers. It alerts you when something needs attention. It hands you a structured brief when you need a real accountant or adviser, and it gets out of the way when you don't.

No subscription. No cloud. No guessing.

---

| Without Finance Assistant | With Finance Assistant |
|---|---|
| YNAB: $15/month, your data on their servers | Free. SQLite on your machine. No subscription. |
| TurboTax: form wizard, no "what if I go freelance?" | SE tax + QBI §199A calculated in conversation |
| Generic ChatGPT: "I estimate your tax might be around…" | IRS Rev. Proc. 2024-40 applied to your actual income |
| Spreadsheet FIRE model you rebuild every year | Monte Carlo + named scenarios, saved and compared |
| UK pension: 20 min of Googling carry-forward rules | 3-year carry-forward with HMRC PTM057200, in seconds |
| Different tool for each country | DE · UK · US · FR · NL · PL — same commands everywhere |

### Why this over a general AI finance assistant?

Any assistant can *talk* about money. The difference is **law-accurate, bracket-correct tax math for six countries**, computed by deterministic code (`locales/<code>/tax_calculator.py`) — not by a model guessing brackets. A general or first-party finance assistant gives you plausible estimates; this applies the actual statute (German EStG §32a, IRS Rev. Proc., HMRC PTM) to your real numbers and shows its work. That per-jurisdiction depth is expensive to build and maintain, which is exactly why a general tool won't — and why this one leans into it. If your country isn't covered, the [scaffold generator](#locales) makes adding it a ~1-evening contribution with source-URL-annotated TODOs.

**See the output in 30 seconds** — [screenshot](#screenshot)
```bash
python3 skill.py --demo       # seed sample data → open ~/.finance/dashboard_demo.html
python3 skill.py --dashboard  # generate from your real data → ~/.finance/dashboard.html
```

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Quick Start](#quick-start)
3. [Locales](#locales)
4. [How It Works](#how-it-works)
5. [Data Storage Layout](#data-storage-layout)
6. [Security & Privacy](#security--privacy)
7. [Bank Statement Import](#bank-statement-import)
8. [Module Reference](#module-reference)
9. [Example Conversations](#example-conversations)
10. [Running Tests](#running-tests)
11. [Screenshot](#screenshot)

---

## What It Does

Finance Assistant covers the full personal finance lifecycle across 20+ operating modes:

| Mode | What you say | What you get |
|------|-------------|-------------|
| **Budget Manager** | "how am I doing on my budget?" | Variance by category, overspend alerts, pace warnings |
| **Transaction Logger** | "I spent €42 at REWE" | Logged, auto-categorized, budget actuals updated |
| **Savings Planner** | "I want to save €10k for a trip" | Timeline projection, monthly contribution needed |
| **Investment Tracker** | "show my portfolio" | Allocation, total return, XIRR, rebalance suggestions |
| **Debt Optimizer** | "best way to pay off my debts?" | Avalanche vs snowball comparison, debt-free date, interest saved |
| **Tax Module** | "what can I deduct?" | Locale-specific deductions (DE/UK/FR/NL/PL/US bundled) |
| **Subscription Radar** | "what am I subscribed to?" | Detects recurring charges, flags duplicates + still-charging-after-cancel |
| **Tax Filing Brief** | "prep my taxes for my accountant" | Hand-off doc: computed tax + statutory rules + deduction + document checklist |
| **Encrypted Backup** | "back up my data" | One file, AES + PBKDF2, to disk or iCloud |
| **Audit Trail** | "what changed today?" | Append-only log of every mutation |
| **Insurance Reviewer** | "do I have enough coverage?" | Coverage gap analysis, renewal alerts |
| **Net Worth Dashboard** | "where do I stand?" | Net worth with 7-domain health score and trend |
| **Data Import** | "import this statement" | Any format — 14 parsers fast-path, LLM reads the rest → preview → categorize → dedupe → import |
| **Scenario Lab** | "should I rent or buy?" | Before/after comparison with multi-year projection |
| **Monte Carlo** | "what's my FIRE confidence?" | 10,000-simulation distribution with p10/p50/p90 outcomes |
| **Specialist Handoff** | complex case | Structured brief for a Steuerberater or financial adviser |
| **Shared Household** | "split expenses with my partner" | Shared budget tracking, settlement ledger |
| **Month Comparison** | "how was March vs February?" | Month-over-month delta by category with trend arrows |
| **Scenario Memory** | "save this scenario" | Named scenario snapshots you can revisit and compare |
| **Session Recall** | "what did we discuss last week?" | Session-indexed memory of past financial decisions |
| **Milestone Alerts** | "alert me when net worth hits €100k" | User-configured threshold triggers surfaced at session start |
| **Freelance Analyser** | "should I go freelance?" | Break-even rate, net income comparison, billable-days threshold |

### Proactive Session Alerts

Every session start scans your finances and surfaces only what needs attention — ranked by urgency, with stale alerts auto-suppressed (and the footer tells you when it hid something):
- Budget overspend or pacing warnings ("85% of Groceries used at 16% of month")
- Upcoming recurring payments in the next 7 days
- Savings goal deadlines within 45 days
- Tax filing deadlines, incl. US quarterly estimated-tax dates
- Portfolio drift past your target allocation
- Recurring subscriptions — total burden, duplicates, and "still charging after you flagged it to cancel"
- Debt strategy nudges (avalanche could save you €X)
- Monthly FIRE progress bar (`[████████░░░░░░░░░░░░] 42.3% — €317k / €750k`)

---

## Where this runs

Finance Assistant is **built for Claude Code**. A claude.ai Projects template ships alongside it, but the browser sandbox can't reach your files, so most features are unavailable there.

| Feature                                  | Claude Code (full) | claude.ai Projects (limited) |
|------------------------------------------|:-:|:-:|
| Conversational budgeting & advice        | ✅ | ✅ |
| Tax math (DE/FR/NL/PL/UK/US brackets)    | ✅ | ✅ (you supply numbers) |
| Debt avalanche/snowball comparison       | ✅ | ✅ (you supply numbers) |
| Net-worth tracking                       | ✅ | ✅ (you supply numbers) |
| Bank CSV import (14 formats)             | ✅ | ❌ no file access |
| SQLite local storage + audit log         | ✅ | ❌ no local storage |
| Recurring subscription detection         | ✅ | ❌ needs transaction history |
| Live prices (Yahoo + CoinGecko)          | ✅ | ❌ no network in this skill's tools |
| FIRE Monte Carlo (10k paths)             | ✅ | ❌ needs local compute |
| Inbox watcher (drop CSV → auto-import)   | ✅ macOS launchd | ❌ |
| Weekly digest (scheduled OS notification)| ✅ macOS launchd | ❌ |
| Encrypted backup (`--backup`)            | ✅ | ❌ |
| Bank sync via GoCardless                 | ✅ | ❌ |

**Translation:** If you're on claude.ai web or mobile, you get a knowledgeable finance advisor that reasons over what you tell it in the chat. If you want it to read your bank statements, watch a folder, run scheduled digests, or hold a real database of your transactions, you need [Claude Code](https://claude.com/product/claude-code) (free CLI, runs locally).

### 100% private (zero data to Anthropic)

By default Claude Code sends your prompts and file context to Anthropic's API. The **data on disk** never leaves your machine, but the **conversation** does. If you want truly zero-egress operation, route Claude Code through a local model with [`claude-code-router`](https://github.com/musistudio/claude-code-router) and point it at [Ollama](https://ollama.com) running locally:

```bash
# 1. Install Ollama and pull a capable model
ollama pull llama3.3:70b      # or qwen2.5-coder:32b, deepseek-r1, etc.

# 2. Install claude-code-router
npm install -g @musistudio/claude-code-router

# 3. Configure it to route to your local Ollama (see router README)
```

**Full recipe + accuracy harness:** [`docs/sovereignty.md`](docs/sovereignty.md) walks through setup and ships a `sovereignty_check.py` harness that measures the local model's tax-reasoning accuracy against the deterministic engine on *your* hardware — so you can see the tradeoff before trusting it, instead of taking this README's word for it.

**Honest tradeoff:** open local models are meaningfully weaker than Claude on multi-step tax reasoning, bracket math, and "explain why" answers. You will get less precise tax calculations and worse advice quality. Use this mode if data sovereignty matters more than answer quality — e.g. when working with confidential client data or during the EU sovereignty audit at your job. For your own personal finances, the privacy gain over the standard local-first model (your data never leaves your machine; only the conversation does) is usually not worth the quality drop.

> **About the "Real math. Real law." promise at the top of this README:** that guarantee holds on the **default Claude path** — the tax engines apply real statute and the calculations are bracket-accurate regardless of model, but *interpreting* your situation correctly (which rule applies, what's deductible) is where a weaker local model degrades. Sovereignty mode explicitly trades away the advice-quality half of that promise. The deterministic math (`locales/<code>/tax_calculator.py`, invoked by `scripts/tax_engine.py`) runs the same either way; the reasoning around it does not. Pick the default path for anything tax-accuracy-critical.

---

## Quick Start

### Use on claude.ai (no installation)

If you use Claude on the web or mobile and don't want to install anything, use the Projects template:

1. Create a new **Project** on [claude.ai](https://claude.ai)
2. Paste the contents of [`projects-template/PROJECT_INSTRUCTIONS.md`](projects-template/PROJECT_INSTRUCTIONS.md) into the Project instructions field
3. Start chatting — budgeting, debt advice, savings goals, net worth tracking, and tax questions all work conversationally

**Limitations:** claude.ai runs in a browser and cannot access your computer's filesystem. That means no CSV import, no local SQLite database, no bank sync, no live prices, and no Monte Carlo simulations — those all require files or local storage that the browser can't reach. What works: conversational budgeting, tax questions, debt advice, savings goals, and net worth tracking based on what you tell it. For the full experience, use the Claude Code skill below.

---

### Install in Claude Code

Clone the repo and add it as a skill:

```bash
git clone --recurse-submodules https://github.com/googlarz/finance-assistant.git
cd finance-assistant
pip install -r requirements.txt
```

Add as a skill in `~/.claude/settings.json`:

```json
{
  "skills": [
    {
      "name": "finance-assistant",
      "path": "/path/to/finance-assistant"
    }
  ]
}
```

Then start a session: `What's my financial health?`

### Verify your install

```bash
python3 skill.py --version    # finance-assistant 3.9.2
python3 skill.py --doctor     # runs health checks on your setup
```

---

### Install in Claude Cowork

Cowork gives you the same agent capabilities as Claude Code in a desktop-friendly interface. For the best experience, set it up as a dedicated project:

**1. Create a new project**
Open Cowork → Projects → **New Project**. Name it something like `Finance`.

**2. Add a project instruction**
In the project's Instructions field, add:

```
Always load and use the Finance Assistant skill /finance-assistant.
Start every session by running skill.py to load my profile and surface any alerts.
```

**3. Start the project**
Open the Finance project and say: `What's my financial health?`

Claude will load your profile, surface any session alerts (budget warnings, upcoming bills, tax deadlines), and be ready for any finance question.

> **Tip:** Pin the Finance project to your Cowork sidebar so it's one click away at the start of each day.

---

## Locales

Tax rules and social contribution logic live in locale plugins — country-specific modules that the skill loads dynamically.

Locales are maintained in a separate git submodule at **https://github.com/googlarz/finance-assistant-locales**. The `--recurse-submodules` flag in the clone command above pulls them automatically.

| Locale | Coverage |
|--------|---------|
| **`de`** — Germany | Income tax, Soli, GKV/PKV social contributions, deductions, filing deadlines 2024–2026 |
| **`uk`** — United Kingdom | Income tax bands, NI Class 1, personal allowance taper (£100k–£125,140), insurance guidance (income protection, life, critical illness) 2024–2026 |
| **`fr`** — France | Quotient familial, décote, IR tranches, CSG/CRDS with assiette réduite (Art. L136-2 CSS) |
| **`nl`** — Netherlands | Box 1/2/3, heffingskorting, arbeidskorting (Box 3 Kerstarrest note included) |
| **`pl`** — Poland | Polski Ład reform: 12%/32%, 30k PLN free amount, składka zdrowotna |
| **`us`** — United States | Federal income tax brackets, standard deduction, self-employment tax + QBI §199A, quarterly estimated-tax deadlines |

DE, FR, NL, PL, and UK are validated against **29 official tax authority test cases** (BMF, HMRC, DGFiP, Belastingdienst, KAS) — run `python3 -m pytest locales/tests/test_validation.py -v`. The US locale ships with unit tests; official IRS reference cases are still being added (contributions welcome).

New locales can be contributed independently to the locales repository without touching the main skill code. See the [locales repo](https://github.com/googlarz/finance-assistant-locales) for the plugin interface, provenance format, and contribution guide.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                    Claude Code / Cowork                         │
│                                                                 │
│   You ──► skill.py ──► profile_manager ──► session_alerts      │
│                │                                                │
│                ▼                                                │
│         ┌──────────────────────────────────────────┐           │
│         │              18 Modes                    │           │
│         │  Budget · Transactions · Goals           │           │
│         │  Investments · Debt · Tax · Insurance    │           │
│         │  Net Worth · Import · Monte Carlo        │           │
│         │  Scenarios · Handoff                     │           │
│         └──────────────┬───────────────────────────┘           │
│                        │                                        │
│              ┌─────────▼──────────┐                            │
│              │   scripts/*.py     │  ◄── locale plugins        │
│              │  (real math, not   │    locales/de · uk · fr    │
│              │   hallucination)   │    locales/nl · pl · ...   │
│              └─────────┬──────────┘                            │
│                        │                                        │
│              ┌─────────▼──────────┐                            │
│              │  SQLite + .finance/ │  local only, never uploaded│
│              │  profile · budgets  │  optional export encryption│
│              │  investments · tax  │  chmod 600, git-ignored    │
│              │  (12-table WAL DB)  │  auto-migrates from JSON   │
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

The German locale is fully bundled via the `locales/` submodule. New locales can be scaffolded automatically via `locale_loader.py`.

### Multi-Currency

All amounts use the `Money` class (backed by `Decimal`) to avoid floating-point errors. Exchange rates are cached in `.finance/exchange_rates.json` with a 24-hour TTL; fallback rates are clearly marked as lower confidence.

---

## Data Storage Layout

All data is project-local in `.finance/`. No cloud sync, no external APIs, no telemetry.

As of v3.0, the primary store is **SQLite** (`finance.db`, WAL mode). JSON files are kept as a human-readable backup and for compatibility; new writes go to both.

```
.finance/
├── finance.db                    # SQLite database (12 tables, WAL mode, FK constraints)
│                                 # tables: profile, accounts, transactions, budget_categories,
│                                 #         goals, holdings, debts, snapshots, recurring_items,
│                                 #         scenarios, thresholds, insurance_policies
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

On first boot after upgrading to v3.0, `skill.py` automatically migrates all existing JSON data into SQLite using `db_migrate.py`. The migration is idempotent — safe to re-run, uses `INSERT OR IGNORE`.

**What is never stored:**
- Bank login credentials, passwords, PINs, TANs
- Full IBAN or bank account numbers
- Credit card numbers or CVV codes
- Tax IDs, passport numbers, national IDs
- Raw document contents

---

## Security & Privacy

### Design Principles

1. **Local-only**: All data lives in `.finance/` on your machine. No network calls for your personal data. No telemetry. No cloud sync.
2. **Structured summaries, not raw data**: Transaction amounts and categories are stored, not raw bank statements or login sessions.
3. **You own the delete button**: Every data category can be deleted individually or all at once.
4. **Encryption at rest**: Fernet AES-128-CBC + HMAC-SHA256 — the same authenticated encryption scheme used in production web services.
5. **Passphrase quality enforced**: The system rejects weak passphrases before encrypting (minimum 12 chars, character variety required), because a strong cipher with a weak key is still weak.
6. **Atomic writes**: Encrypted files are written to a `.enc.tmp` file first, then atomically renamed — a power failure or crash cannot leave a half-encrypted, unreadable file.
7. **File permissions**: `harden_permissions()` sets `.finance/` to `700` (owner-only directory) and all files to `600` (owner-only read/write). Other OS users on the same machine cannot read your data.
8. **Git guard**: On first session, `.finance/` is automatically added to `.gitignore` so financial data cannot be accidentally committed and pushed to a repository.
9. **Audit log**: Every significant data access (read, write, encrypt, export, delete) is logged to `audit/access_log.json` with a timestamp.
10. **Sanitize before sharing**: `sanitize_for_sharing(data)` strips all PII (names, employers, payees, addresses) before you share data to get help — financial amounts and structures are preserved.

### Encryption Details

```
Key derivation: PBKDF2-HMAC-SHA256
Iterations:     480,000 (NIST 2023 recommendation)
Salt:           16 bytes random per file (unique per encryption)
Cipher:         AES-128 in CBC mode (via Fernet)
MAC:            HMAC-SHA256 (Fernet built-in; prevents ciphertext tampering)
Encoding:       Base64url
Dependency:     pip install cryptography
```

Each file gets its own random salt. Two files encrypted with the same passphrase produce different ciphertexts — you cannot tell if two files contain the same data by comparing them.

The salt is stored alongside the ciphertext (standard practice — it only makes brute-force harder when combined with high iteration counts; it does not weaken the encryption).

### Encrypted Export

Backups can be encrypted before leaving your machine:

```python
# Encrypted backup — safe to store in cloud or email to yourself
export_all_data(passphrase="MyStr0ng!Passphrase")

# Plaintext export — keep offline only
export_all_data()
```

The encrypted export uses the same Fernet key derivation as individual file encryption. The passphrase is never stored anywhere.

### All Security Controls

```python
from scripts.data_safety import (
    get_privacy_summary,          # Full security status report
    get_data_inventory,           # Audit what's stored and where
    harden_permissions,           # chmod 600/700 on all .finance/ files
    check_permissions,            # Check for insecure file permissions
    ensure_gitignore_protection,  # Add .finance/ to .gitignore
    encrypt_sensitive_files,      # Encrypt profile, accounts, investments, debt
    decrypt_sensitive_files,      # Decrypt for use
    encrypt_file,                 # Encrypt a single file
    decrypt_file,                 # Decrypt a single file
    export_all_data,              # Export (plain or encrypted)
    import_data,                  # Import from export file
    delete_all_data,              # Permanent wipe (requires confirm=True)
    delete_category,              # Delete one category (requires confirm=True)
    sanitize_for_sharing,         # Strip PII before sharing for help
    get_access_log,               # View audit trail
)
```

### What Happens on First Session

```
skill.py (session start)
  ├── ensure_gitignore_protection()   # .finance/ → .gitignore
  ├── check_permissions()             # warn if group/world readable
  └── get_profile()                   # load or start onboarding
      └── (new user) show privacy statement
```

The privacy statement is shown once:

> *Your data lives only in `.finance/` on your machine — nothing is ever uploaded. You can encrypt it, export it, or delete it completely at any time. I never store bank credentials, card numbers, IBANs, or government IDs.*

### Threat Model

| Threat | Protection |
|--------|-----------|
| Another user on same machine reads your files | `harden_permissions()` — chmod 600/700 |
| Accidental `git push` of financial data | `ensure_gitignore_protection()` — automatic on session start |
| Laptop stolen, unencrypted disk | `encrypt_sensitive_files(passphrase)` + OS disk encryption (FileVault/LUKS) |
| Weak passphrase undermines AES | `_check_passphrase_strength()` — enforced before every encrypt call |
| Power failure during encryption corrupts file | Atomic write via `.enc.tmp` → `rename()` — POSIX atomic |
| Sharing data for help leaks names/employer | `sanitize_for_sharing()` — redacts all PII fields |
| Unexpected data access by a process | `get_access_log()` — timestamped audit trail |
| Cloud backup of export file exposes data | `export_all_data(passphrase=...)` — Fernet-encrypted export |

### Known Limitations

- **Memory**: Decrypted data resides in Python process memory while the skill is running. Python does not securely zero memory on deallocation. This is a fundamental Python limitation.
- **OS keychain**: Passphrases are not stored in the OS keychain (macOS Keychain, GNOME Keyring). You must provide the passphrase each session when using encrypted files. This is deliberate — no stored secret means no stored secret to steal.
- **Disk encryption**: If your disk is not encrypted (macOS FileVault, Linux LUKS), Fernet protects against OS-level access control bypass but not against forensic disk reads. Enable full-disk encryption for maximum protection.
- **Audit log**: The access log itself is protected by `harden_permissions()` but is not encrypted by default (it contains timestamps and action types, not financial amounts).

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
| `tax_engine.py` | Country-agnostic interface, delegates to locale plugin via `importlib` |
| `tax_brief.py` | Accountant/Steuerberater filing brief: computed tax + rules + deduction + doc checklist |
| `locale_telemetry.py` | Privacy-safe record of which locales get used (locale + operation only) |
| `locale_registry.py` | Rule provenance (source URL, verification date, confidence) |
| `locale_loader.py` | Dynamic locale import, on-demand skeleton builder for new countries |
| `locales/de/` | German locale: income tax, Soli, social contributions, 2024–2026 |
| `locales/uk/` | UK locale: income tax, NI, personal allowance taper £100k–£125,140 |
| `locales/fr/` | French locale: quotient familial, décote, CSG/CRDS assiette réduite |
| `locales/nl/` | Dutch locale: Box 1/2/3, heffingskorting, arbeidskorting, Box 3 uncertainty |
| `locales/pl/` | Polish locale: Polski Ład 12%/32%, 30k PLN free amount, składka zdrowotna |
| `locales/validation/` | 29 official test cases (BMF, HMRC, DGFiP, Belastingdienst, KAS) — all pass |

### Data & Simulation

| Module | Purpose |
|--------|---------|
| `db.py` | 12-table SQLite schema, WAL mode, `get_conn()` context manager |
| `db_migrate.py` | Idempotent JSON → SQLite migration (`INSERT OR IGNORE`) |
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

### Security

| Module | Purpose |
|--------|---------|
| `data_safety.py` | Fernet AES encryption, permissions hardening, git guard, export, delete, sanitize, audit |
| `audit_log.py` | Append-only mutation log (`~/.finance/audit.log`) — every change, with rotation |
| `backup.py` | Encrypted `.tar.gz` backup/restore (PBKDF2 + Fernet) to disk or iCloud |
| `sovereignty_check.py` | Measures local-model (Ollama) tax accuracy vs the deterministic engine |
| `household.py` | Shared household: members, expense splits, settle-up, shared goals |

---

## Example Conversations

### Monte Carlo FIRE Projection

```
You:  What's my FIRE confidence level?
FA:   Running 10,000 simulations (return 7%±12%, inflation 2%±0.8%)...

      Retirement probability: 73% success at 2042 target
      ┌─────────────────────────────────┐
      │  p10   $420k  ████             │
      │  p25   $580k  ██████           │
      │  p50   $790k  ████████         │  ← median
      │  p75  $1.05M  ██████████       │
      │  p90  $1.38M  █████████████    │
      └─────────────────────────────────┘
      Current: $180k  target: $900k

      Sequence risk: worst 10% of runs hit a bad first decade.
      Mitigation: +$200/month raises success to 81%.
```

### "Should I go freelance?" (US — real SE tax + QBI math)

```
You:  I make $80k as a W-2 employee. What changes if I go 1099 freelance
      at the same $80k?

FA:   Same $80k, two tax pictures (2024, single, federal):

      As a W-2 employee:
        Federal income tax       $9,441
        Your FICA (SS + Medicare) $6,120   (employer pays another $6,120)
        Effective rate           11.8%

      As a 1099 freelancer:
        Self-employment tax      $11,304   (you pay BOTH FICA halves — Schedule SE)
        − ½ SE tax deduction     −$5,652   (above the line)
        − §199A QBI deduction    −$11,950  (20% of profit, IRS Rev. Proc. 2024-40)
        Taxable income           $47,799
        Federal income tax       $5,569
        Total federal + SE       $16,872

      → Going freelance at the SAME headline number costs ~$1,300 more in
        federal+SE tax, because SE tax replaces the employer's FICA share.
        To break even you'd need to bill ~$82k. Want the break-even rate?
```

### Debt Optimization

```
You:  Best strategy to pay off my 3 loans?
FA:   Avalanche (highest rate first):
        Credit card $3,200 @ 18.9% → Car loan $8,600 @ 5.9% → Personal loan $13,000 @ 3.4%
        Interest saved vs minimum: $2,840 | Debt-free: Nov 2027

      Snowball (smallest balance first):
        Same order (happens to match) in this case
        Interest saved vs minimum: $1,920 | Debt-free: Feb 2028

      → Avalanche saves $920 more and finishes 3 months earlier.
        Choose snowball only if you need the win of a quick first payoff.
```

### Budget Check

```
You:  How am I doing on my April budget?
FA:   $340 of $400 food budget used (85%) — 28 days into 30-day month. On pace.
      Transport: $112 / $150 (75%) — fine.
      Eating out: $89 / $80 — OVER by $9 ⚠

      Suggestion: $11 left in eating out. One meal left this month.
      Adjacent: Groceries has $60 remaining — cooking covers the gap.
```

### Same depth in every locale

The tax math isn't US-only — each locale applies its own statute. Ask the same
"what can I deduct?" in Germany and you get German law, not a translation of US rules:

```
You:  What can I deduct this year?  (locale: de)
FA:   Profile: angestellt, Berlin, homeoffice 3 days/week

      ✓ Arbeitnehmer-Pauschbetrag: €1,230 (automatic, EStG §9a)
      ✓ Homeoffice-Pauschale: €6/day × 210 days = €1,260 (at cap)
      ✓ Pendlerpauschale: €0 (homeoffice replaces commute)
      ? Gewerkschaftsbeitrag / Fortbildungskosten: enter amounts to refine

      Estimated refund above Pauschbetrag: ~€340
```

UK pulls HMRC pension carry-forward; France applies the quotient familial and
décote; the Netherlands handles Box 1/2/3. Six countries, one set of commands.

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'locales'`

The locale data lives in a git submodule. If you cloned without `--recurse-submodules`, run:

```bash
git submodule update --init --recursive
```

Then re-run `python3 skill.py --doctor` to verify.

### Locale not found for my country

See [CONTRIBUTING.md](CONTRIBUTING.md) for the locale plugin spec — adding a new country is ~7 files.

---

## Running Tests

```bash
# Full suite (main + locales + official validation)
python3 -m pytest tests/ locales/tests/ locales/validation/ -q
# 1,208 tests — all modules, all locales, all official tax authority cases

# Main skill only
python3 -m pytest tests/ -v

# Locale tax tests
python3 -m pytest locales/tests/ -v

# Official validation (BMF / HMRC / DGFiP / Belastingdienst / KAS)
python3 -m pytest locales/validation/ -v
```

Tests use an isolated `.finance/` directory per test via the `isolated_finance_dir` autouse fixture — they never touch real data.

Key test files:

| File | What it tests |
|------|-------------|
| `tests/test_data_safety.py` | Encryption roundtrip, wrong passphrase, unique salts, permissions, git guard, encrypted export, sanitize |
| `tests/test_session_alerts.py` | Budget warnings, goal deadline alerts, urgency sorting |
| `tests/test_scenario_engine.py` | FIRE, salary comparison, rent-vs-buy, debt-vs-invest |
| `tests/test_investment_tracker.py` | FIRE number, portfolio growth projection, snapshots |
| `tests/test_debt_optimizer.py` | Avalanche vs snowball, interest savings, debt-free date |
| `tests/test_db.py` | SQLite schema init, CRUD operations, idempotent migration |
| `tests/test_monte_carlo.py` | All 4 simulators, percentile ordering, probability bounds, seeded reproducibility |
| `tests/test_recurring_engine.py` | Calendar-aware day clamping (Feb 28/29, Apr 30, Mar 31) |
| `locales/tests/test_de_tax.py` | German income tax, Soli, social contributions, 2024–2026 |
| `locales/tests/test_fr_tax.py` | French quotient familial, décote, CSG assiette réduite |
| `locales/tests/test_validation.py` | Official authority validation runner across all 5 locales |
| `locales/validation/*/` | 29 cases from BMF, HMRC, DGFiP, Belastingdienst, KAS |

---

## Screenshot

![Finance Assistant Dashboard](assets/dashboard-preview.jpg)
