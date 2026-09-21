# Launch checklist (maintainer)

## Before anything is posted
1. Fix or explain the failing test `tests/test_call_signatures.py::test_cross_module_calls_match_signatures`; re-run the suite on the release commit and update the "1,565" figure everywhere if it differs (I saw 1,557 passed, 1 failed, 1 skipped on the working tree).
2. Cut 4.2.0 only after confirming the version number and creating a GitHub Release.
3. Reconcile the Python requirement (`--doctor` says 3.10+; README says 3.10+ for MCP only).
4. Re-run the README example conversations (FIRE 73%, W-2 vs 1099) and confirm the figures. They are not in demo-transcript.md and I did not verify them.
5. Confirm `assets/demo.svg` renders on the GitHub README (GitHub serves SVG via img tag; SMIL animation works when embedded with `<img>`, not inline).
6. Check `docs/launch/reddit.md`, `hn-show.md`, `product-hunt.md`, `awesome-claude-code-entry.md` (pre-existing) and decide which drafts to keep; my drafts are `show-hn.md`, `reddit-claudeai.md`, `linkedin.md`, `x-thread.md`.
7. Do not mention LLMessenger or other unrelated projects.

## Order and timing (suggested, adjust to your timezone)
1. Day 0, Tue-Thu ~15:00 CET: Show HN (`show-hn.md`). Post the body as the first comment. Stay online 3 hours.
2. Same day, +2h: r/ClaudeAI (`reddit-claudeai.md`). Check subreddit self-promotion rules first.
3. Day 0 evening: X thread (`x-thread.md`), attach `assets/demo.svg` rendered as GIF/video (X does not animate SVG).
4. Day 1 morning: LinkedIn (`linkedin.md`).
5. Day 1-3: submit plugin/skill directory listings (`plugin-listing.md`) and the awesome-claude-code entry.

## Answering comments
- Reply with specifics and repo links; concede limits fast. Bug reports: open an issue, link it back.
- Country requests: point to the locales repo and CONTRIBUTING.md (~7 files).
- "How is this validated?" 39 official tax-authority test cases; run `python3 -m pytest locales/tests/test_validation.py -v`. It is not a claim of full statutory coverage.

### "Is this financial advice?"
No. README: it applies real tax statute to your numbers but is software, not a licensed advisor; confirm filing decisions with a tax professional or your local authority. SKILL.md: it does not present itself as legally binding financial advice and hands off with a structured brief when a case exceeds scope. Be upfront that the DE/UK/IE capital-gains estimate is unverified against official sources.

### "Does my data leave my machine?"
Answer in two parts (docs/SECURITY.md):
- Data on disk: local in `.finance/`. No telemetry, no cloud sync, nothing uploaded. Optional Fernet encryption (PBKDF2-HMAC-SHA256, 480,000 iterations, per-file salt). Files chmod 600/700; `.finance/` auto-added to `.gitignore`; audit log; delete-all command.
- The conversation: by default Claude Code sends prompts and file context Claude sees to Anthropic's API. Zero egress means routing Claude Code through a local model (docs/sovereignty.md; reasoning quality drops, tax math is identical).
- Opt-in network calls only: api.frankfurter.app (base currency code), query1.finance.yahoo.com (tickers), api.coingecko.com (coin ids), bankaccountdata.gocardless.com (your GoCardless credentials, needs setup), cdn.jsdelivr.net (dashboard Chart.js, SRI-pinned). Nothing else opens a socket; readers can verify with `grep -rn "urlopen\|requests\." scripts/`.
- Be candid about limits: decrypted data is in process memory while running; the audit log `~/.finance/audit.log` is plaintext (chmod 600) with amounts and descriptions; passphrases are not kept in the OS keychain.

### "Why not just ask ChatGPT/Claude?"
The figures are computed by code and tested against official cases; the model does not guess brackets. Do not claim it is more accurate than a tax professional.

## After launch
- Log issues opened, stars, and which questions recurred; fold answers into README FAQ.
- Thank contributors, and tag country-request issues `good first locale`.
