"""
Finance Assistant Scenario Engine.

Expanded from TaxDE scenario_engine.py with new financial scenarios:
salary packages, freelance break-even, mortgage comparisons, FIRE projections,
debt-vs-invest, and rent-vs-buy.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Optional

try:
    from profile_manager import get_profile
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from profile_manager import get_profile


# ── Salary Package Comparison (from TaxDE) ───────────────────────────────────

def compare_salary_packages(
    packages: list[dict],
    profile: Optional[dict] = None,
    projection_years: int = 3,
    annual_raise_pct: float = 0.0,
) -> dict:
    """Compare employment packages with multi-year projections."""
    if not packages:
        return {"packages": [], "best_option": None}

    evaluations = []
    for pkg in packages:
        gross = float(pkg.get("annual_gross", 0))
        benefits = float(pkg.get("benefits_value", 0))
        bav = float(pkg.get("bav_contribution", 0))

        try:
            from tax_engine import get_tax_summary
            _pkg_profile = deepcopy(profile or get_profile() or {})
            _pkg_profile.setdefault("employment", {})["annual_gross"] = gross
            _s = get_tax_summary(_pkg_profile, datetime.now().year)
            if _s.get("source") == "engine" and _s.get("net") is not None:
                net = _s["net"] + benefits - bav * 0.5
                _tax_note = _s["components"]
            else:
                raise ValueError(_s.get("error", "no result"))
        except Exception:
            net = gross * (1 - 0.25 - 0.20) + benefits - bav * 0.5
            _tax_note = "estimated (25% income tax + 20% social — set a locale for precise tax)"

        projections = []
        for yr in range(projection_years):
            factor = (1 + annual_raise_pct) ** yr
            projections.append({
                "year": yr + 1,
                "annual_gross": round(gross * factor, 2),
                "estimated_annual_net": round(net * factor, 2),
            })

        evaluations.append({
            "label": pkg.get("label", f"Package {len(evaluations) + 1}"),
            "annual_gross": gross,
            "estimated_annual_net": round(net, 2),
            "estimated_monthly_net": round(net / 12, 2),
            "projections": projections,
            "multi_year_net_total": round(sum(p["estimated_annual_net"] for p in projections), 2),
            "tax_note": _tax_note,
        })

    best = max(evaluations, key=lambda e: e["estimated_annual_net"])
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "packages": evaluations,
        "best_option": best,
        "projection_years": projection_years,
        "note": "Net figures use locale-specific tax rules where available. Use the tax module for a precise breakdown.",
    }


# ── Mortgage Comparison ──────────────────────────────────────────────────────

def compare_mortgage_options(options: list[dict]) -> dict:
    """Compare mortgage offers with total cost analysis."""
    evaluations = []
    for opt in options:
        amount = float(opt.get("loan_amount", 0))
        rate = float(opt.get("interest_rate", 0)) / 100
        years = int(opt.get("term_years", 30))
        monthly_rate = rate / 12
        months = years * 12

        if monthly_rate > 0:
            payment = amount * monthly_rate / (1 - (1 + monthly_rate) ** -months)
        else:
            payment = amount / months

        total_paid = payment * months
        total_interest = total_paid - amount

        evaluations.append({
            "label": opt.get("label", f"Option {len(evaluations) + 1}"),
            "loan_amount": amount,
            "interest_rate": float(opt.get("interest_rate", 0)),
            "term_years": years,
            "monthly_payment": round(payment, 2),
            "total_paid": round(total_paid, 2),
            "total_interest": round(total_interest, 2),
        })

    best = min(evaluations, key=lambda e: e["total_interest"]) if evaluations else None
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "options": evaluations,
        "best_option": best,
    }


# ── FIRE Projection ─────────────────────────────────────────────────────────

def project_fire_timeline(
    current_savings: float,
    monthly_contribution: float,
    annual_expenses: float,
    annual_return_pct: float = 0.07,
    withdrawal_rate: float = 0.04,
    inflation_rate: float = 0.02,
    real: bool = True,
) -> dict:
    """Project timeline to financial independence.

    When real=True (default), uses the real return rate (nominal return adjusted
    for inflation) so that projections reflect actual purchasing power rather than
    nominal growth. Over 25 years at 7% nominal / 2% inflation, using nominal
    returns would overstate real purchasing power by ~64%.

    real_return = (1 + annual_return_pct) / (1 + inflation_rate) - 1
    """
    fire_number = annual_expenses / withdrawal_rate
    if real:
        real_return = (1 + annual_return_pct) / (1 + inflation_rate) - 1
    else:
        real_return = annual_return_pct
    monthly_return = real_return / 12
    balance = current_savings
    months = 0
    max_months = 12 * 60  # 60 year cap

    milestones = []
    while balance < fire_number and months < max_months:
        months += 1
        balance = balance * (1 + monthly_return) + monthly_contribution
        if months % 12 == 0:
            milestones.append({"year": months // 12, "balance": round(balance, 2)})

    years = months / 12
    return {
        "fire_number": round(fire_number, 2),
        "current_savings": current_savings,
        "monthly_contribution": monthly_contribution,
        "years_to_fire": round(years, 1),
        "months_to_fire": months,
        "annual_expenses": annual_expenses,
        "withdrawal_rate": withdrawal_rate,
        "annual_return_pct": annual_return_pct,
        "inflation_rate": inflation_rate,
        "real_return_used": round(real_return, 6),
        "milestones": milestones,
        "achievable": months < max_months,
    }


# ── Debt vs Invest ───────────────────────────────────────────────────────────

def compare_debt_payoff_vs_invest(
    debt_balance: float,
    debt_rate: float,
    investment_return: float,
    monthly_available: float,
    years: int = 10,
) -> dict:
    """Compare paying off debt faster vs investing the extra money."""
    monthly_debt_rate = debt_rate / 100 / 12
    monthly_invest_rate = investment_return / 100 / 12

    # Scenario A: Pay off debt, then invest
    debt_bal = debt_balance
    months_to_payoff = 0
    total_debt_interest_a = 0.0
    while debt_bal > 0 and months_to_payoff < years * 12:
        months_to_payoff += 1
        interest = debt_bal * monthly_debt_rate
        total_debt_interest_a += interest
        debt_bal = debt_bal + interest - monthly_available
        if debt_bal < 0:
            debt_bal = 0

    invest_months_a = max(0, years * 12 - months_to_payoff)
    invest_balance_a = 0.0
    for _ in range(invest_months_a):
        invest_balance_a = invest_balance_a * (1 + monthly_invest_rate) + monthly_available

    # Scenario B: Minimum debt payments, invest the rest
    min_payment = debt_balance * 0.02  # Assume 2% minimum
    invest_extra = max(0, monthly_available - min_payment)
    debt_bal_b = debt_balance
    invest_balance_b = 0.0
    total_debt_interest_b = 0.0
    for _ in range(years * 12):
        # Debt
        interest = debt_bal_b * monthly_debt_rate
        total_debt_interest_b += interest
        debt_bal_b = max(0, debt_bal_b + interest - min_payment)
        # Invest
        invest_balance_b = invest_balance_b * (1 + monthly_invest_rate) + invest_extra

    net_a = invest_balance_a - total_debt_interest_a
    # net_b was subtracting BOTH the remaining principal (debt_bal_b) and the
    # cumulative interest ever charged (total_debt_interest_b) — but
    # debt_bal_b's growth already bakes in that accrued interest each month
    # (debt_bal_b += interest - min_payment), so subtracting both double-
    # counted the cost of debt and systematically biased the comparison
    # toward "pay debt first".
    net_b = invest_balance_b - debt_bal_b

    return {
        "pay_debt_first": {
            "months_to_payoff": months_to_payoff,
            "total_debt_interest": round(total_debt_interest_a, 2),
            "investment_balance": round(invest_balance_a, 2),
            "net_position": round(net_a, 2),
        },
        "invest_while_paying_minimum": {
            "remaining_debt": round(debt_bal_b, 2),
            "total_debt_interest": round(total_debt_interest_b, 2),
            "investment_balance": round(invest_balance_b, 2),
            "net_position": round(net_b, 2),
        },
        "recommendation": "pay_debt_first" if net_a > net_b else "invest",
        "difference": round(abs(net_a - net_b), 2),
        "note": "This is a simplified model. Tax implications and risk tolerance matter.",
    }


# ── Rent vs Buy ──────────────────────────────────────────────────────────────

def compare_rent_vs_buy(
    monthly_rent: float,
    home_price: float,
    down_payment: float,
    mortgage_rate: float,
    years: int = 30,
    property_tax_rate: float = 0.01,
    maintenance_rate: float = 0.01,
    rent_increase: float = 0.02,
    home_appreciation: float = 0.03,
    investment_return: float = 0.07,
) -> dict:
    """Compare renting vs buying over a given period."""
    loan = home_price - down_payment
    monthly_mortgage_rate = mortgage_rate / 100 / 12
    months = years * 12

    if monthly_mortgage_rate > 0:
        mortgage_payment = loan * monthly_mortgage_rate / (1 - (1 + monthly_mortgage_rate) ** -months)
    else:
        mortgage_payment = loan / months

    # Buying costs
    total_mortgage = mortgage_payment * months
    total_property_tax = home_price * property_tax_rate * years
    total_maintenance = home_price * maintenance_rate * years
    total_buy_cost = down_payment + total_mortgage + total_property_tax + total_maintenance
    future_home_value = home_price * ((1 + home_appreciation) ** years)
    buy_net = future_home_value - total_buy_cost

    # Renting costs + investing the difference
    total_rent = 0
    invest_balance = down_payment  # Invest the down payment instead
    monthly_invest_rate = investment_return / 12
    current_rent = monthly_rent

    for yr in range(years):
        for _ in range(12):
            total_rent += current_rent
            monthly_savings = (
                mortgage_payment
                + (home_price * property_tax_rate / 12)
                + (home_price * maintenance_rate / 12)  # a renter avoids maintenance too — was omitted
                - current_rent
            )
            if monthly_savings > 0:
                invest_balance = invest_balance * (1 + monthly_invest_rate) + monthly_savings
            else:
                invest_balance = invest_balance * (1 + monthly_invest_rate)
        current_rent *= (1 + rent_increase)

    rent_net = invest_balance - total_rent

    return {
        "buy": {
            "down_payment": down_payment,
            "monthly_mortgage": round(mortgage_payment, 2),
            "total_cost": round(total_buy_cost, 2),
            "future_home_value": round(future_home_value, 2),
            "net_position": round(buy_net, 2),
        },
        "rent": {
            "starting_monthly_rent": monthly_rent,
            "total_rent_paid": round(total_rent, 2),
            "investment_balance": round(invest_balance, 2),
            "net_position": round(rent_net, 2),
        },
        "recommendation": "buy" if buy_net > rent_net else "rent",
        "difference": round(abs(buy_net - rent_net), 2),
        "years": years,
        "assumptions": {
            "mortgage_rate": mortgage_rate,
            "rent_increase": f"{rent_increase*100:.0f}%/year",
            "home_appreciation": f"{home_appreciation*100:.0f}%/year",
            "investment_return": f"{investment_return*100:.0f}%/year",
        },
    }


# ── Freelance vs Employment ──────────────────────────────────────────────────

def compare_freelance_vs_employment(
    employed_gross: float,
    freelance_daily_rate: float,
    billable_days_per_year: int = 220,
    freelance_monthly_expenses: float = 500.0,
    profile: Optional[dict] = None,
) -> dict:
    """Compare staying employed vs going freelance.

    Calculates net income for both scenarios using locale-specific tax rules
    where available, falling back to conservative estimates. Identifies the
    break-even daily rate and billable-days threshold.

    Args:
        employed_gross: Current annual gross salary.
        freelance_daily_rate: Target daily rate as a freelancer.
        billable_days_per_year: Expected billable days (default 220, ~85% of working days).
        freelance_monthly_expenses: Monthly business overhead (software, desk, accountant).
        profile: Finance profile dict. Loaded automatically if not passed.
    """
    profile = profile or get_profile() or {}

    def _net_for_gross(annual_gross: float, employment_type: str = "employed") -> tuple[float, str]:
        """Return (net, note) using the real tax engine, or a flat estimate."""
        try:
            from tax_engine import get_tax_summary
            p = deepcopy(profile)
            p.setdefault("employment", {})["annual_gross"] = annual_gross
            p["employment"]["type"] = employment_type
            p.setdefault("tax_profile", {})  # locale resolved inside the engine
            s = get_tax_summary(p, datetime.now().year)
            if s.get("source") == "engine" and s.get("net") is not None:
                return s["net"], s["components"]
        except Exception:
            pass
        # Fallback: employed ~45% combined, freelance ~40% (no employer social top-up)
        rate = 0.45 if employment_type == "employed" else 0.40
        return annual_gross * (1 - rate), "estimated (~40–45% combined tax + social — set a locale for precision)"

    # Employment scenario
    employed_net, emp_note = _net_for_gross(employed_gross, "employed")

    # Freelance scenario
    freelance_gross_revenue = freelance_daily_rate * billable_days_per_year
    annual_expenses = freelance_monthly_expenses * 12
    freelance_taxable = max(0.0, freelance_gross_revenue - annual_expenses)
    freelance_net_before_expenses, fl_note = _net_for_gross(freelance_taxable, "freelance")
    # Net after deducting expenses (expenses already reduce taxable income, so net is from taxable)
    freelance_net = freelance_net_before_expenses

    # Break-even: minimum daily rate to match employed net
    # Solve: (rate * days - annual_expenses) * (1 - effective_rate) = employed_net
    effective_rate = 0.40  # conservative freelance estimate
    breakeven_rate = (employed_net / (1 - effective_rate) + annual_expenses) / billable_days_per_year
    breakeven_days = max(1, int(
        (employed_net / (1 - effective_rate) + annual_expenses) / freelance_daily_rate
    ))

    net_advantage = freelance_net - employed_net
    advantage_monthly = net_advantage / 12

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "employment": {
            "annual_gross": employed_gross,
            "estimated_annual_net": round(employed_net, 2),
            "estimated_monthly_net": round(employed_net / 12, 2),
            "tax_note": emp_note,
        },
        "freelance": {
            "daily_rate": freelance_daily_rate,
            "billable_days": billable_days_per_year,
            "annual_gross_revenue": round(freelance_gross_revenue, 2),
            "annual_business_expenses": round(annual_expenses, 2),
            "taxable_income": round(freelance_taxable, 2),
            "estimated_annual_net": round(freelance_net, 2),
            "estimated_monthly_net": round(freelance_net / 12, 2),
            "tax_note": fl_note,
        },
        "break_even": {
            "minimum_daily_rate": round(breakeven_rate, 2),
            "minimum_billable_days": breakeven_days,
            "current_rate_vs_breakeven": round(freelance_daily_rate - breakeven_rate, 2),
        },
        "net_advantage_annual": round(net_advantage, 2),
        "net_advantage_monthly": round(advantage_monthly, 2),
        "recommendation": "freelance" if net_advantage > 0 else "employment",
        "caveats": [
            "Freelance figures exclude employer-paid benefits (health insurance top-up, pension, paid leave).",
            "Income stability risk not modelled — freelance income may vary month to month.",
            "Use the tax module for a precise locale-specific net calculation.",
        ],
    }
