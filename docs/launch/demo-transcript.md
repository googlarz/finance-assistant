# Demo transcript (real output)

Captured 2026-09-21 on the 4.2.0-in-progress working tree, Python 3.9.6, macOS. Output is pasted verbatim from the commands shown. Numbers come from the seed data in `scripts/demo_data.py`; regenerate before posting.

## 1. The demo

```
$ mkdir -p /tmp/fa_demo && FINANCE_PROJECT_DIR=/tmp/fa_demo python3 skill.py --demo
Demo data seeded — sample profile, accounts, transactions, goals, debts, holdings.
Demo dashboard: /Users/dawid/.finance/dashboard_demo.html

When you're ready for the real thing, say 'wipe demo and start over'.
```

The demo dashboard is written to `~/.finance/`, not to `FINANCE_PROJECT_DIR`. A second run prints "Demo data already present (skipped reseeding)."

## 2. Net worth from the seeded data

```
$ FINANCE_PROJECT_DIR=/tmp/fa_demo python3 -c "from scripts import net_worth_engine as n; import json; print(json.dumps(n.calculate_net_worth(), indent=1))"
{
 "date": "2026-09-21",
 "currency": "EUR",
 "net_worth": 63880.0,
 "total_assets": 65980.0,
 "total_liabilities": 2100.0,
 "breakdown": {
  "cash_and_savings": 41500.0,
  "investments": 24480.0,
  "credit_card_balance": 0.0,
  "loans_and_debt": 2100.0
 },
 "account_count": 3,
 "holding_count": 1,
 "debt_count": 1
}
```

## 3. Tax summary (locale: de)

```
$ ... tax_engine.get_tax_summary()
{
 "locale": "de",
 "year": null,
 "gross": 58000.0,
 "income_tax": 12991.67,
 "payroll_tax": null,
 "total_tax": 12991.67,
 "social_tax": 11919.0,
 "total_burden": 24910.67,
 "net": 45008.33,
 "effective_rate": 0.224,
 "components": "DE income tax + Soli (+ church tax where set). total_burden adds employee social contributions (pension/health/care/unemployment).",
 "source": "engine"
}
```

## 4. Reconciliation check

```
$ ... reconciliation.check_all()
[]
```

(Empty list: no balance assertions in the demo, so nothing to flag.)

## 5. Health check and test run (same day)

```
$ python3 skill.py --doctor
  [!] Python version: 3.9.6 (3.10+ required)
  [✓] Dependencies: All core dependencies present
  [✓] Encryption (cryptography): cryptography package available
  [✓] Locales: 7 locale(s) available: de, fr, ie, nl, pl, uk, us
  [!] OCR (tesseract): tesseract binary not found
OK (with 2 warning(s))

$ python3 -m pytest -q
1 failed, 1557 passed, 1 skipped
FAILED tests/test_call_signatures.py::test_cross_module_calls_match_signatures
```

## Flags for the maintainer (resolve before posting)

- The working tree had 1 failing test and 1,559 collected, not the 1,565 the README badge states. Re-run on the release commit before quoting any test count.
- Python here is 3.9.6 and `--doctor` says 3.10+ is required; README states 3.10+ only for the MCP extra. Wording is inconsistent.
- `get_tax_summary()` returned `"year": null`. Describe it as "demo profile, DE" and do not attribute a tax year.
- The README examples (FIRE 73%, W-2 vs 1099) are not in this transcript; I did not reproduce them. Run them yourself before quoting figures in posts.
