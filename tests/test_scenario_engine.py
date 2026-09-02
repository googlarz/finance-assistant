"""Tests for scenario_engine.py."""
import pytest
from scenario_engine import (
    compare_salary_packages, compare_mortgage_options,
    project_fire_timeline, compare_debt_payoff_vs_invest,
    compare_rent_vs_buy, compare_freelance_vs_employment,
)


def test_salary_comparison():
    result = compare_salary_packages([
        {"label": "Current", "annual_gross": 65000},
        {"label": "New Offer", "annual_gross": 75000, "benefits_value": 1200},
    ])
    assert len(result["packages"]) == 2
    assert result["best_option"]["label"] == "New Offer"


def test_mortgage_comparison():
    result = compare_mortgage_options([
        {"label": "Bank A", "loan_amount": 300000, "interest_rate": 3.5, "term_years": 25},
        {"label": "Bank B", "loan_amount": 300000, "interest_rate": 3.0, "term_years": 30},
    ])
    assert len(result["options"]) == 2
    assert result["best_option"] is not None


def test_fire_projection():
    result = project_fire_timeline(
        current_savings=50000, monthly_contribution=1500,
        annual_expenses=30000,
    )
    assert result["fire_number"] == 750000.0
    assert result["years_to_fire"] > 0
    assert result["achievable"] is True
    assert len(result["milestones"]) > 0
    # real_return_used must be present and differ from nominal when inflation > 0
    assert "real_return_used" in result
    assert result["real_return_used"] < result["annual_return_pct"]


def test_fire_unreachable():
    result = project_fire_timeline(
        current_savings=0, monthly_contribution=10,
        annual_expenses=100000,
    )
    assert result["fire_number"] == 2500000.0


def test_fire_inflation_affects_timeline():
    """inflation_rate must affect the projection — real return differs from nominal."""
    base = project_fire_timeline(
        current_savings=50000, monthly_contribution=1500,
        annual_expenses=30000, annual_return_pct=0.07, inflation_rate=0.0,
    )
    inflated = project_fire_timeline(
        current_savings=50000, monthly_contribution=1500,
        annual_expenses=30000, annual_return_pct=0.07, inflation_rate=0.03,
    )
    # With higher inflation, real return is lower → takes longer to reach FIRE
    assert inflated["months_to_fire"] > base["months_to_fire"], (
        "Higher inflation should increase time to FIRE"
    )
    assert inflated["real_return_used"] < base["real_return_used"]


def test_fire_real_equals_nominal_when_real_false():
    """When real=False, nominal return is used unchanged."""
    result = project_fire_timeline(
        current_savings=50000, monthly_contribution=1500,
        annual_expenses=30000, annual_return_pct=0.07, inflation_rate=0.02,
        real=False,
    )
    assert abs(result["real_return_used"] - 0.07) < 1e-9


def test_debt_vs_invest():
    result = compare_debt_payoff_vs_invest(
        debt_balance=10000, debt_rate=5,
        investment_return=8, monthly_available=500,
    )
    assert result["recommendation"] in ("pay_debt_first", "invest")
    assert result["difference"] > 0


def test_rent_vs_buy():
    result = compare_rent_vs_buy(
        monthly_rent=1200, home_price=400000,
        down_payment=80000, mortgage_rate=3.5,
    )
    assert result["recommendation"] in ("buy", "rent")
    assert result["buy"]["monthly_mortgage"] > 0
    assert result["rent"]["total_rent_paid"] > 0
    assert result["years"] == 30


def test_debt_vs_invest_no_double_counting():
    """Regression: net_b (invest-while-paying-minimum) subtracted BOTH the
    remaining principal AND the cumulative interest ever charged — but the
    remaining principal's growth already bakes in that accrued interest
    each month, so subtracting both double-counted the cost of debt and
    biased the comparison toward "pay debt first"."""
    result = compare_debt_payoff_vs_invest(
        debt_balance=1200, debt_rate=12,
        investment_return=8, monthly_available=24, years=1,
    )
    invest_net = result["invest_while_paying_minimum"]["net_position"]
    # The old (buggy, double-subtracted) formula produced -1183.62 for this
    # exact input; the fixed formula (invest_balance - remaining debt
    # balance, no separate interest term) produces -1047.81.
    assert invest_net != pytest.approx(-1183.62, abs=0.01)
    assert invest_net == pytest.approx(-1047.81, abs=0.5)


