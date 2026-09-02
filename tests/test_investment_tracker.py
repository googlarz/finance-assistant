"""Tests for investment_tracker.py and investment_returns.py."""
import os
import sys

scripts_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from investment_tracker import (
    get_portfolio, add_holding, update_holding, delete_holding,
    calculate_allocation, calculate_total_return, suggest_rebalance,
    calculate_fire_number, project_portfolio_growth,
    take_portfolio_snapshot, format_portfolio_display,
)
from investment_returns import approximate_xirr, xirr_value


def test_empty_portfolio(isolated_finance_dir):
    p = get_portfolio()
    assert p["holdings"] == []


def test_add_holding(isolated_finance_dir):
    h = add_holding({"symbol": "VWCE", "name": "Vanguard All-World", "type": "etf",
                      "units": 50, "cost_basis": 5000, "current_value": 6200})
    assert h["symbol"] == "VWCE"
    assert h["current_value"] == 6200


def test_total_return(isolated_finance_dir):
    add_holding({"symbol": "VWCE", "type": "etf", "cost_basis": 5000, "current_value": 6200})
    add_holding({"symbol": "BND", "type": "bond", "cost_basis": 3000, "current_value": 3100})
    ret = calculate_total_return()
    assert ret["total_gain_loss"] == 1300.0
    assert ret["total_return_pct"] > 0


def test_allocation(isolated_finance_dir):
    add_holding({"symbol": "VWCE", "type": "etf", "current_value": 7000})
    add_holding({"symbol": "BND", "type": "bond", "current_value": 3000})
    alloc = calculate_allocation()
    assert alloc["allocation"]["etf"]["pct"] == 70.0
    assert alloc["allocation"]["bond"]["pct"] == 30.0


def test_rebalance_suggestions(isolated_finance_dir):
    add_holding({"symbol": "VWCE", "type": "etf", "current_value": 8000})
    add_holding({"symbol": "BND", "type": "bond", "current_value": 2000})
    portfolio = get_portfolio()
    portfolio["target_allocation"] = {"etf": 70, "bond": 30}
    from finance_storage import save_json, get_portfolio_path
    save_json(get_portfolio_path(), portfolio)
    suggestions = suggest_rebalance()
    assert len(suggestions) > 0


def test_fire_number(isolated_finance_dir):
    add_holding({"symbol": "VWCE", "type": "etf", "current_value": 100000})
    fire = calculate_fire_number(30000)
    assert fire["fire_number"] == 750000.0
    assert fire["progress_pct"] > 0


def test_project_growth(isolated_finance_dir):
    add_holding({"symbol": "VWCE", "type": "etf", "current_value": 10000})
    proj = project_portfolio_growth(500, annual_return_pct=0.07, years=5)
    assert len(proj) == 5
    assert proj[-1]["balance"] > 10000 + 500 * 60  # growth > just contributions


def test_snapshot(isolated_finance_dir):
    add_holding({"symbol": "VWCE", "type": "etf", "current_value": 5000})
    snap = take_portfolio_snapshot()
    assert snap["total_value"] == 5000


def test_format_display(isolated_finance_dir):
    add_holding({"symbol": "VWCE", "name": "Vanguard", "type": "etf",
                  "cost_basis": 5000, "current_value": 6200})
    display = format_portfolio_display()
    assert "VWCE" in display


def test_project_growth_has_inflation_note(isolated_finance_dir):
    add_holding({"symbol": "VWCE", "type": "etf", "current_value": 10000})
    proj = project_portfolio_growth(500, annual_return_pct=0.07, years=3)
    for year_data in proj:
        assert "inflation_note" in year_data
        assert "real_return_estimate" in year_data
        assert "nominal" in year_data["inflation_note"]
        assert "inflation" in year_data["inflation_note"].lower()


def test_project_growth_real_return_estimate(isolated_finance_dir):
    add_holding({"symbol": "VWCE", "type": "etf", "current_value": 10000})
    proj = project_portfolio_growth(0, annual_return_pct=0.07, years=1)
    # real return at 7% nominal, 2% inflation ≈ 4.9%
    assert abs(proj[0]["real_return_estimate"] - (1.07 / 1.02 - 1)) < 0.001


# ── approximate_xirr convergence ──────────────────────────────────────────────

def test_xirr_converges_for_simple_cashflows():
    """Normal case: Newton's method should converge."""
    cashflows = [
        {"date": "2023-01-01", "amount": -10000},
        {"date": "2023-07-01", "amount": -5000},
    ]
    result = approximate_xirr(cashflows, current_value=16000, as_of="2024-01-01")
    assert result["converged"] is True
    assert result["warning"] is None
    assert result["xirr_pct"] != 0


def test_xirr_convergence_metadata_present():
    """Valid 2-cashflow input converges and includes expected keys."""
    cashflows = [
        {"date": "2023-01-01", "amount": -1000},
        {"date": "2023-07-01", "amount": -500},
    ]
    result = approximate_xirr(cashflows, current_value=1650, as_of="2024-01-01")
    assert "converged" in result
    assert "iterations" in result
    assert "warning" in result


def test_xirr_single_cashflow_returns_error():
    """Single cashflow returns insufficient-data error, not a guess."""
    cashflows = [{"date": "2023-01-01", "amount": -1000}]
    result = approximate_xirr(cashflows, current_value=1100, as_of="2024-01-01")
    assert result["converged"] is False
    assert result["xirr_pct"] is None
    assert "error" in result


def test_xirr_same_date_cashflows_returns_error():
    """All cashflows on the same date as as_of → insufficient data."""
    cashflows = [{"date": "2024-01-01", "amount": -1000}]
    result = approximate_xirr(cashflows, current_value=1100, as_of="2024-01-01")
    assert result["converged"] is False
    assert result["xirr_pct"] is None


def test_xirr_value_does_not_crash_on_insufficient_data():
    """Regression: xirr_value() did result["xirr_pct"] / 100 unconditionally
    — calling it on approximate_xirr's documented "insufficient data"
    result (xirr_pct=None) raised TypeError instead of degrading cleanly."""
    cashflows = [{"date": "2024-01-01", "amount": -1000}]
    result = approximate_xirr(cashflows, current_value=1100, as_of="2024-01-01")
    assert xirr_value(result) is None


def test_xirr_value_helper():
    """xirr_value extracts the decimal rate from a converged result dict."""
    cashflows = [
        {"date": "2023-01-01", "amount": -10000},
        {"date": "2023-06-01", "amount": -2000},
    ]
    result = approximate_xirr(cashflows, current_value=13000, as_of="2024-01-01")
    if result["converged"]:
        val = xirr_value(result)
        assert isinstance(val, float)
        assert abs(val - result["xirr_pct"] / 100) < 1e-9
