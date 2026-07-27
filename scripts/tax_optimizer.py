# tax_optimizer.py
"""
Proactive year-round tax optimisation for Finance Assistant.

Analyses YTD income/spending, projects the full-year tax bill, and surfaces
ranked action items ("Do X before Dec 31 to save €Y").
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Imports – graceful fallbacks so the module is importable in isolation
# ---------------------------------------------------------------------------
try:
    from db import get_conn, get_db_path, init_db
except ImportError:  # pragma: no cover
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from db import get_conn, get_db_path, init_db

try:
    import tax_engine
except ImportError:  # pragma: no cover
    tax_engine = None  # type: ignore


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _current_year() -> int:
    return datetime.now().year


def _get_ytd_data(conn: sqlite3.Connection, year: int) -> dict:
    """
    Aggregate YTD figures from the transactions table for *year*.

    Returns a dict with:
      ytd_income, ytd_expenses, months_elapsed, ytd_charitable
    """
    year_prefix = f"{year}-%"

    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0)  AS ytd_income,
            COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0) AS ytd_expenses
        FROM transactions
        WHERE date LIKE ?
          AND type NOT IN ('transfer', 'investment', 'debt_payment')
        """,
        (year_prefix,),
    ).fetchone()

    ytd_income = float(row["ytd_income"]) if row else 0.0
    ytd_expenses = float(row["ytd_expenses"]) if row else 0.0

    # Months that have at least one transaction (Jan=1 … Dec=12)
    months_row = conn.execute(
        """
        SELECT COUNT(DISTINCT CAST(SUBSTR(date, 6, 2) AS INTEGER)) AS cnt
        FROM transactions
        WHERE date LIKE ?
        """,
        (year_prefix,),
    ).fetchone()
    months_elapsed = int(months_row["cnt"]) if months_row else 0

    # Charitable / donation transactions
    charitable_row = conn.execute(
        """
        SELECT COALESCE(SUM(ABS(amount)), 0) AS total
        FROM transactions
        WHERE date LIKE ?
          AND (LOWER(category) IN ('charitable', 'donation', 'charity'))
        """,
        (year_prefix,),
    ).fetchone()
    ytd_charitable = float(charitable_row["total"]) if charitable_row else 0.0

    return {
        "ytd_income": ytd_income,
        "ytd_expenses": ytd_expenses,
        "months_elapsed": months_elapsed,
        "ytd_charitable": ytd_charitable,
    }


def _get_locale(profile: dict) -> str:
    return (
        profile.get("tax_profile", {}).get("locale")
        or profile.get("meta", {}).get("locale")
        or "de"
    )


def _marginal_rate_estimate(projected_income: float) -> float:
    """
    Rough German marginal tax rate estimate for opportunity sizing.
    Returns a fraction (e.g. 0.32).
    """
    if projected_income <= 11_784:
        return 0.0
    if projected_income <= 17_005:
        return 0.14
    if projected_income <= 66_760:
        return 0.32
    if projected_income <= 277_825:
        return 0.42
    return 0.45


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def project_year_end_tax(profile: dict, year: int = None) -> dict:
    """
    Projects full-year tax based on YTD transactions.

    Returns a dict with projection details, or {"error": ..., "locale": ...}
    if the locale is unsupported or tax_engine fails.
    """
    year = year or _current_year()
    locale_code = _get_locale(profile)

    # Only DE implemented; other locales get a graceful error
    if locale_code not in ("de",):
        if tax_engine is None:
            return {"error": "tax_engine not available", "locale": locale_code}
        # Attempt via tax_engine for other locales
        try:
            result = tax_engine.calculate_tax_estimate(profile, year)
            if "error" in result:
                return result
        except Exception as exc:
            return {"error": str(exc), "locale": locale_code}

    # Pull YTD data from DB
    try:
        init_db()
        with get_conn() as conn:
            ytd = _get_ytd_data(conn, year)
    except Exception as exc:
        return {"error": f"DB error: {exc}", "locale": locale_code}

    months_elapsed = ytd["months_elapsed"]
    ytd_income = ytd["ytd_income"]

    # Annualise
    if months_elapsed > 0:
        projected_annual_income = ytd_income * (12.0 / months_elapsed)
    else:
        projected_annual_income = float(
            profile.get("employment", {}).get("annual_gross", 0) or 0
        )

    # Confidence band
    if months_elapsed < 3:
        confidence = "low"
    elif months_elapsed < 9:
        confidence = "medium"
    else:
        confidence = "high"

    # Build an augmented profile with projected income for tax calculation
    augmented = _deep_copy_profile(profile)
    augmented.setdefault("employment", {})["annual_gross"] = projected_annual_income

    projected_tax = None
    projected_refund_or_liability = None

    if tax_engine is not None:
        try:
            tax_result = tax_engine.calculate_tax_estimate(augmented, year)
            if "error" not in tax_result:
                details = tax_result.get("details", tax_result)
                projected_tax = details.get("total_tax_due") or tax_result.get("estimated_tax")
                refund = details.get("estimated_refund") or tax_result.get("estimated_refund")
                projected_refund_or_liability = refund
        except Exception:
            pass

    months_remaining = 12 - months_elapsed

    return {
        "year": year,
        "locale": locale_code,
        "months_elapsed": months_elapsed,
        "months_remaining": months_remaining,
        "ytd_income": round(ytd_income, 2),
        "projected_annual_income": round(projected_annual_income, 2),
        "projected_tax": round(projected_tax, 2) if projected_tax is not None else None,
        "projected_refund_or_liability": (
            round(projected_refund_or_liability, 2)
            if projected_refund_or_liability is not None
            else None
        ),
        "confidence": confidence,
        "note": (
            f"Based on {months_elapsed} month(s) of data. "
            "Projection assumes current income pace continues."
        ),
    }


