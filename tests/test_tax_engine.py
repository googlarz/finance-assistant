"""
Direct tests for scripts/tax_engine.py — the normalized gateway to all locale math.

Previously untested despite being the single source of truth for all consumers
(scenario engine, tax brief, session monitor). Tests here assert:
  - get_tax_summary() returns the expected normalized keys for all 6 locales
  - FR income_tax bug fixed: top-level 'income_tax' key now picked up
  - total_tax reflects full fiscal burden (not just income tax) for UK/FR/PL
  - social_tax + total_burden correctly surfaces DE employee contributions
  - effective_rate is computed from total_tax / gross (not locale-specific income rate)
  - error path returns error key, not KeyError
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tax_engine import get_tax_summary, calculate_tax_estimate, get_available_locales

# ── Test profiles — minimal valid input for each locale ──────────────────────

_PROFILES = {
    "de": {"employment": {"annual_gross": 60000}, "tax_profile": {"locale": "de", "tax_class": "I", "tax_year": 2024, "extra": {}}},
    "uk": {"employment": {"annual_gross": 50000}, "tax_profile": {"locale": "uk", "tax_year": 2024, "extra": {}}},
    "fr": {"employment": {"annual_gross": 45000}, "tax_profile": {"locale": "fr", "tax_year": 2024, "extra": {}}},
    "nl": {"employment": {"annual_gross": 50000}, "tax_profile": {"locale": "nl", "tax_year": 2024, "extra": {}}},
    "pl": {"employment": {"annual_gross": 80000}, "tax_profile": {"locale": "pl", "tax_year": 2024, "extra": {}}},
    "us": {"employment": {"annual_gross": 80000}, "tax_profile": {"locale": "us", "filing_status": "single", "tax_year": 2024, "extra": {}}},
}

ALL_LOCALES = list(_PROFILES.keys())

# Required keys that MUST be present in every get_tax_summary() result
_REQUIRED_KEYS = {"locale", "year", "gross", "total_tax", "total_burden", "net",
                  "effective_rate", "components", "source"}


# ── Normalized output shape ───────────────────────────────────────────────────

@pytest.mark.parametrize("code", ALL_LOCALES)
def test_get_tax_summary_required_keys_present(code):
    """get_tax_summary() must return all required normalized keys."""
    result = get_tax_summary(_PROFILES[code], 2024)
    assert "error" not in result, f"{code}: unexpected error: {result.get('error')}"
    for key in _REQUIRED_KEYS:
        assert key in result, f"{code}: missing required key '{key}'"


@pytest.mark.parametrize("code", ALL_LOCALES)
def test_get_tax_summary_source_is_engine(code):
    result = get_tax_summary(_PROFILES[code], 2024)
    assert result.get("source") == "engine", f"{code}: source should be 'engine'"


@pytest.mark.parametrize("code", ALL_LOCALES)
def test_get_tax_summary_locale_matches(code):
    result = get_tax_summary(_PROFILES[code], 2024)
    assert result.get("locale") == code, f"{code}: locale field mismatch"


# ── Numeric sanity ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", ALL_LOCALES)
def test_get_tax_summary_total_tax_positive(code):
    """total_tax must be a positive number — none of the locales should produce zero tax."""
    result = get_tax_summary(_PROFILES[code], 2024)
    assert result["total_tax"] is not None, f"{code}: total_tax is None"
    assert result["total_tax"] > 0, f"{code}: total_tax should be positive, got {result['total_tax']}"


@pytest.mark.parametrize("code", ALL_LOCALES)
def test_get_tax_summary_net_equals_gross_minus_total_tax(code):
    """net must equal gross - total_tax (within 1 cent)."""
    r = get_tax_summary(_PROFILES[code], 2024)
    if r.get("gross") is not None and r.get("total_tax") is not None and r.get("net") is not None:
        expected = round(r["gross"] - r["total_tax"], 2)
        assert abs(r["net"] - expected) < 0.02, (
            f"{code}: net {r['net']} != gross {r['gross']} - total_tax {r['total_tax']} = {expected}"
        )


@pytest.mark.parametrize("code", ALL_LOCALES)
def test_get_tax_summary_effective_rate_range(code):
    """effective_rate must be between 0 and 1."""
    result = get_tax_summary(_PROFILES[code], 2024)
    er = result.get("effective_rate")
    assert er is not None, f"{code}: effective_rate is None"
    assert 0 < er < 1, f"{code}: effective_rate {er} outside (0, 1)"


@pytest.mark.parametrize("code", ALL_LOCALES)
def test_get_tax_summary_effective_rate_equals_total_tax_over_gross(code):
    """effective_rate must equal total_tax / gross (not just income_tax / gross)."""
    r = get_tax_summary(_PROFILES[code], 2024)
    if r.get("gross") and r.get("total_tax") and r.get("effective_rate"):
        expected = round(r["total_tax"] / r["gross"], 4)
        assert abs(r["effective_rate"] - expected) < 0.001, (
            f"{code}: effective_rate {r['effective_rate']} should be "
            f"total_tax/gross = {expected}"
        )


@pytest.mark.parametrize("code", ALL_LOCALES)
def test_get_tax_summary_total_burden_ge_total_tax(code):
    """total_burden must be >= total_tax (it adds social contributions where applicable)."""
    r = get_tax_summary(_PROFILES[code], 2024)
    assert r.get("total_burden") is not None, f"{code}: total_burden is None"
    assert r["total_burden"] >= r["total_tax"], (
        f"{code}: total_burden {r['total_burden']} < total_tax {r['total_tax']}"
    )


# ── Locale-specific correctness ───────────────────────────────────────────────

def test_fr_income_tax_not_none():
    """FR income_tax was previously None due to wrong key lookup. Regression guard."""
    r = get_tax_summary(_PROFILES["fr"], 2024)
    assert r.get("income_tax") is not None, (
        "FR income_tax is None — top-level 'income_tax' key not being picked up. "
        "Check the _num() call in get_tax_summary()."
    )
    assert r["income_tax"] > 0, f"FR income_tax should be positive, got {r['income_tax']}"


def test_fr_total_tax_includes_prelevements():
    """FR total_tax must include prélèvements sociaux, not just IR."""
    r = get_tax_summary(_PROFILES["fr"], 2024)
    # income_tax (IR only) is ~5489 for 45k; prelevements ~4288; total ~9778
    assert r["total_tax"] > r["income_tax"] * 1.5, (
        f"FR total_tax {r['total_tax']} should exceed income_tax {r['income_tax']} by ~80% "
        "(prélèvements sociaux not being captured)"
    )


def test_de_social_tax_present():
    """DE social_tax (employee ZUS-like contributions) must be captured separately."""
    r = get_tax_summary(_PROFILES["de"], 2024)
    assert r.get("social_tax") is not None and r["social_tax"] > 0, (
        f"DE social_tax should be positive (employee pension/health/care/unemployment), "
        f"got {r.get('social_tax')}"
    )


def test_de_total_burden_includes_social():
    """DE total_burden must be significantly larger than total_tax alone."""
    r = get_tax_summary(_PROFILES["de"], 2024)
    # For €60k: income+soli ~14148, social ~12330 → burden ~26478
    assert r["total_burden"] > r["total_tax"] * 1.5, (
        f"DE total_burden {r['total_burden']} should be ~1.87x total_tax {r['total_tax']} "
        "(employee social contributions missing)"
    )


def test_uk_total_tax_includes_ni():
    """UK total_tax must include National Insurance, not just income tax."""
    r = get_tax_summary(_PROFILES["uk"], 2024)
    assert r["income_tax"] is not None
    # For £50k: income_tax ~7486, NI ~2994 → total ~10480
    assert r["total_tax"] > r["income_tax"], (
        f"UK total_tax {r['total_tax']} should exceed income_tax {r['income_tax']} (NI missing)"
    )


def test_pl_total_tax_includes_zus():
    """PL total_tax must include ZUS and health contributions."""
    r = get_tax_summary(_PROFILES["pl"], 2024)
    # For 80k PLN: income_tax ~4323, ZUS ~10968, health ~6212 → total ~21504
    assert r["total_tax"] > r["income_tax"] * 3, (
        f"PL total_tax {r['total_tax']} should be >3x income_tax {r['income_tax']} "
        "(ZUS + health insurance missing)"
    )


def test_us_total_tax_includes_fica():
    """US total_tax must include FICA (SS + Medicare)."""
    r = get_tax_summary(_PROFILES["us"], 2024)
    assert r.get("payroll_tax") is not None and r["payroll_tax"] > 0, (
        f"US payroll_tax should include FICA, got {r.get('payroll_tax')}"
    )
    assert r["total_tax"] > r["income_tax"], (
        f"US total_tax {r['total_tax']} should exceed income_tax {r['income_tax']} (FICA missing)"
    )


# ── Error handling ────────────────────────────────────────────────────────────

def test_get_tax_summary_unknown_locale_returns_error():
    """Unknown locale returns error key, not KeyError."""
    profile = {"employment": {"annual_gross": 50000}, "tax_profile": {"locale": "xx", "tax_year": 2024, "extra": {}}}
    result = get_tax_summary(profile, 2024)
    assert "error" in result, "Expected error for unknown locale 'xx'"
    assert result.get("source") == "error"


def test_calculate_tax_estimate_unknown_locale_returns_error():
    profile = {"employment": {"annual_gross": 50000}, "tax_profile": {"locale": "xx", "tax_year": 2024, "extra": {}}}
    result = calculate_tax_estimate(profile, 2024)
    assert "error" in result, "Expected error for unknown locale 'xx'"


# ── get_available_locales ─────────────────────────────────────────────────────

def test_get_available_locales_returns_all_six():
    locales = get_available_locales()
    codes = {loc["code"] for loc in locales}
    expected = {"de", "uk", "fr", "nl", "pl", "us"}
    assert expected.issubset(codes), f"Missing locales: {expected - codes}"


def test_get_available_locales_have_required_fields():
    for loc in get_available_locales():
        assert "code" in loc
        assert "name" in loc
        assert "years" in loc
        assert "currency" in loc
