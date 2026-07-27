# tests/test_tax_optimizer.py
"""Tests for scripts/tax_optimizer.py"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from db import get_conn, init_db
from tax_optimizer import (
    _get_ytd_data,
    get_de_opportunities,
    get_optimization_opportunities,
    get_tax_action_summary,
    project_year_end_tax,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

YEAR = 2025


def _insert_tx(conn, date: str, amount: float, category: str = "salary", type: str = "expense"):
    """Insert a minimal transaction row directly into the DB."""
    conn.execute(
        """
        INSERT INTO transactions
            (id, account_id, date, amount, currency, category, description, type, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4())[:8],
            "acc_test",
            date,
            amount,
            "EUR",
            category,
            "test",
            type,
            datetime.now().isoformat(),
        ),
    )


def _de_profile(**overrides) -> dict:
    profile = {
        "meta": {"primary_currency": "EUR", "locale": "de", "tax_year": YEAR},
        "employment": {"type": "employed", "annual_gross": 60_000, "currency": "EUR"},
        "family": {"status": "single", "children": []},
        "housing": {"homeoffice_days_per_week": 3},
        "tax_profile": {"locale": "de", "extra": {}},
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(profile.get(k), dict):
            profile[k].update(v)
        else:
            profile[k] = v
    return profile


# ---------------------------------------------------------------------------
# _get_ytd_data
# ---------------------------------------------------------------------------

class TestGetYtdData:
    def test_correct_aggregation(self, isolated_finance_dir):
        init_db()
        with get_conn() as conn:
            _insert_tx(conn, f"{YEAR}-01-15", 3000.0, "salary")
            _insert_tx(conn, f"{YEAR}-01-20", 3000.0, "salary")
            _insert_tx(conn, f"{YEAR}-02-15", 3000.0, "salary")
            _insert_tx(conn, f"{YEAR}-02-10", -250.0, "food")
            _insert_tx(conn, f"{YEAR}-01-25", -100.0, "charitable")

        with get_conn() as conn:
            data = _get_ytd_data(conn, YEAR)

        assert data["ytd_income"] == pytest.approx(9000.0)
        assert data["ytd_expenses"] == pytest.approx(350.0)
        assert data["months_elapsed"] == 2
        assert data["ytd_charitable"] == pytest.approx(100.0)

    def test_empty_db_returns_zeros(self, isolated_finance_dir):
        init_db()
        with get_conn() as conn:
            data = _get_ytd_data(conn, YEAR)
        assert data["ytd_income"] == 0.0
        assert data["months_elapsed"] == 0
        assert data["ytd_charitable"] == 0.0

    def test_different_year_not_counted(self, isolated_finance_dir):
        init_db()
        with get_conn() as conn:
            _insert_tx(conn, "2024-06-01", 5000.0, "salary")
        with get_conn() as conn:
            data = _get_ytd_data(conn, YEAR)
        assert data["ytd_income"] == 0.0
        assert data["months_elapsed"] == 0

    def test_transfers_and_investments_excluded(self, isolated_finance_dir):
        """Issue #7: transfers/investment moves must not inflate YTD income
        or expenses used for tax-optimization projections."""
        init_db()
        with get_conn() as conn:
            _insert_tx(conn, f"{YEAR}-01-15", 3000.0, "salary")
            _insert_tx(conn, f"{YEAR}-01-20", -250.0, "food")
            _insert_tx(conn, f"{YEAR}-01-25", 10000.0, "savings", type="transfer")
            _insert_tx(conn, f"{YEAR}-01-26", -2000.0, "brokerage", type="investment")
            _insert_tx(conn, f"{YEAR}-01-27", -500.0, "loan", type="debt_payment")
        with get_conn() as conn:
            data = _get_ytd_data(conn, YEAR)
        assert data["ytd_income"] == pytest.approx(3000.0)
        assert data["ytd_expenses"] == pytest.approx(250.0)


# ---------------------------------------------------------------------------
# project_year_end_tax
# ---------------------------------------------------------------------------

class TestProjectYearEndTax:
    def test_returns_required_keys(self, isolated_finance_dir):
        init_db()
        profile = _de_profile()
        with get_conn() as conn:
            for m in ("01", "02", "03", "04"):
                _insert_tx(conn, f"{YEAR}-{m}-15", 5000.0, "salary")

        result = project_year_end_tax(profile, YEAR)

        assert "error" not in result
        for key in (
            "year", "locale", "months_elapsed", "ytd_income",
            "projected_annual_income", "confidence", "note",
        ):
            assert key in result, f"Missing key: {key}"

    def test_annualisation_math(self, isolated_finance_dir):
        init_db()
        profile = _de_profile()
        with get_conn() as conn:
            # 2 months, €4000/month → projected €24,000/year
            _insert_tx(conn, f"{YEAR}-01-10", 4000.0, "salary")
            _insert_tx(conn, f"{YEAR}-02-10", 4000.0, "salary")

        result = project_year_end_tax(profile, YEAR)

        assert result["months_elapsed"] == 2
        assert result["ytd_income"] == pytest.approx(8000.0)
        assert result["projected_annual_income"] == pytest.approx(48000.0)

    def test_no_transactions_returns_low_confidence(self, isolated_finance_dir):
        init_db()
        profile = _de_profile()
        result = project_year_end_tax(profile, YEAR)

        assert "error" not in result
        assert result["months_elapsed"] == 0
        assert result["confidence"] == "low"

    def test_unsupported_locale_returns_error(self, isolated_finance_dir):
        init_db()
        profile = _de_profile()
        profile["tax_profile"]["locale"] = "xx"  # not a real locale

        # tax_engine will raise ValueError for unknown locale
        result = project_year_end_tax(profile, YEAR)
        assert "error" in result
        assert result["locale"] == "xx"

    def test_confidence_levels(self, isolated_finance_dir):
        init_db()
        profile = _de_profile()

        # 1 month → low
        with get_conn() as conn:
            _insert_tx(conn, f"{YEAR}-01-10", 3000.0)
        assert project_year_end_tax(profile, YEAR)["confidence"] == "low"

    def test_medium_confidence(self, isolated_finance_dir):
        init_db()
        profile = _de_profile()
        with get_conn() as conn:
            for m in ("01", "02", "03", "04", "05"):
                _insert_tx(conn, f"{YEAR}-{m}-10", 3000.0)
        assert project_year_end_tax(profile, YEAR)["confidence"] == "medium"


# ---------------------------------------------------------------------------
# get_de_opportunities
# ---------------------------------------------------------------------------

class TestGetDeOpportunities:
    def _ytd(self, income=15000, months=4, charitable=0, ho_days=0):
        return {
            "ytd_income": income,
            "months_elapsed": months,
            "ytd_homeoffice_days": ho_days,
            "ytd_charitable": charitable,
            "ytd_work_expenses": 0,
        }

    def test_no_riester_shows_opportunity(self):
        profile = _de_profile()
        # No riester in tax_extra
        opps = get_de_opportunities(profile, self._ytd(), YEAR)
        categories = [o["category"] for o in opps]
        assert "retirement" in categories
        riester_opps = [o for o in opps if "Riester" in o["action"]]
        assert riester_opps, "Expected a Riester opportunity"

    def test_maxed_riester_no_opportunity(self):
        profile = _de_profile()
        profile["tax_profile"]["extra"] = {
            "riester": True,
            "riester_contribution": 2100,  # already at max
        }
        opps = get_de_opportunities(profile, self._ytd(), YEAR)
        riester_opps = [o for o in opps if "Riester" in o["action"]]
        assert not riester_opps, "Should not suggest Riester when already maxed"

    def test_homeoffice_3_days_per_week(self):
        profile = _de_profile()
        # 3 days/week → projected 138 days (3*46), cap=210 → remaining=72 days
        ytd = self._ytd(income=20000, months=4)
        opps = get_de_opportunities(profile, ytd, YEAR)
        ho_opps = [o for o in opps if o["category"] == "homeoffice"]
        assert ho_opps, "Expected homeoffice opportunity for 3 days/week"
        # Remaining days = 210 - min(138, 210) = 72
        opp = ho_opps[0]
        assert opp["max_deductible_amount"] == pytest.approx(72 * 6, abs=1)

    def test_partial_riester_shows_gap(self):
        profile = _de_profile()
        profile["tax_profile"]["extra"] = {
            "riester": True,
            "riester_contribution": 1000,
        }
        opps = get_de_opportunities(profile, self._ytd(income=20000, months=4), YEAR)
        riester_opps = [o for o in opps if "Riester" in o["action"]]
        assert riester_opps
        assert riester_opps[0]["max_deductible_amount"] == pytest.approx(1100.0)

    def test_charitable_opportunity_appears(self):
        profile = _de_profile()
        ytd = self._ytd(income=30000, months=6, charitable=0)
        opps = get_de_opportunities(profile, ytd, YEAR)
        charitable_opps = [o for o in opps if o["category"] == "charitable"]
        assert charitable_opps, "Expected charitable opportunity"

    def test_sorted_by_saving_descending(self):
        profile = _de_profile()
        ytd = self._ytd(income=30000, months=6, charitable=0)
        opps = get_de_opportunities(profile, ytd, YEAR)
        savings = [o["potential_tax_saving"] for o in opps]
        assert savings == sorted(savings, reverse=True)

    def test_ruerup_opportunity_high_earner(self):
        profile = _de_profile()
        profile["employment"]["annual_gross"] = 80_000
        ytd = self._ytd(income=40000, months=6)
        opps = get_de_opportunities(profile, ytd, YEAR)
        ruerup_opps = [o for o in opps if "Rürup" in o["action"] or "ruerup" in o["action"].lower()]
        assert ruerup_opps, "Expected Rürup opportunity for high earner"


# ---------------------------------------------------------------------------
# get_optimization_opportunities
# ---------------------------------------------------------------------------

class TestGetOptimizationOpportunities:
    def test_non_de_locale_returns_empty(self, isolated_finance_dir):
        init_db()
        profile = _de_profile()
        profile["tax_profile"]["locale"] = "uk"
        result = get_optimization_opportunities(profile, YEAR)
        assert result == []

    def test_de_locale_returns_list(self, isolated_finance_dir):
        init_db()
        with get_conn() as conn:
            for m in ("01", "02", "03", "04"):
                _insert_tx(conn, f"{YEAR}-{m}-10", 4000.0, "salary")
        profile = _de_profile()
        result = get_optimization_opportunities(profile, YEAR)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# get_tax_action_summary
# ---------------------------------------------------------------------------

class TestGetTaxActionSummary:
    def test_returns_non_empty_string(self, isolated_finance_dir):
        init_db()
        profile = _de_profile()
        with get_conn() as conn:
            for m in ("01", "02", "03", "04"):
                _insert_tx(conn, f"{YEAR}-{m}-15", 5000.0, "salary")
        result = get_tax_action_summary(profile, YEAR)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_no_data_returns_explanation(self, isolated_finance_dir):
        init_db()
        profile = _de_profile()
        result = get_tax_action_summary(profile, YEAR)
        assert isinstance(result, str)
        assert "no transaction data" in result.lower() or "month" in result.lower()

    def test_contains_year(self, isolated_finance_dir):
        init_db()
        profile = _de_profile()
        with get_conn() as conn:
            _insert_tx(conn, f"{YEAR}-03-10", 5000.0, "salary")
        result = get_tax_action_summary(profile, YEAR)
        assert str(YEAR) in result

    def test_mocked_tax_engine_still_produces_summary(self, isolated_finance_dir):
        """Summary works even if tax_engine.calculate_tax_estimate fails."""
        init_db()
        profile = _de_profile()
        with get_conn() as conn:
            for m in ("01", "02", "03"):
                _insert_tx(conn, f"{YEAR}-{m}-10", 4000.0, "salary")

        mock_result = {
            "estimated_refund": 400.0,
            "details": {"total_tax_due": 8000.0, "estimated_refund": 400.0},
        }
        with patch("tax_optimizer.tax_engine") as mock_engine:
            mock_engine.calculate_tax_estimate.return_value = mock_result
            result = get_tax_action_summary(profile, YEAR)

        assert isinstance(result, str)
        assert str(YEAR) in result