def get_de_opportunities(profile: dict, ytd_data: dict, year: int) -> list[dict]:
    """
    German-specific tax optimisation opportunities.

    ytd_data must contain: ytd_income, months_elapsed,
    ytd_homeoffice_days (optional), ytd_charitable.
    """
    opportunities: list[dict] = []

    ytd_income: float = ytd_data.get("ytd_income", 0.0)
    months_elapsed: int = ytd_data.get("months_elapsed", 0)
    ytd_charitable: float = ytd_data.get("ytd_charitable", 0.0)

    # Project annual income
    if months_elapsed > 0:
        projected_income = ytd_income * (12.0 / months_elapsed)
    else:
        projected_income = float(
            profile.get("employment", {}).get("annual_gross", 0) or 0
        )

    marginal = _marginal_rate_estimate(projected_income)
    months_remaining = 12 - months_elapsed
    deadline = f"December 31, {year}"
    tax_extra = profile.get("tax_profile", {}).get("extra", {})
    housing = profile.get("housing", {})

    # ------------------------------------------------------------------
    # 1. Homeoffice-Pauschale  (§4 Abs.5 EStG)  €6/day, max 210 days
    # ------------------------------------------------------------------
    HO_MAX_DAYS = 210
    HO_RATE = 6
    ho_days_pw = housing.get("homeoffice_days_per_week") or tax_extra.get("homeoffice_days_per_week")
    ytd_ho_days: int = ytd_data.get("ytd_homeoffice_days", 0)

    if ho_days_pw is not None:
        # Project annual days (46 working weeks as per DE tax_calculator logic)
        projected_annual_days = min(int(float(ho_days_pw) * 46), HO_MAX_DAYS)
        remaining_days = max(0, HO_MAX_DAYS - projected_annual_days)
        if remaining_days > 0 and months_remaining > 0:
            extra_saving = remaining_days * HO_RATE * marginal
            if extra_saving >= 50:
                opportunities.append({
                    "action": (
                        f"Log additional homeoffice days — you have {remaining_days} "
                        f"remaining days claimable at €{HO_RATE}/day"
                    ),
                    "category": "homeoffice",
                    "potential_tax_saving": round(extra_saving, 2),
                    "max_deductible_amount": round(remaining_days * HO_RATE, 2),
                    "deadline": deadline,
                    "effort": "low",
                    "detail": (
                        "§4 Abs.5 Nr.6b EStG: up to 210 homeoffice days per year at €6/day "
                        f"(€{HO_MAX_DAYS * HO_RATE} annual cap). "
                        "Keep a record of days worked from home."
                    ),
                    "confidence": "definitive",
                })
    elif ytd_ho_days > 0:
        remaining_days = max(0, HO_MAX_DAYS - ytd_ho_days)
        if remaining_days > 0:
            extra_saving = remaining_days * HO_RATE * marginal
            if extra_saving >= 50:
                opportunities.append({
                    "action": (
                        f"Log remaining homeoffice days ({remaining_days} days left "
                        f"at €{HO_RATE}/day)"
                    ),
                    "category": "homeoffice",
                    "potential_tax_saving": round(extra_saving, 2),
                    "max_deductible_amount": round(remaining_days * HO_RATE, 2),
                    "deadline": deadline,
                    "effort": "low",
                    "detail": "§4 Abs.5 Nr.6b EStG: 210 days × €6 = €1,260 annual cap.",
                    "confidence": "likely",
                })

    # ------------------------------------------------------------------
    # 2. Riester  (§10a EStG)  — max €2,100/year
    # ------------------------------------------------------------------
    RIESTER_MAX = 2_100
    RIESTER_BASIC_ALLOWANCE = 175  # automatically deducted, reduces effective gap
    riester_contribution = float(tax_extra.get("riester_contribution", 0) or 0)
    has_riester = bool(tax_extra.get("riester", False))

    if has_riester or riester_contribution > 0:
        gap = max(0.0, RIESTER_MAX - riester_contribution)
        if gap >= 1:
            saving = gap * marginal
            if saving >= 50:
                opportunities.append({
                    "action": f"Increase Riester contribution to annual maximum (€{RIESTER_MAX:,})",
                    "category": "retirement",
                    "potential_tax_saving": round(saving, 2),
                    "max_deductible_amount": round(gap, 2),
                    "deadline": deadline,
                    "effort": "low",
                    "detail": (
                        f"§10a EStG: up to €{RIESTER_MAX:,}/year deductible as Sonderausgaben. "
                        f"Basic allowance of €{RIESTER_BASIC_ALLOWANCE} already counts toward cap. "
                        "Contact your Riester provider to increase contributions."
                    ),
                    "confidence": "definitive",
                })
    else:
        # No Riester — suggest opening one
        potential_saving = RIESTER_MAX * marginal
        if potential_saving >= 50:
            opportunities.append({
                "action": "Open a Riester-Rente and contribute up to €2,100 this year",
                "category": "retirement",
                "potential_tax_saving": round(potential_saving, 2),
                "max_deductible_amount": float(RIESTER_MAX),
                "deadline": deadline,
                "effort": "medium",
                "detail": (
                    "§10a EStG: employed taxpayers can deduct up to €2,100/year. "
                    "State allowance (€175 basic + child allowances) reduce required own contribution."
                ),
                "confidence": "likely",
            })

    # ------------------------------------------------------------------
    # 3. Rürup / Basis-Rente  (§10 EStG)
    # ------------------------------------------------------------------
    family_status = profile.get("family", {}).get("status", "single")
    married = family_status in ("married", "verheiratet")
    RUERUP_MAX_SINGLE = 27_566  # 2025 baseline; exact cap varies by year
    ruerup_max = RUERUP_MAX_SINGLE * 2 if married else RUERUP_MAX_SINGLE
    ruerup_contribution = float(tax_extra.get("ruerup_contribution", 0) or 0)
    has_ruerup = bool(tax_extra.get("ruerup", False))

    if projected_income > 50_000:
        gap = max(0.0, ruerup_max - ruerup_contribution)
        if gap >= 1:
            saving = gap * marginal
            if saving >= 50:
                opportunities.append({
                    "action": (
                        f"Contribute to Rürup/Basis-Rente — up to "
                        f"€{ruerup_max:,} deductible this year"
                    ),
                    "category": "retirement",
                    "potential_tax_saving": round(saving, 2),
                    "max_deductible_amount": round(gap, 2),
                    "deadline": deadline,
                    "effort": "medium",
                    "detail": (
                        f"§10 EStG: Basisrente contributions up to €{ruerup_max:,} "
                        f"({'married' if married else 'single'}) are deductible. "
                        "High earners benefit most. Funds are locked until retirement."
                    ),
                    "confidence": "definitive" if has_ruerup else "likely",
                })

    # ------------------------------------------------------------------
    # 4. Charitable donations  (§10b EStG)  — up to 20% of income
    # ------------------------------------------------------------------
    CHARITABLE_CAP_FRACTION = 0.20
    LOW_EFFORT_THRESHOLD_FRACTION = 0.05

    charitable_cap = projected_income * CHARITABLE_CAP_FRACTION
    charitable_gap = max(0.0, charitable_cap - ytd_charitable)
    if charitable_gap >= 1:
        low_effort_threshold = projected_income * LOW_EFFORT_THRESHOLD_FRACTION
        is_low_effort = ytd_charitable < low_effort_threshold
        saving = charitable_gap * marginal
        if saving >= 50:
            opportunities.append({
                "action": (
                    f"Make charitable donations — up to €{charitable_gap:,.0f} "
                    "more deductible this year"
                ),
                "category": "charitable",
                "potential_tax_saving": round(saving, 2),
                "max_deductible_amount": round(charitable_gap, 2),
                "deadline": deadline,
                "effort": "low" if is_low_effort else "medium",
                "detail": (
                    "§10b EStG: up to 20% of income deductible as Sonderausgaben. "
                    "Requires Zuwendungsbestätigung from recipient organisation."
                ),
                "confidence": "definitive",
            })

    # ------------------------------------------------------------------
    # 5. Arbeitsmittel / work equipment  (§9 EStG)
    # ------------------------------------------------------------------
    ARBEITNEHMER_PAUSCHBETRAG = 1_230
    ytd_work_expenses = float(ytd_data.get("ytd_work_expenses", 0) or 0)

    if ytd_work_expenses < ARBEITNEHMER_PAUSCHBETRAG and months_remaining > 0:
        gap = ARBEITNEHMER_PAUSCHBETRAG - ytd_work_expenses
        saving = gap * marginal
        if saving >= 50:
            opportunities.append({
                "action": (
                    f"Purchase work equipment before year-end to exceed the "
                    f"€{ARBEITNEHMER_PAUSCHBETRAG:,} Arbeitnehmer-Pauschbetrag"
                ),
                "category": "training",
                "potential_tax_saving": round(saving, 2),
                "max_deductible_amount": round(gap, 2),
                "deadline": deadline,
                "effort": "medium",
                "detail": (
                    "§9 EStG: work equipment (laptop, books, desk accessories) is fully "
                    f"deductible above the €{ARBEITNEHMER_PAUSCHBETRAG:,} flat deduction. "
                    "Keep receipts."
                ),
                "confidence": "likely",
            })

    # Sort by potential saving (highest first)
    opportunities.sort(key=lambda o: o["potential_tax_saving"], reverse=True)
    return opportunities


