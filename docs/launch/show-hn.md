# Show HN draft

Note: `hn-show.md` (older draft) also exists in this folder; this file supersedes it if you prefer this wording.

## Title

Show HN: Finance Assistant – deterministic tax engines for 7 countries, run from Claude Code

## URL

https://github.com/googlarz/finance-assistant

## Body (first comment)

I built a personal-finance skill for Claude Code where the LLM does the conversation and Python does the math. Tax figures come from deterministic engines applying the statute (e.g. German EStG §32a, US SE tax + QBI §199A), not from the model guessing brackets.

What it does:
- Tax engines for DE, UK, US, FR, NL, PL, IE, loaded from a locales git submodule. They are checked against 39 official tax-authority test cases (BMF, HMRC, DGFiP, Belastingdienst, KAS, IRS, Revenue). US cases are computed independently from IRS Rev. Proc. 2023-34 and Schedule SE.
- Imports 14 bank CSV formats on a fast path. Anything else (foreign bank, scanned PDF, screenshot) is read by Claude, then goes through the same sanitize, dedupe, confirm pipeline.
- Budgets, debt payoff comparison, net worth, FIRE with a 10,000-path Monte Carlo, saveable what-ifs (W-2 vs 1099, single vs MFJ).
- Data is local SQLite/JSON in `.finance/`. Optional Fernet encryption (PBKDF2 480k iterations), append-only audit log, a read-mostly MCP server (write tools are dry-run-first).
- `python3 skill.py --demo` seeds sample data so you can try it without your own numbers.

Limits, stated plainly:
- It is software, not a licensed advisor. Confirm filing decisions with a tax professional or your authority.
- "Validated" means the 39 official cases, which is not full coverage of every rule in every country. Some modules are explicitly not verified: the realized capital-gains estimate for DE/UK/IE uses rates checked against primary sources but a simplified model (for example no UK share-matching rules). Treat it as a planning aid, not a filing figure.
- Privacy: the data on disk never leaves your machine, but by default Claude Code sends the conversation to Anthropic's API. Zero egress needs a local model (there is a recipe and accuracy harness in docs/sovereignty.md; reasoning quality drops, the tax math does not). A few opt-in features call out: exchange rates (Frankfurter), stock/crypto prices (Yahoo, CoinGecko), GoCardless bank sync. The table of exactly what each sends is in docs/SECURITY.md.
- Other known limits: decrypted data sits in Python process memory while running; passphrases are not stored in the OS keychain.
- The Python floor is 3.10+ for the MCP server.

I would most like feedback on the locale plugin format (adding a country is meant to be a ~7-file contribution) and on where the tax engines disagree with your own return.

License CC BY 4.0.
