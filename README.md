# Finance Assistant

[![version](https://img.shields.io/badge/version-3.11.1-blue)](https://github.com/googlarz/finance-assistant/releases)
[![tests](https://img.shields.io/badge/tests-1%2C237%20passing-brightgreen)](docs/ARCHITECTURE.md#testing)
[![tax cases](https://img.shields.io/badge/tax%20law-33%20official%20cases-success)](#locales--validation)
[![locales](https://img.shields.io/badge/locales-DE·UK·US·FR·NL·PL-orange)](#locales--validation)
[![local-first](https://img.shields.io/badge/local--first-no%20cloud-black)](docs/SECURITY.md)
[![license](https://img.shields.io/badge/license-CC%20BY%204.0-lightgrey)](LICENSE)

**Real math. Real law. Your machine.**

A personal finance copilot that applies actual tax statute to your real numbers — not estimates, not vibes. Runs locally through [Claude Code](https://claude.com/product/claude-code); your data never leaves your machine. Open source, free forever.

`6 locales` · `14 bank formats + any file via LLM` · `Monte Carlo FIRE` · `1,237 tests`

**[→ Live demo](https://googlarz.github.io/finance-assistant/)** — see a real conversation without installing

---

## See it work — real output, not a mockup

**FIRE confidence, with the actual distribution:**

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

**"Should I go freelance?" — with real SE tax + QBI, not a guess:**

```
You:  I make $80k as a W-2 employee. What changes if I go 1099 at the same $80k?
FA:   Same $80k, two tax pictures (2024, single, federal):

      As a W-2 employee:
        Federal income tax        $9,441
        Your FICA (SS + Medicare) $6,120   (employer pays another $6,120)

      As a 1099 freelancer:
        Self-employment tax       $11,304  (you pay BOTH FICA halves — Schedule SE)
        − ½ SE tax deduction      −$5,652
        − §199A QBI deduction     −$11,950 (IRS Rev. Proc. 2024-40)
        Federal income tax        $5,569
        Total federal + SE        $16,872

      → Freelancing at the SAME number costs ~$1,300 more, because SE tax
        replaces the employer's FICA share. Break-even ≈ $82k. Want the rate?
```

Every figure is deterministic Python applying real statute — and it's [validated against 33 official tax-authority test cases](#locales--validation). [More examples ↓](#more-conversations)

---

## Who it's for

People who want **correct** answers about their own money — not a chatbot's plausible guess and not a SaaS that wants your bank login. Especially:

- Anyone with **real tax complexity** — freelance/1099, multiple countries, equity, "what if I change X" questions — tired of estimates.
- **Privacy-conscious** people who want their financial data to stay on their own disk.
- **Claude Code users** who'd rather talk to their finances than fill in a dashboard.

If your country isn't covered, the [scaffold generator](#locales--validation) makes adding it a ~1-evening contribution.

## Why this over a general AI assistant?

Any assistant can *talk* about money. The difference is **law-accurate, bracket-correct tax math for six countries**, computed by deterministic code — not a model guessing brackets. A general (or first-party) assistant gives you plausible estimates; this applies the actual statute (German EStG §32a, IRS Rev. Proc., HMRC PTM) to your real numbers, shows its work, and is tested against official authority cases.

| Instead of… | You get |
|---|---|
| YNAB: $15/month, your data on their servers | Free. SQLite on your machine. No subscription. |
| TurboTax: form wizard, no "what if I go freelance?" | SE tax + QBI §199A computed in conversation, saveable |
| Generic ChatGPT: "your tax might be around…" | IRS Rev. Proc. 2024-40 applied to your actual income |
| Spreadsheet FIRE model you rebuild yearly | Monte Carlo + named scenarios, saved and compared |
| UK pension: 20 min of Googling carry-forward | 3-year carry-forward with HMRC PTM057200, in seconds |
| A different tool per country | DE · UK · US · FR · NL · PL — same commands everywhere |

---

## Install

**One line** — clone straight into your skills folder (Claude Code auto-discovers it, no config to edit):

```bash
git clone --recurse-submodules https://github.com/googlarz/finance-assistant.git \
  ~/.claude/skills/finance-assistant
pip install -r ~/.claude/skills/finance-assistant/requirements.txt
```

Start a new Claude Code session and ask: **"What's my financial health?"**

```bash
python3 ~/.claude/skills/finance-assistant/skill.py --demo     # try it with sample data first
python3 ~/.claude/skills/finance-assistant/skill.py --doctor   # verify your setup
```

<details>
<summary>Already cloned elsewhere? · claude.ai (no install) · Claude Cowork</summary>

**Already cloned to a dev location?** Register it without moving it:
```bash
cd /path/to/your/finance-assistant
python3 skill.py --install     # symlinks into ~/.claude/skills/ (git pull stays live)
```

**claude.ai web/mobile (no install):** create a Project and paste [`projects-template/PROJECT_INSTRUCTIONS.md`](projects-template/PROJECT_INSTRUCTIONS.md) into its instructions. Conversational only — the browser can't reach files, so no CSV import, SQLite, live prices, or Monte Carlo. See [Where this runs](#where-this-runs).

**Claude Cowork:** create a project, add the instruction *"Always load and use the Finance Assistant skill /finance-assistant"*, and ask "What's my financial health?".
</details>

---

## What it does

A conversational copilot across the full personal-finance lifecycle. The highlights:

- **Tax, law-accurate** — deductions, filing brief for your accountant, and saveable what-ifs (`W-2 vs 1099`, `single vs MFJ`, `max the 401k?`) computed from real brackets in 6 countries.
- **Plan & project** — budgets, savings goals, debt avalanche/snowball, FIRE with 10,000-path Monte Carlo, rent-vs-buy and salary-offer comparisons.
- **Track wealth** — portfolio allocation/XIRR, live stock + crypto prices, net-worth health score.
- **Import anything** — 14 bank-CSV formats on a fast path; an unrecognized file (foreign bank, scanned PDF, screenshot) is read by Claude directly, same sanitize→dedupe→confirm pipeline.
- **Stay ahead** — every session surfaces only what needs attention: budget overspend, upcoming bills, tax deadlines, portfolio drift, zombie subscriptions ("still charging after you flagged it to cancel"), FIRE progress. Stale alerts auto-suppress.
- **Own your data** — local SQLite, encrypted backup, append-only audit log of every change, one-command total wipe.

<details>
<summary>Full list of 20+ modes</summary>

Budget Manager · Transaction Logger · Savings Planner · Investment Tracker · Debt Optimizer · Tax Module · Tax What-Ifs · Tax Filing Brief · Subscription Radar · Encrypted Backup · Audit Trail · Insurance Reviewer · Net Worth Dashboard · Data Import (LLM fallback) · Scenario Lab · Monte Carlo · Specialist Handoff · Shared Household · Month Comparison · Scenario Memory · Session Recall · Milestone Alerts · Freelance Analyser
</details>

---

## More conversations

```
You:  Best strategy to pay off my 3 loans?
FA:   Avalanche (highest rate first):
        Credit card $3,200 @ 18.9% → Car loan $8,600 @ 5.9% → Personal loan $13,000 @ 3.4%
        Interest saved vs minimum: $2,840 | Debt-free: Nov 2027
      Snowball (smallest first): saves $1,920 | Debt-free: Feb 2028
      → Avalanche saves $920 more and finishes 3 months earlier.
```

```
You:  How am I doing on my April budget?
FA:   $340 of $400 food (85%) — 28 days into 30-day month. On pace.
      Eating out: $89 / $80 — OVER by $9 ⚠
      Groceries has $60 remaining — cooking covers the gap.
```

The tax depth isn't US-only — ask "what can I deduct?" in Germany and you get German law (Arbeitnehmer-Pauschbetrag, Homeoffice-Pauschale, EStG §9a), not a translation of US rules. UK pulls HMRC pension carry-forward; France applies the quotient familial. Six countries, one set of commands.

---

## Locales & validation

Tax rules live in country-specific plugins (a [git submodule](https://github.com/googlarz/finance-assistant-locales)) that the skill loads dynamically.

| Locale | Coverage |
|--------|---------|
| **`de`** Germany | Income tax, Soli, GKV/PKV social contributions, deductions, deadlines 2024–2026 |
| **`uk`** United Kingdom | Income tax bands, NI Class 1, personal-allowance taper (£100k–£125,140), insurance |
| **`us`** United States | Federal brackets, standard deduction, SE tax + QBI §199A, quarterly estimated-tax dates |
| **`fr`** France | Quotient familial, décote, IR tranches, CSG/CRDS (assiette réduite) |
| **`nl`** Netherlands | Box 1/2/3, heffingskorting, arbeidskorting (Box 3 Kerstarrest note) |
| **`pl`** Poland | Polski Ład: 12%/32%, 30k PLN free amount, składka zdrowotna |

All six are validated against **33 official tax-authority test cases** (BMF, HMRC, DGFiP, Belastingdienst, KAS, IRS) — `python3 -m pytest locales/tests/test_validation.py -v`. US cases are computed independently from IRS Rev. Proc. 2023-34 and Schedule SE. Adding a country is independent of the main code — see the [locales repo](https://github.com/googlarz/finance-assistant-locales).

---

## Where this runs

**Built for Claude Code** (the free CLI). A claude.ai Projects template ships too, but the browser sandbox can't reach your files, so most features need the local install.

| Feature | Claude Code | claude.ai Projects |
|---|:-:|:-:|
| Conversational budgeting, tax math, debt & net-worth advice | ✅ | ✅ (you supply the numbers) |
| Bank import · SQLite · subscription detection · live prices | ✅ | ❌ no file/network access |
| FIRE Monte Carlo · encrypted backup · inbox watcher · weekly digest | ✅ | ❌ needs local compute/launchd |

**Want zero data to Anthropic?** For full privacy, run Claude Code against a local model: point [claude-code-router](https://github.com/musistudio/claude-code-router) at [Ollama](https://ollama.com) and nothing leaves your machine — not even the conversation. The deterministic tax math is identical; only the reasoning quality drops. Recipe + an accuracy harness you run yourself: [`docs/sovereignty.md`](docs/sovereignty.md).

---

## Privacy & security

Local-first by design. Your data lives only in `.finance/` on your machine — no cloud, no telemetry, nothing uploaded.

- **Encrypted at rest** — Fernet (AES-128-CBC + HMAC-SHA256), PBKDF2 480k iterations, atomic writes.
- **Hardened** — `.finance/` is chmod 600/700 and auto-added to `.gitignore` on first run.
- **You own the delete button** — wipe any category or everything, one command.
- **Audit log** — every change is recorded; `--audit` shows what happened.
- **Never stored** — bank credentials, IBANs, card numbers, government IDs, raw documents.

This protects your data **at rest**. By default Claude Code still sends the **conversation** to Anthropic's API — for zero egress, route it through a local model ([Sovereignty mode](docs/sovereignty.md)).

Full detail — encryption parameters, threat model, all controls, known limitations — in [`docs/SECURITY.md`](docs/SECURITY.md).

---

## Docs

- [**Architecture**](docs/ARCHITECTURE.md) — how it works, data layout, full module reference, testing
- [**Security**](docs/SECURITY.md) — encryption, threat model, controls
- [**Sovereignty mode**](docs/sovereignty.md) — run fully local via Ollama + accuracy harness
- [**Contributing**](CONTRIBUTING.md) — add a locale (~7 files), plugin spec, provenance format

**Troubleshooting:** `ModuleNotFoundError: No module named 'locales'` → you cloned without submodules; run `git submodule update --init --recursive`, then `python3 skill.py --doctor`.

---

Open source under [CC BY 4.0](LICENSE). Built on real statute, tested against official numbers, run on your own machine.

![Finance Assistant Dashboard](assets/dashboard-preview.jpg)