def get_optimization_opportunities(profile: dict, year: int = None) -> list[dict]:
    """
    Returns ranked list of tax optimisation opportunities for the given profile.
    Currently only implements DE; all other locales return [].
    """
    year = year or _current_year()
    locale_code = _get_locale(profile)

    if locale_code != "de":
        return []

    try:
        init_db()
        with get_conn() as conn:
            ytd_data = _get_ytd_data(conn, year)
    except Exception:
        ytd_data = {
            "ytd_income": float(profile.get("employment", {}).get("annual_gross", 0) or 0),
            "ytd_expenses": 0.0,
            "months_elapsed": 0,
            "ytd_charitable": 0.0,
        }

    # Merge homeoffice days from profile into ytd_data if available
    housing = profile.get("housing", {})
    tax_extra = profile.get("tax_profile", {}).get("extra", {})
    ho_days_pw = housing.get("homeoffice_days_per_week") or tax_extra.get("homeoffice_days_per_week")
    months_elapsed = ytd_data["months_elapsed"]
    if ho_days_pw is not None and months_elapsed > 0:
        ytd_data["ytd_homeoffice_days"] = int(float(ho_days_pw) * (months_elapsed * 46 / 12))
    else:
        ytd_data["ytd_homeoffice_days"] = ytd_data.get("ytd_homeoffice_days", 0)

    return get_de_opportunities(profile, ytd_data, year)


