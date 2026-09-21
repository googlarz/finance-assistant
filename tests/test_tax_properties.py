"""Property-style sweeps over every locale's tax calculator (plain loops, no deps).

Entry point: tax_engine.get_tax_summary(profile, year), which normalizes each
locale's calculate_tax() output. Sweeps gross 20k..400k in 5k steps.
"""
import pytest

import tax_engine

LOCALES = ["de", "uk", "fr", "nl", "pl", "us", "ie"]
YEAR = 2026
GROSSES = list(range(20_000, 400_001, 5_000))
EPS = 0.02  # rounding tolerance (values are rounded to cents)


def _profile(locale, gross, married=False, filing_status=None):
    extra = {}
    if filing_status:
        extra["filing_status"] = filing_status
    return {
        "meta": {"locale": locale, "tax_year": YEAR, "primary_currency": "EUR"},
        "employment": {"type": "employed", "annual_gross": gross},
        "family": {"status": "married" if married else "single", "children": []},
        "tax_profile": {"locale": locale, "tax_class": "III" if (married and locale == "de") else "I",
                        "church_tax": False, "extra": extra},
    }


def _summary(locale, gross, **kw):
    s = tax_engine.get_tax_summary(_profile(locale, gross, **kw), YEAR)
    assert "error" not in s, f"{locale} @ {gross}: {s.get('error')}"
    return s


@pytest.mark.parametrize("locale", LOCALES)
def test_sanity_bounds(locale):
    for g in GROSSES:
        s = _summary(locale, g)
        assert s["gross"] == pytest.approx(g), (locale, g, s["gross"])
        assert s["total_tax"] is not None and s["total_tax"] >= 0, (locale, g, s["total_tax"])
        assert s["total_tax"] <= g, (locale, g, s["total_tax"])
        assert s["net"] == pytest.approx(g - s["total_tax"], abs=0.02)
        if s["income_tax"] is not None:
            assert s["income_tax"] >= -EPS, (locale, g, s["income_tax"])
        assert s["total_burden"] is not None
        assert 0 <= s["total_burden"] <= g, (locale, g, s["total_burden"])
        assert s["total_burden"] >= s["total_tax"] - EPS, (locale, g)


@pytest.mark.parametrize("locale", LOCALES)
def test_total_tax_monotonic_in_gross(locale):
    prev_g, prev_t = None, None
    for g in GROSSES:
        t = _summary(locale, g)["total_tax"]
        if prev_t is not None:
            assert t >= prev_t - EPS, f"{locale}: tax fell {prev_t} -> {t} going {prev_g} -> {g}"
        prev_g, prev_t = g, t


@pytest.mark.parametrize("locale", LOCALES)
def test_total_burden_monotonic_in_gross(locale):
    prev_g, prev_t = None, None
    for g in GROSSES:
        t = _summary(locale, g)["total_burden"]
        if prev_t is not None:
            assert t >= prev_t - EPS, f"{locale}: burden fell {prev_t} -> {t} going {prev_g} -> {g}"
        prev_g, prev_t = g, t


@pytest.mark.parametrize("locale", LOCALES)
def test_net_never_decreases_when_gross_rises(locale):
    """No negative marginal take-home. A genuine cliff, if one exists in a
    locale's rules, must be documented here rather than failing."""
    prev_g, prev_n = None, None
    for g in GROSSES:
        n = _summary(locale, g)["net"]
        if prev_n is not None:
            assert n >= prev_n - EPS, f"{locale}: net fell {prev_n} -> {n} going {prev_g} -> {g}"
        prev_g, prev_n = g, n
    # burden-based net
    prev = None
    for g in GROSSES:
        n = g - _summary(locale, g)["total_burden"]
        if prev is not None:
            assert n >= prev - EPS, f"{locale}: take-home after burden fell {prev} -> {n} at {g}"
        prev = n


@pytest.mark.parametrize("locale", LOCALES)
def test_fine_grained_monotonic_around_thresholds(locale):
    """Finer 500-step sweep over the range where brackets/allowances kick in."""
    prev = None
    for g in range(10_000, 200_001, 500):
        t = _summary(locale, g)["total_tax"]
        if prev is not None:
            assert t >= prev - EPS, f"{locale}: tax fell {prev} -> {t} at gross {g}"
        prev = t


def test_us_joint_filing_never_more_tax_than_single():
    """Documented rule: MFJ brackets/standard deduction are at least as wide as
    single, so MFJ on the same income never yields more federal income tax."""
    for g in GROSSES:
        single = _summary("us", g, filing_status="single")
        joint = _summary("us", g, married=True, filing_status="married_filing_jointly")
        assert joint["income_tax"] <= single["income_tax"] + EPS, (
            g, joint["income_tax"], single["income_tax"])


def test_ie_married_one_income_never_more_tax_than_single():
    """Irish married one-income: wider standard-rate band and higher credits."""
    for g in GROSSES:
        single = _summary("ie", g)
        married = _summary("ie", g, married=True)
        assert married["income_tax"] <= single["income_tax"] + EPS, (
            g, married["income_tax"], single["income_tax"])


def test_fr_married_quotient_never_more_ir_than_single():
    """French quotient familial: 2 parts never gives MORE income tax than 1 part
    on the same taxable income."""
    for g in GROSSES:
        single = _summary("fr", g)
        married = _summary("fr", g, married=True)
        assert married["income_tax"] <= single["income_tax"] + EPS, (
            g, married["income_tax"], single["income_tax"])


def test_de_splitting_class_iii_never_more_income_tax_than_class_i():
    """Ehegattensplitting (Steuerklasse III) is never worse than class I for a
    single-earner couple, on the income-tax component."""
    for g in GROSSES:
        c1 = tax_engine.get_tax_summary(_profile("de", g), YEAR)
        c3 = tax_engine.get_tax_summary(_profile("de", g, married=True), YEAR)
        assert c3["income_tax"] <= c1["income_tax"] + EPS, (g, c3["income_tax"], c1["income_tax"])
