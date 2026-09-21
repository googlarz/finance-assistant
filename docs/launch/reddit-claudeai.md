# r/ClaudeAI draft

## Title

I built a Claude Code skill that does personal finance with deterministic tax math instead of LLM guesses (open source, local)

## Body

Claude is good at explaining money and unreliable at arithmetic, so I split the job: Claude handles the conversation, Python engines do the numbers.

- Tax engines for DE / UK / US / FR / NL / PL / IE, checked against 39 official tax-authority test cases
- Budgets, debt avalanche vs snowball, net worth, FIRE Monte Carlo (10,000 paths), "what if I go freelance" comparisons
- 14 bank CSV formats; anything else (scanned PDF, screenshot, foreign bank) is read by Claude through the same dedupe-and-confirm pipeline
- Data stays in a local `.finance/` folder; optional encryption; an MCP server so Claude Desktop can read your numbers

Try it without your own data:

```bash
git clone --recurse-submodules https://github.com/googlarz/finance-assistant.git ~/.claude/skills/finance-assistant
pip install -r ~/.claude/skills/finance-assistant/requirements.txt
python3 ~/.claude/skills/finance-assistant/skill.py --demo
```

Then start a new Claude Code session and ask "What's my financial health?"

Honest caveats: it is not financial or tax advice. The capital-gains estimate (DE/UK/IE) uses rates and allowances checked against primary sources (gesetze-im-internet.de, gov.uk, revenue.ie) but a simplified model (for example no UK share-matching rules), so it is a planning aid, not a filing figure. And Claude Code still sends your conversation to Anthropic unless you route it to a local model (docs/sovereignty.md) — only the data on disk stays local.

Repo: https://github.com/googlarz/finance-assistant

Happy to hear which countries and bank formats to add next.