def get_tax_action_summary(profile: dict, year: int = None) -> str:
    """
    Returns a formatted plain-text summary of the tax outlook and top actions.
    """
    year = year or _current_year()
    locale_code = _get_locale(profile)

    projection = project_year_end_tax(profile, year)
    if "error" in projection:
        return (
            f"Tax projection unavailable for locale '{locale_code}': "
            f"{projection['error']}"
        )

    months_elapsed = projection.get("months_elapsed", 0)
    if months_elapsed == 0:
        return (
            f"Tax outlook for {year}: no transaction data found yet. "
            "Add income and expense transactions to get a projection."
        )

    refund = projection.get("projected_refund_or_liability")
    refund_str = (
        f"~€{abs(refund):,.0f} {'refund' if refund >= 0 else 'liability'}"
        if refund is not None
        else "unknown"
    )

    lines: list[str] = [
        f"Tax outlook for {year} ({months_elapsed} month(s) elapsed):",
        f"Projected {'refund' if (refund or 0) >= 0 else 'liability'}: {refund_str} at current pace",
        "",
        "Top actions before Dec 31:",
    ]

    opportunities = get_optimization_opportunities(profile, year)
    if not opportunities:
        lines.append("  No further optimisation opportunities identified.")
    else:
        total_saving = 0.0
        for i, opp in enumerate(opportunities[:5], 1):
            saving = opp["potential_tax_saving"]
            total_saving += saving
            conf = opp["confidence"]
            lines.append(
                f"  {i}. {opp['action']} → save ~€{saving:,.0f} ({conf} confidence)"
            )
        lines.append("")
        lines.append(f"Total potential additional refund: ~€{total_saving:,.0f}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------

def _deep_copy_profile(profile: dict) -> dict:
    """Shallow-copies the top-level profile dict and its first-level sub-dicts."""
    result = {}
    for k, v in profile.items():
        result[k] = dict(v) if isinstance(v, dict) else v
    return result
