# LinkedIn draft

I got tired of AI assistants answering tax questions with "roughly", so I built one that does not guess.

Finance Assistant is an open-source skill for Claude Code. The language model handles the conversation. Deterministic Python engines apply actual tax statute to your numbers for Germany, the UK, the US, France, the Netherlands, Poland and Ireland, and they are checked against 39 official tax-authority test cases.

It also imports bank CSVs (14 formats, plus an LLM fallback for anything else), tracks budgets and net worth, and runs a 10,000-path Monte Carlo for early-retirement planning.

Design choices I care about:
- Your data lives in a local folder. No telemetry, no cloud sync.
- Optional encryption at rest and an audit log of every change.
- Clear limits: it is software, not a licensed advisor, and the capital-gains estimate uses rates checked against primary sources but a simplified model, so it is a planning aid.
- One honest caveat: by default the conversation itself goes to Anthropic's API through Claude Code. A local-model route exists if that matters to you.

If you work in tax, fintech or privacy-sensitive tooling, I would value your review of the engines.

https://github.com/googlarz/finance-assistant

#opensource #personalfinance #claudecode #privacy
