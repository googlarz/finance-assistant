"""End-to-end user journeys, one per locale.

Blank profile -> onboarding (all 9 steps via parse_step_response/complete_step)
-> bank CSV import -> tax / net worth / budget variance / digest / alerts.

Purpose: catch silent failures. Several public wrappers swallow exceptions by
design (digest, alerts, tax_engine fallbacks), so a second test calls the
underlying functions directly, where an exception would surface.
"""
import os
import tempfile
from datetime import date

import pytest

import onboarding
import tax_engine
import net_worth_engine
import budget_engine
import weekly_digest
import session_alerts
import profile_manager
import account_manager
import import_router
from transaction_logger import get_transactions

YEAR = date.today().year

# locale -> (basics, employment, housing, goals, debts, investments, accounts, tax, budget, gross, currency)
JOURNEYS = {
    "de": dict(
        basics="I'm Anna Schmidt and I live in Germany",
        employment="I'm employed, gross 72,000 per year",
        housing="I rent in Berlin, 1300 per month",
        goals="Emergency fund of 15000 by end of year",
        debts="Student loan 8000 at 3.5%",
        investments="ETF 25000",
        accounts="DKB checking and ING savings",
        tax="Steuerklasse 1, no Kirchensteuer",
        budget="50/30/20",
        gross=72000, currency="EUR",
    ),
    "uk": dict(
        basics="I'm James Taylor and I live in the UK",
        employment="I'm employed, gross £58,000 per year",
        housing="I rent in London, 1800 per month",
        goals="Holiday fund of £5000 by end of year",
        debts="Credit card 3000 at 19%",
        investments="ISA 20000",
        accounts="Monzo current and Barclays savings",
        tax="Standard tax code, ISA user",
        budget="50/30/20",
        gross=58000, currency="GBP",
    ),
    "fr": dict(
        basics="I'm Claire Martin and I live in France",
        employment="I'm employed, gross 54,000 per year",
        housing="I rent in Lyon, 950 per month",
        goals="Emergency fund of 9000 by end of year",
        debts="Car loan 6000 at 4%",
        investments="ETF 12000",
        accounts="BNP checking and BNP savings",
        tax="Married, one child",
        budget="50/30/20",
        gross=54000, currency="EUR",
    ),
    "nl": dict(
        basics="I'm Pieter Jansen and I live in the Netherlands",
        employment="I'm employed, gross 62,000 per year",
        housing="I rent in Utrecht, 1400 per month",
        goals="Emergency fund of 10000 by end of year",
        debts="Student loan 12000 at 2.5%",
        investments="ETF 18000",
        accounts="ING checking and ABN AMRO savings",
        tax="30% ruling not applicable",
        budget="50/30/20",
        gross=62000, currency="EUR",
    ),
    "pl": dict(
        basics="I'm Piotr Kowalski and I live in Poland",
        employment="I'm employed, gross 180,000 per year",
        housing="I rent in Warsaw, 3500 per month",
        goals="Emergency fund of 30000 by end of year",
        debts="Car loan 25000 at 7%",
        investments="ETF 40000",
        accounts="PKO checking and mBank savings",
        tax="Standard scale, no joint filing",
        budget="50/30/20",
        gross=180000, currency="PLN",
    ),
    "us": dict(
        basics="I'm Emily Johnson and I live in the United States",
        employment="I'm employed, gross $95,000 per year",
        housing="I rent in Austin, 2100 per month",
        goals="Emergency fund of $20000 by end of year",
        debts="Student loan 30000 at 5.5%",
        investments="401k 60000",
        accounts="Chase checking and Ally savings",
        tax="Single filing status",
        budget="50/30/20",
        gross=95000, currency="USD",
    ),
    "ie": dict(
        basics="I'm Aoife Murphy and I live in Ireland",
        employment="I'm employed, gross 66,000 per year",
        housing="I rent in Dublin, 2000 per month",
        goals="Emergency fund of 12000 by end of year",
        debts="Car loan 9000 at 6%",
        investments="ETF 15000",
        accounts="Revolut checking and AIB savings",
        tax="Single, PAYE employee",
        budget="50/30/20",
        gross=66000, currency="EUR",
    ),
}

LOCALES = sorted(JOURNEYS)


def _run_onboarding(locale):
    j = JOURNEYS[locale]
    onboarding.reset_onboarding()
    parsed = {}
    for step in onboarding.STEPS:
        parsed[step] = onboarding.parse_step_response(step, j[step], locale=locale)
        assert not parsed[step].get("needs_clarification"), (locale, step, parsed[step])
        onboarding.complete_step(step, parsed[step])
    return parsed


def _write_csv(locale):
    """Realistic single-account statement, dated this month, generic columns."""
    d = date.today().replace(day=1).isoformat()
    rows = [
        (d, "Salary Employer", 4200.00),
        (d, "Rent Landlord", -1300.00),
        (d, "Supermarket Weekly Shop", -86.40),
        (d, "Streaming Subscription", -12.99),
        (d, "Public Transport Pass", -49.00),
        (d, "Restaurant Dinner", -54.20),
    ]
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    f.write("Date,Description,Amount\n")
    for r in rows:
        f.write(f"{r[0]},{r[1]},{r[2]:.2f}\n")
    f.close()
    return f.name, len(rows)


