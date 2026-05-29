#!/usr/bin/env python3
"""
Finance Assistant — Locale Scaffold Generator.

Generates a skeleton locale directory with the correct plugin interface,
stub implementations for every required function, and a LOCALE_CONTRACTS
snippet for validate_locale.py.

Usage:
    python3 scripts/scaffold_locale.py AT
    python3 scripts/scaffold_locale.py CH --locale-name Switzerland
    python3 scripts/scaffold_locale.py CA --locale-name Canada

What gets created:
    locales/<CODE>/
    ├── __init__.py        Module exports + LOCALE_CODE / LOCALE_NAME / SUPPORTED_YEARS
    ├── tax_rules.py       Year-keyed dicts with tax parameters (fill in real values)
    └── tax_calculator.py  calculate_tax() + get_tax_rules() implementing the plugin interface

After running:
    1. Fill every TODO in the generated files with real tax parameters.
    2. Add a LOCALE_CONTRACTS entry in scripts/validate_locale.py (snippet printed below).
    3. Run: python3 scripts/validate_locale.py
    4. Open a PR — see CONTRIBUTING.md for review checklist.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

# Map ISO-3166-1 alpha-2 code → (locale name, currency)
_DEFAULTS: dict[str, tuple[str, str]] = {
    "AT": ("Austria", "EUR"),
    "CH": ("Switzerland", "CHF"),
    "CA": ("Canada", "CAD"),
    "AU": ("Australia", "AUD"),
    "ES": ("Spain", "EUR"),
    "IT": ("Italy", "EUR"),
    "PT": ("Portugal", "EUR"),
    "SE": ("Sweden", "SEK"),
    "NO": ("Norway", "NOK"),
    "DK": ("Denmark", "DKK"),
}

# Authoritative tax-authority sources per locale. Injected into the generated
# TODOs so a contributor has the real link instead of "<official URL>" — this
# is the difference between a ~1-evening contribution and a research project.
_SOURCES: dict[str, dict[str, str]] = {
    "AT": {
        "authority": "Bundesministerium für Finanzen (BMF)",
        "income_tax": "https://www.bmf.gv.at/themen/steuern/das-steuersystem/einkommensteuer.html",
        "social": "https://www.gesundheitskasse.at",
    },
    "CH": {
        "authority": "Eidgenössische Steuerverwaltung (ESTV)",
        "income_tax": "https://www.estv.admin.ch/estv/en/home/direct-federal-tax/direct-federal-tax.html",
        "social": "https://www.ahv-iv.ch",
    },
    "CA": {
        "authority": "Canada Revenue Agency (CRA)",
        "income_tax": "https://www.canada.ca/en/revenue-agency/services/tax/individuals/frequently-asked-questions-individuals/canadian-income-tax-rates-individuals-current-previous-years.html",
        "social": "https://www.canada.ca/en/employment-social-development/programs/ei.html",
    },
    "AU": {
        "authority": "Australian Taxation Office (ATO)",
        "income_tax": "https://www.ato.gov.au/rates/individual-income-tax-rates/",
        "social": "https://www.ato.gov.au/individuals/super/",
    },
    "ES": {
        "authority": "Agencia Tributaria",
        "income_tax": "https://sede.agenciatributaria.gob.es/Sede/en_gb/irpf.html",
        "social": "https://www.seg-social.es",
    },
    "IT": {
        "authority": "Agenzia delle Entrate",
        "income_tax": "https://www.agenziaentrate.gov.it/portale/web/guest/schede/dichiarazioni/irpef",
        "social": "https://www.inps.it",
    },
    "PT": {
        "authority": "Autoridade Tributária e Aduaneira",
        "income_tax": "https://www.portaldasfinancas.gov.pt",
        "social": "https://www.seg-social.pt",
    },
    "SE": {
        "authority": "Skatteverket",
        "income_tax": "https://www.skatteverket.se/privat/skatter/beloppochprocent.4.html",
        "social": "https://www.forsakringskassan.se",
    },
    "NO": {
        "authority": "Skatteetaten",
        "income_tax": "https://www.skatteetaten.no/en/rates/",
        "social": "https://www.nav.no",
    },
    "DK": {
        "authority": "Skattestyrelsen",
        "income_tax": "https://skat.dk/en-us/individuals/tax-cards-and-tax-assessment-notices",
        "social": "https://www.borger.dk",
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _locale_dir(code: str) -> Path:
    return _REPO_ROOT / "locales" / code.lower()


def _write(path: Path, content: str, *, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[dry-run] would write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip())
    print(f"  created {path.relative_to(_REPO_ROOT)}")


def generate(code: str, locale_name: str, currency: str, *, dry_run: bool = False) -> None:
    code_upper = code.upper()
    code_lower = code.lower()
    target = _locale_dir(code_lower)

    # Resolve authoritative source URLs for this locale (real links injected
    # into the generated TODOs). Falls back to placeholders for unknown codes.
    src = _SOURCES.get(code_upper, {})
    src_authority = src.get("authority", f"{locale_name} national tax authority")
    src_income = src.get("income_tax", "<official income-tax rates URL>")
    src_social = src.get("social", "<official social-security URL>")

    if target.exists() and any(target.iterdir()):
        print(f"⚠  {target} already exists and is non-empty. Aborting to avoid overwrite.")
        sys.exit(1)

    print(f"\nScaffolding locale: {code_upper} — {locale_name} ({currency})")
    print(f"Output directory:   locales/{code_lower}/\n")

    # ── __init__.py ──────────────────────────────────────────────────────────
    _write(target / "__init__.py", f"""\
        \"\"\"
        Finance Assistant locale plugin: {locale_name} ({code_upper}).

        Auto-generated by scaffold_locale.py. Replace every TODO with real
        values sourced from official government tax publications.
        \"\"\"

        from __future__ import annotations

        from .tax_rules import get_tax_year_rules
        from .tax_calculator import calculate_tax, get_tax_rules

        LOCALE_CODE = "{code_lower}"
        LOCALE_NAME = "{locale_name}"
        SUPPORTED_YEARS = [2024, 2025, 2026]

        __all__ = [
            "LOCALE_CODE",
            "LOCALE_NAME",
            "SUPPORTED_YEARS",
            "calculate_tax",
            "get_tax_rules",
        ]
        """, dry_run=dry_run)

    # ── tax_rules.py ─────────────────────────────────────────────────────────
    _write(target / "tax_rules.py", f"""\
        \"\"\"
        Tax rules for {locale_name} ({code_upper}).

        Fill in the actual tax parameters from official government sources.
        Cite your source as a comment on each value — makes future updates
        easier and lets reviewers verify correctness.

        Primary source — {src_authority}:
          - Income tax rates:   {src_income}
          - Social security:    {src_social}
        Cross-check:
          - OECD country tax notes: https://stats.oecd.org (Table I.1–I.7)
          - PwC Worldwide Tax Summaries: https://taxsummaries.pwc.com/{locale_name.lower().replace(' ', '-')}
        \"\"\"

        from __future__ import annotations


        # ── 2024 ─────────────────────────────────────────────────────────────────

        _2024: dict = {{
            "year": 2024,
            "currency": "{currency}",

            # Income tax-free allowance / personal allowance
            # TODO: replace with real value. Source: {src_income}
            "tax_free_allowance": 0,

            # Tax brackets: list of {{rate: float, from: int, to: int | None}}
            # 'to' is None for the top bracket.
            # TODO: fill with real brackets. Source: {src_income}
            "tax_brackets": [
                {{"rate": 0.20, "from": 0, "to": None}},  # TODO — placeholder
            ],

            # Standard deduction or equivalent (0 if not applicable)
            "standard_deduction": 0,

            # Social contribution rate (employee share, approximate)
            # TODO: source from social security authority. Source: {src_social}
            "social_contribution_rate": 0.0,

            # Pension contribution ceiling (annual, gross)
            "pension_ceiling": 0,

            # Additional locale-specific parameters
            # TODO: add country-specific fields (e.g. soli, AVS, cantonal rates)
        }}


        # ── 2025 ─────────────────────────────────────────────────────────────────

        _2025: dict = {{
            **_2024,           # Inherit 2024 as baseline — update changed values only
            "year": 2025,
            # TODO: override values that changed in 2025
        }}


        # ── 2026 ─────────────────────────────────────────────────────────────────

        _2026: dict = {{
            **_2025,           # Inherit 2025 as baseline — update changed values only
            "year": 2026,
            # TODO: override values that changed in 2026
        }}


        _RULES: dict[int, dict] = {{2024: _2024, 2025: _2025, 2026: _2026}}


        def get_tax_year_rules(year: int) -> dict:
            \"\"\"Return tax parameters for the given year. Raises KeyError for unsupported years.\"\"\"
            if year not in _RULES:
                raise KeyError(f"{{year}} is not in SUPPORTED_YEARS for {code_upper}. Add it to tax_rules.py.")
            return _RULES[year]
        """, dry_run=dry_run)

    # ── tax_calculator.py ────────────────────────────────────────────────────
    _write(target / "tax_calculator.py", f"""\
        \"\"\"
        Tax calculator for {locale_name} ({code_upper}).

        Implements the Finance Assistant locale plugin interface:
          calculate_tax(profile, year) -> dict
          get_tax_rules(year) -> dict

        Start by implementing calculate_tax() using the parameters in tax_rules.py.
        Add helper functions (e.g. _apply_brackets) as needed.
        \"\"\"

        from __future__ import annotations

        from .tax_rules import get_tax_year_rules


        def get_tax_rules(year: int) -> dict:
            \"\"\"Return raw tax parameters for the given year (plugin interface).\"\"\"
            return get_tax_year_rules(year)


        def calculate_tax(profile: dict, year: int) -> dict:
            \"\"\"
            Calculate full tax liability for the given profile and year.

            Args:
                profile: Finance Assistant user profile dict. Keys typically used:
                    income        (float) gross annual income
                    filing_status (str)   e.g. "single", "married_filing_jointly"
                    dependents    (int)   number of dependents
                year: Tax year to calculate for (must be in SUPPORTED_YEARS).

            Returns a dict with at least:
                gross    (float) gross income used for calculation
                tax      (float) income tax amount
                soli     (float) solidarity/surcharge (0.0 if not applicable)
                net      (float) net income after tax and soli
                currency (str)   "{currency}"
                year     (int)   tax year

            Add country-specific keys (e.g. ava, avs, cantonal_tax) as needed.
            \"\"\"
            rules = get_tax_year_rules(year)
            income = float(profile.get("income") or profile.get("gross_income") or 0)

            # TODO: implement proper tax calculation using rules
            # Example pattern (replace with real formula):
            taxable = max(0.0, income - rules.get("tax_free_allowance", 0) - rules.get("standard_deduction", 0))
            tax = _apply_brackets(taxable, rules.get("tax_brackets", []))

            return {{
                "gross": round(income, 2),
                "taxable_income": round(taxable, 2),
                "tax": round(tax, 2),
                "soli": 0.0,           # TODO: add if applicable
                "net": round(income - tax, 2),
                "currency": rules.get("currency", "{currency}"),
                "year": year,
                # TODO: add country-specific result keys
            }}


        def _apply_brackets(taxable_income: float, brackets: list[dict]) -> float:
            \"\"\"Apply progressive tax brackets to taxable income. Returns tax amount.\"\"\"
            tax = 0.0
            prev_upper = 0
            for bracket in brackets:
                rate = bracket.get("rate", 0)
                lower = bracket.get("from", prev_upper)
                upper = bracket.get("to")  # None = top bracket
                if taxable_income <= lower:
                    break
                chunk = (taxable_income - lower) if upper is None else min(taxable_income - lower, upper - lower)
                tax += chunk * rate
                if upper is None or taxable_income <= upper:
                    break
                prev_upper = upper
            return tax
        """, dry_run=dry_run)

    if not dry_run:
        print("\n✓ Scaffold complete.\n")

    # ── Validate_locale snippet ───────────────────────────────────────────────
    print(f"""\
