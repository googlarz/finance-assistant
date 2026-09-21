# X thread draft

1/ I built a personal-finance skill for Claude Code where the LLM talks and Python does the math. Tax figures come from deterministic engines, not model guesses. Open source, local-first. https://github.com/googlarz/finance-assistant

2/ Tax engines for DE, UK, US, FR, NL, PL, IE. Checked against 39 official tax-authority test cases (BMF, HMRC, DGFiP, Belastingdienst, KAS, IRS, Revenue).

3/ Try it with sample data, no setup of your own numbers:
python3 skill.py --demo
Real output from the seeded demo: net worth 63,880 EUR (assets 65,980, liabilities 2,100). DE tax summary on 58,000 gross: income tax 12,991.67, effective rate 22.4%.

4/ Also: 14 bank CSV formats, LLM fallback for scans and screenshots, budgets, debt payoff, FIRE Monte Carlo (10,000 paths), saveable what-ifs like W-2 vs 1099.

5/ Privacy: data stays in a local .finance/ folder, optional encryption, audit log. But by default Claude Code sends the conversation to Anthropic. Local-model route is documented if you need zero egress.

6/ Limits: not financial advice. The DE/UK/IE capital-gains estimate uses source-checked rates but a simplified model. "Validated" means 39 cases, not every rule.

7/ Want a country added? Locale plugins are meant to be a ~7-file contribution. Feedback on where the engines disagree with your return is the most useful thing you can send.