def test_rent_vs_buy_maintenance_reduces_renter_savings():
    """Regression: maintenance_rate (a real recurring ownership cost a
    renter avoids) was dropped from the renter's investable-savings
    calculation — property_tax_rate was included but maintenance_rate
    wasn't, understating the rent scenario and biasing toward "buy"."""
    with_maintenance = compare_rent_vs_buy(
        monthly_rent=1500, home_price=400000, down_payment=80000,
        mortgage_rate=4.0, years=10, maintenance_rate=0.02,
    )
    no_maintenance = compare_rent_vs_buy(
        monthly_rent=1500, home_price=400000, down_payment=80000,
        mortgage_rate=4.0, years=10, maintenance_rate=0.0,
    )
    assert with_maintenance["rent"]["net_position"] != no_maintenance["rent"]["net_position"]


# ── Tax wiring (regression: scenarios silently used a crude 25%/20% flat estimate
#    because they imported a non-existent calculate_tax and read keys no locale returns) ──

def test_get_tax_summary_normalizes_us(isolated_finance_dir):
    from tax_engine import get_tax_summary
    p = {"meta": {"locale": "us", "tax_year": 2024},
         "tax_profile": {"locale": "us", "filing_status": "single"},
         "employment": {"type": "employed", "annual_gross": 80000}}
    s = get_tax_summary(p, 2024)
    assert s["source"] == "engine"
    assert s["income_tax"] == pytest.approx(9441.0, abs=5)      # real federal income tax
    assert s["total_tax"] == pytest.approx(15561.0, abs=5)      # + FICA
    assert s["net"] == pytest.approx(64439.0, abs=5)
    assert "FICA" in s["components"]


def test_get_tax_summary_normalizes_de(isolated_finance_dir):
    from tax_engine import get_tax_summary
    p = {"meta": {"locale": "de", "tax_year": 2024},
         "tax_profile": {"locale": "de"},
         "employment": {"type": "employed", "annual_gross": 80000}}
    s = get_tax_summary(p, 2024)
    assert s["source"] == "engine"
    # DE income tax on 80k is ~22.4k — must be real, NOT the crude 0.25*80000=20000 guess
    assert s["income_tax"] == pytest.approx(22431.97, abs=50)
    assert "social contributions" in s["components"].lower()  # honest about what's excluded


def test_salary_comparison_uses_real_engine(isolated_finance_dir):
    """Net must come from the tax engine, not the 25%/20% flat fallback."""
    profile = {"meta": {"locale": "us", "tax_year": 2024},
               "tax_profile": {"locale": "us", "filing_status": "single"}}
    result = compare_salary_packages(
        [{"label": "A", "annual_gross": 80000}], profile=profile)
    pkg = result["packages"][0]
    # Crude fallback would give 80000*0.55 = 44000. Engine gives ~64.4k.
    assert pkg["estimated_annual_net"] > 60000
    assert "estimated (25%" not in pkg["tax_note"]
    assert "FICA" in pkg["tax_note"]


def test_freelance_vs_employment_uses_real_engine(isolated_finance_dir):
    profile = {"meta": {"locale": "us", "tax_year": 2024},
               "tax_profile": {"locale": "us", "filing_status": "single"}}
    r = compare_freelance_vs_employment(80000, 600, 220, 500, profile=profile)
    # Employed net must be engine-based (~64.4k), not crude 80000*0.55=44000
    assert r["employment"]["estimated_annual_net"] > 60000
    assert "estimated (~40" not in r["employment"]["tax_note"]
    assert r["recommendation"] in ("freelance", "employment")


def test_scenario_falls_back_gracefully_without_locale(isolated_finance_dir):
    """No locale set → crude estimate is acceptable, but must not crash."""
    result = compare_salary_packages([{"label": "A", "annual_gross": 80000}], profile={})
    assert result["packages"][0]["estimated_annual_net"] > 0