Next steps:
  1. Fill in every TODO in locales/{code_lower}/ with real values.
     Primary source ({src_authority}):
       income tax: {src_income}
       social:     {src_social}
  2. Add this entry to scripts/validate_locale.py LOCALE_CONTRACTS:

    "{code_lower}": {{
        "module": "locales.{code_lower}",
        "function": "calculate_tax",
        "test_input": {{
            "profile": {{"income": 50000}},
            "year": 2025,
        }},
        "required_keys": ["gross", "tax", "soli", "net", "currency", "year"],
        "value_checks": {{
            "gross": {{"type": (int, float), "min": 0}},
            "tax":   {{"type": (int, float), "min": 0}},
            "net":   {{"type": (int, float), "min": 0}},
        }},
    }},

  3. Run: python3 scripts/validate_locale.py
  4. See CONTRIBUTING.md for PR checklist.
""")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Finance Assistant locale skeleton.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example: python3 scripts/scaffold_locale.py AT",
    )
    parser.add_argument("code", help="ISO 3166-1 alpha-2 locale code, e.g. AT, CH, CA")
    parser.add_argument("--locale-name", help="Human-readable country name (auto-detected for common codes)")
    parser.add_argument("--currency", help="ISO 4217 currency code (auto-detected for common codes)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be created without writing files")
    args = parser.parse_args()

    code = args.code.upper()
    default_name, default_currency = _DEFAULTS.get(code, (code, "EUR"))
    locale_name = args.locale_name or default_name
    currency = args.currency or default_currency

    generate(code, locale_name, currency, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