def _import_statement(locale):
    checking = next(a for a in account_manager.list_accounts() if a["type"] == "checking")
    path, n = _write_csv(locale)
    try:
        res = import_router.import_file(
            path, account_id=checking["id"], currency=JOURNEYS[locale]["currency"],
            dry_run=False, keep_original=False,
        )
    finally:
        os.unlink(path)
    return checking, res, n


@pytest.mark.parametrize("locale", LOCALES)
def test_journey(locale):
    j = JOURNEYS[locale]
    _run_onboarding(locale)

    # onboarding landed in the profile and the engines
    profile = profile_manager.get_profile()
    assert profile_manager.get_locale() == locale
    assert profile["meta"]["primary_currency"] == j["currency"]
    assert profile["employment"]["annual_gross"] == j["gross"]
    assert onboarding.is_onboarding_complete()
    accounts = account_manager.list_accounts()
    assert len(accounts) >= 1 and any(a["type"] == "checking" for a in accounts), accounts

    # bank import
    checking, res, n = _import_statement(locale)
    assert "error" not in res, res
    assert res["imported"] == n, res
    stored = get_transactions(account_id=checking["id"], year=YEAR)
    assert len(stored) == n

    # tax
    summary = tax_engine.get_tax_summary(profile, YEAR)
    assert "error" not in summary, summary
    assert summary["locale"] == locale
    assert summary["gross"] == pytest.approx(j["gross"])
    assert 0 < summary["total_tax"] < j["gross"]
    assert summary["net"] == pytest.approx(j["gross"] - summary["total_tax"], abs=0.02)
    est = tax_engine.calculate_tax_estimate(profile, YEAR)
    assert "error" not in est, est

    # net worth
    nw = net_worth_engine.calculate_net_worth()
    assert isinstance(nw["net_worth"], (int, float)), nw
    assert nw["net_worth"] == nw["net_worth"]  # not NaN

    # budget variance
    today = date.today()
    assert budget_engine.get_budget(today.year, today.month) is not None
    var = budget_engine.get_budget_variance(today.year, today.month)
    assert "error" not in var, var

    # digest + alerts
    digest = weekly_digest.generate_digest(profile)
    assert isinstance(digest["sections"], list) and digest["sections"]
    assert all(isinstance(s, str) and s for s in digest["sections"])
    alerts = session_alerts.get_session_alerts(profile)
    assert isinstance(alerts, list)


@pytest.mark.parametrize("locale", LOCALES)
def test_journey_without_swallowing(locale):
    """Same journey, but call the underlying functions directly so an
    exception is a test failure instead of a silently dropped section."""
    _run_onboarding(locale)
    _import_statement(locale)
    profile = profile_manager.get_profile()
    today = date.today()

    # Locale plugin called directly: no try/except fallback from tax_engine.
    from locales.context import LocaleContext
    mod = tax_engine._load_locale(locale)
    ctx = LocaleContext.from_finance_profile(profile, tax_year=YEAR)
    result = mod.calculate_tax(ctx, YEAR)
    assert isinstance(result, dict) and "error" not in result, result
    fn = getattr(mod, "get_social_contributions", None)
    if fn is not None:
        sc = fn(float(JOURNEYS[locale]["gross"]), YEAR)
        assert sc.get("total", 0) >= 0
    assert isinstance(tax_engine.get_tax_deadlines(profile, YEAR), list)
    assert isinstance(tax_engine.get_tax_rules(profile, YEAR), dict)
    assert isinstance(tax_engine.generate_tax_claims(profile, YEAR, persist=False), dict)

    # digest sections (generate_digest wraps each of these in swallow-all)
    weekly_digest._net_worth_summary(profile)
    weekly_digest._budget_summary(today)
    weekly_digest._portfolio_summary(profile)
    weekly_digest._deadline_summary(today, locale)
    weekly_digest._inbox_summary()

    # alert producers (get_session_alerts wraps each in swallow-all)
    session_alerts._budget_alerts(today)
    session_alerts._recurring_alerts(today)
    session_alerts._goal_alerts(today)
    session_alerts._tax_alerts(today, locale)
    session_alerts._fire_alert(profile, today)
    session_alerts._threshold_alerts(profile)
    session_alerts._quarterly_us_tax_alert(today)
    session_alerts._portfolio_drift_alert(profile)
    session_alerts._inbox_alert()
    session_alerts._data_coach_alerts(profile)

    net_worth_engine.calculate_net_worth()
    net_worth_engine.take_snapshot()
    budget_engine.get_budget_variance(today.year, today.month)


# ── Regression tests for onboarding parser defects fixed in 4.2.0 ──

@pytest.mark.parametrize("text,expected", [("gross 72000 per year", 72000), ("€65000", 65000)])
def test_employment_parses_unseparated_amount(text, expected):
    assert onboarding.parse_step_response("employment", text)["gross_annual"] == expected


def test_basics_dutch_surname_does_not_override_country():
    r = onboarding.parse_step_response("basics", "I'm Pieter de Vries and I live in the Netherlands")
    assert r["locale"] == "nl"


def test_accounts_adjacent_banks_keep_own_type():
    r = onboarding.parse_step_response("accounts", "DKB checking and ING savings")
    assert [a["type"] for a in r["accounts"]] == ["checking", "savings"]
