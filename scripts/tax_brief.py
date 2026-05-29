"""
Accountant / Steuerberater filing brief.

Produces a focused, hand-off-ready document for a tax professional: the computed
tax estimate with the actual rules applied, the deduction claims, an income
summary, and a checklist of source documents the user needs to gather.

Distinct from annual_summary.py (which is a broad year-in-review across budgets,
investments, donations). This is narrowly the "give this to your accountant
before filing" artifact.

Usage:
    python3 skill.py --tax-brief [--year 2025]
Writes markdown to .finance/workspace/tax_brief_<locale>_<year>.md
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

try:
    from finance_storage import ensure_subdir, save_json
    from currency import format_money
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import ensure_subdir
    try:
        from currency import format_money
    except ImportError:
        def format_money(amount, currency="EUR"):
            return f"{amount:,.2f} {currency}"


def build_brief(profile: Optional[dict] = None, year: Optional[int] = None) -> dict:
    """Assemble the filing-brief data from the tax engine. Never raises."""
    try:
        from tax_engine import (
            calculate_tax_estimate, generate_tax_claims, get_tax_rules,
            get_tax_deadlines, get_active_locale,
        )
        from profile_manager import get_profile
    except ImportError:
        import os, sys
        sys.path.insert(0, os.path.dirname(__file__))
        from tax_engine import (
            calculate_tax_estimate, generate_tax_claims, get_tax_rules,
            get_tax_deadlines, get_active_locale,
        )
        from profile_manager import get_profile

    profile = profile or get_profile() or {}
    year = year or profile.get("meta", {}).get("tax_year", date.today().year - 1)

    estimate = calculate_tax_estimate(profile, year)
    claims = generate_tax_claims(profile, year, persist=False)
    try:
        rules = get_tax_rules(profile, year)
    except Exception:
        rules = {}
    try:
        deadlines = get_tax_deadlines(profile, year)
    except Exception:
        deadlines = []

    locale = estimate.get("locale", get_active_locale())
    return {
        "locale": locale,
        "locale_name": estimate.get("locale_name", locale.upper()),
        "year": year,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "estimate": estimate,
        "claims": claims.get("claims", []) if isinstance(claims, dict) else [],
        "rules": rules,
        "deadlines": deadlines,
        "error": estimate.get("error"),
    }


def _first(*vals):
    """Return the first value that is a non-zero number, else None."""
    for v in vals:
        try:
            if v is not None and float(v) != 0:
                return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _extract_amounts(est: dict) -> dict:
    """Normalize the wildly different locale return shapes into common rows.

    Locales don't share a key schema: DE nests everything under `breakdown`
    (estimated_tax, zu_versteuerndes_einkommen, soli); US returns flat keys
    (federal_income_tax, gross_income, social_security_tax + medicare_tax).
    This maps whatever's present into a labelled, ordered list of rows.
    """
    b = est.get("breakdown", {}) if isinstance(est.get("breakdown"), dict) else {}

    gross = _first(est.get("gross"), est.get("gross_income"), b.get("gross_income"))
    taxable = _first(est.get("taxable_income"), b.get("zu_versteuerndes_einkommen"), b.get("taxable_income"))
    income_tax = _first(est.get("tax"), est.get("federal_income_tax"), b.get("estimated_tax"), b.get("income_tax"))
    soli = _first(est.get("soli"), b.get("soli"))
    # US splits social into SS + Medicare; DE has social contributions in breakdown
    social = _first(
        est.get("social"),
        b.get("social_contributions"),
        (float(est.get("social_security_tax", 0) or 0) + float(est.get("medicare_tax", 0) or 0)) or None,
    )
    se_tax = _first(est.get("self_employment_tax"))
    qbi = _first(est.get("qbi_deduction"))
    net = _first(est.get("net"), b.get("net"))
    if net is None and gross is not None and income_tax is not None:
        net = gross - income_tax

    rows = []
    if gross is not None:    rows.append(("Gross income", gross))
    if taxable is not None:  rows.append(("Taxable income", taxable))
    if income_tax is not None: rows.append(("Income tax", income_tax))
    if soli is not None:     rows.append(("Solidarity surcharge", soli))
    if se_tax is not None:   rows.append(("Self-employment tax", se_tax))
    if qbi is not None:      rows.append(("§199A QBI deduction", qbi))
    if social is not None:   rows.append(("Social contributions", social))
    if net is not None:      rows.append(("Net (after income tax)", net))

    er = est.get("effective_rate")
    effective_rate = None
    if er is not None:
        try:
            er = float(er)
            effective_rate = er * 100 if er <= 1 else er  # fraction → percent
        except (TypeError, ValueError):
            pass

    return {"rows": rows, "effective_rate": effective_rate}


def render_markdown(brief: dict) -> str:
    """Render the brief as a hand-off markdown document."""
    if brief.get("error"):
        return (
            f"# Tax Filing Brief — error\n\n"
            f"Could not compute: {brief['error']}\n\n"
            f"Locale '{brief.get('locale')}' may not be implemented. "
            f"Available: DE, FR, NL, PL, UK, US."
        )

    est = brief["estimate"]
    cur = est.get("currency", "EUR")
    L = []
    L.append(f"# Tax Filing Brief — {brief['locale_name']} {brief['year']}")
    L.append("")
    L.append(f"*Prepared {brief['generated_at'][:10]} by Finance Assistant for hand-off to a tax professional.*")
    L.append("")
    L.append("> **This is an estimate, not a filing.** The numbers below apply published "
             "statutory rules to the figures on record. Confirm every input with your "
             "advisor before filing — especially deductions, which depend on documentation.")
    L.append("")

    # ── Computed estimate ──
    amounts = _extract_amounts(est)
    L.append("## Computed tax estimate")
    L.append("")
    L.append("| Item | Amount |")
    L.append("|------|-------:|")
    for label, val in amounts["rows"]:
        L.append(f"| {label} | {format_money(float(val), cur)} |")
    if amounts["effective_rate"] is not None:
        L.append(f"| Effective rate | {amounts['effective_rate']:.1f}% |")
    if not amounts["rows"]:
        L.append("| _no figures on record — add income/employment to your profile_ | |")
    L.append("")

    # ── Rules applied (the "real law" provenance) ──
    rules = brief.get("rules") or {}
    if rules:
        L.append("## Statutory rules applied")
        L.append("")
        L.append(f"Locale plugin: `locales/{brief['locale']}/` · tax year {brief['year']}")
        L.append("")
        if rules.get("tax_free_allowance"):
            L.append(f"- Tax-free allowance: {format_money(float(rules['tax_free_allowance']), cur)}")
        brackets = rules.get("tax_brackets") or []
        if brackets:
            L.append("- Brackets:")
            for b in brackets:
                hi = "and up" if b.get("to") is None else f"to {format_money(float(b['to']), cur)}"
                L.append(f"  - {b.get('rate', 0) * 100:.0f}% from {format_money(float(b.get('from', 0)), cur)} {hi}")
        L.append("")

    # ── Deduction claims ──
    claims = brief.get("claims", [])
    L.append("## Deduction claims to discuss")
    L.append("")
    if claims:
        L.append("| Claim | Est. amount | Needs documentation |")
        L.append("|-------|------------:|---------------------|")
        for c in claims:
            name = c.get("label") or c.get("category") or c.get("name", "Claim")
            amt = c.get("amount", c.get("estimated_amount", 0))
            doc = c.get("documentation", c.get("evidence", "receipt / statement"))
            L.append(f"| {name} | {format_money(float(amt or 0), cur)} | {doc} |")
    else:
        L.append("_No deduction claims detected. Discuss with your advisor whether any apply._")
    L.append("")

    # ── Document checklist ──
    L.append("## Documents to gather before your appointment")
    L.append("")
    checklist = [
        "Annual income statement(s) (employer / clients)",
        "Bank statements for the full tax year",
        "Receipts for every deduction claimed above",
        "Investment income statements (dividends, interest, capital gains)",
        "Records of any tax already paid or withheld (prepayments, PAYE/withholding)",
    ]
    if brief["locale"] == "de":
        checklist += ["Lohnsteuerbescheinigung", "Spendenquittungen (donation receipts)"]
    elif brief["locale"] == "us":
        checklist += ["W-2 / 1099 forms", "Form 1098 (mortgage interest) if applicable"]
    elif brief["locale"] == "uk":
        checklist += ["P60 / P45", "Records of any Gift Aid donations"]
    for item in checklist:
        L.append(f"- [ ] {item}")
    L.append("")

    # ── Deadlines ──
    deadlines = brief.get("deadlines", [])
    if deadlines:
        L.append("## Filing deadlines")
        L.append("")
        for d in deadlines:
            L.append(f"- **{d.get('label', 'Deadline')}**: {d.get('deadline', '?')}")
        L.append("")

    L.append("---")
    L.append("*Generated locally by Finance Assistant. No data left your machine to produce this.*")
    return "\n".join(L)


def generate(profile: Optional[dict] = None, year: Optional[int] = None) -> str:
    """Build + render + write the brief. Returns the output file path."""
    brief = build_brief(profile, year)
    md = render_markdown(brief)
    out = ensure_subdir("workspace") / f"tax_brief_{brief['locale']}_{brief['year']}.md"
    out.write_text(md, encoding="utf-8")
    return str(out)
