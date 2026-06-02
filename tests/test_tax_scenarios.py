"""Tests for tax_scenarios — the law-accurate what-if comparisons."""
import pytest
from tax_scenarios import (
    compare_filing_status, compare_employment_type,
    compare_pretax_contribution, format_comparison, save,
)

US = {"meta": {"locale": "us", "tax_year": 2024},
      "tax_profile": {"locale": "us"}}


def test_employment_type_uses_engine(isolated_finance_dir):
    c = compare_employment_type(80000, 2024, US)
    assert c["engine"] is True
    labels = {s["label"]: s for s in c["scenarios"]}
    # W-2 net must be the real engine number (~64.4k), not a crude guess
    assert labels["W-2 employee"]["net"] == pytest.approx(64439, abs=50)
    assert labels["1099 self-employed"]["net"] == pytest.approx(63128, abs=50)
    assert c["best"] == "W-2 employee"
    assert c["net_advantage"] == pytest.approx(1311, abs=20)


def test_filing_status_mfj_beats_single_at_150k(isolated_finance_dir):
    c = compare_filing_status(150000, 2024, US)
    assert c["best"] == "Married filing jointly"
    assert c["net_advantage"] > 0


def test_pretax_contribution_reports_tax_saved(isolated_finance_dir):
    c = compare_pretax_contribution(100000, 23000, 2024, US)
    assert "tax_saved" in c
    assert c["tax_saved"] > 0
    # 23k pretax at the 22% marginal bracket → ~5k saved
    assert c["tax_saved"] == pytest.approx(5060, abs=100)


def test_format_comparison_renders(isolated_finance_dir):
    c = compare_employment_type(80000, 2024, US)
    out = format_comparison(c, "USD")
    assert "W-2 employee" in out
    assert "1099 self-employed" in out
    assert "Better" in out


def test_save_roundtrips(isolated_finance_dir):
    c = compare_employment_type(80000, 2024, US)
    rec = save("my freelance check", c, US)
    assert rec["name"] == "my freelance check"
    from scenario_store import load_scenario
    loaded = load_scenario("my freelance check")
    assert loaded is not None
    assert loaded["type"] == "tax_employment_type"


def test_no_locale_falls_back_not_crash(isolated_finance_dir):
    # Empty profile → engine may error per-locale; must not raise, engine flag False-able
    c = compare_employment_type(80000, 2024, {})
    assert "scenarios" in c
    out = format_comparison(c, "USD")
    assert isinstance(out, str)
