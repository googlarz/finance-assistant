"""Tests for scripts/monte_carlo.py"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from monte_carlo import simulate, format_simulation_result


# ── FIRE simulations ──────────────────────────────────────────────────────────

def test_fire_result_has_required_keys():
    result = simulate("fire", {
        "current_savings": 50_000,
        "monthly_contribution": 2_000,
        "annual_expenses": 40_000,
        "annual_return": 0.07,
        "inflation_rate": 0.02,
        "withdrawal_rate": 0.04,
    }, n_simulations=200, seed=42)

    assert result["scenario_type"] == "fire"
    assert result["n_simulations"] == 200
    assert "percentiles" in result
    for key in ("p10", "p25", "p50", "p75", "p90"):
        assert key in result["percentiles"], f"Missing percentile key: {key}"
    assert "probability" in result
    assert "success" in result["probability"]
    assert "failure" in result["probability"]
    assert "description" in result["probability"]
    assert "histogram" in result
    assert "inputs_used" in result
    assert "assumptions" in result


def test_fire_percentiles_ordered():
    result = simulate("fire", {
        "current_savings": 50_000,
        "monthly_contribution": 2_000,
        "annual_expenses": 40_000,
        "annual_return": 0.07,
    }, n_simulations=500, seed=1)
    p = result["percentiles"]
    assert p["p10"] <= p["p50"] <= p["p90"], f"Percentiles not ordered: {p}"
    assert p["p10"] <= p["p25"] <= p["p75"] <= p["p90"]


def test_fire_p50_close_to_deterministic():
    """Median simulation result should be within ±3 years of deterministic projection."""
    from scenario_engine import project_fire_timeline

    inputs = {
        "current_savings": 100_000,
        "monthly_contribution": 2_500,
        "annual_expenses": 50_000,
        "annual_return": 0.07,
        "inflation_rate": 0.02,
        "withdrawal_rate": 0.04,
    }
    result = simulate("fire", inputs, n_simulations=2_000, seed=99)
    p50 = result["percentiles"]["p50"]

    det = project_fire_timeline(
        current_savings=100_000,
        monthly_contribution=2_500,
        annual_expenses=50_000,
        annual_return_pct=0.07,
        withdrawal_rate=0.04,
        inflation_rate=0.02,
    )
    det_years = det["years_to_fire"]

    assert abs(p50 - det_years) <= 3, (
        f"Monte Carlo p50={p50:.1f} too far from deterministic={det_years:.1f}"
    )


def test_fire_success_probability_in_range():
    result = simulate("fire", {
        "current_savings": 50_000,
        "monthly_contribution": 2_000,
        "annual_expenses": 40_000,
    }, n_simulations=300, seed=7)
    prob = result["probability"]["success"]
    assert 0.0 <= prob <= 1.0, f"Success probability out of range: {prob}"
    assert result["probability"]["failure"] == round(1 - prob, 4)


def test_fire_histogram_10_buckets_sum_to_n():
    n = 400
    result = simulate("fire", {
        "current_savings": 80_000,
        "monthly_contribution": 1_500,
        "annual_expenses": 35_000,
    }, n_simulations=n, seed=13)
    hist = result["histogram"]
    assert len(hist) == 10, f"Expected 10 histogram buckets, got {len(hist)}"
    total = sum(b["count"] for b in hist)
    # histogram only includes non-999 values; total may be <= n
    assert total <= n


# ── Savings goal simulations ──────────────────────────────────────────────────

def test_savings_goal_percentiles_ordered_and_positive():
    result = simulate("savings_goal", {
        "goal_amount": 20_000,
        "monthly_contribution": 800,
        "current_savings": 2_000,
        "rate": 0.025,
    }, n_simulations=300, seed=42)
    p = result["percentiles"]
    assert p["p10"] <= p["p50"] <= p["p90"]
    assert p["p10"] > 0
    assert p["p50"] > 0


def test_savings_goal_required_keys():
    result = simulate("savings_goal", {
        "goal_amount": 5_000,
        "monthly_contribution": 400,
    }, n_simulations=100, seed=1)
    for key in ("scenario_type", "n_simulations", "percentiles", "probability", "histogram", "inputs_used", "assumptions"):
        assert key in result


# ── Debt payoff simulations ───────────────────────────────────────────────────

def test_debt_payoff_percentiles_ordered():
    result = simulate("debt_payoff", {
        "balance": 15_000,
        "interest_rate": 0.08,
        "min_payment": 250,
        "extra_monthly": 150,
    }, n_simulations=300, seed=42)
    p = result["percentiles"]
    assert p["p10"] <= p["p50"] <= p["p90"]


def test_debt_payoff_required_keys():
    result = simulate("debt_payoff", {
        "balance": 8_000,
        "interest_rate": 0.06,
        "min_payment": 150,
        "extra_monthly": 80,
    }, n_simulations=100, seed=5)
    for key in ("scenario_type", "n_simulations", "percentiles", "probability", "histogram", "inputs_used", "assumptions"):
        assert key in result


# ── Reproducibility ───────────────────────────────────────────────────────────

def test_seed_produces_identical_results():
    inputs = {
        "current_savings": 60_000,
        "monthly_contribution": 1_800,
        "annual_expenses": 38_000,
    }
    r1 = simulate("fire", inputs, n_simulations=200, seed=42)
    r2 = simulate("fire", inputs, n_simulations=200, seed=42)
    assert r1["percentiles"] == r2["percentiles"], "Same seed should produce identical results"
    assert r1["probability"] == r2["probability"]


def test_different_seeds_produce_different_results():
    inputs = {
        "current_savings": 60_000,
        "monthly_contribution": 1_800,
        "annual_expenses": 38_000,
    }
    r1 = simulate("fire", inputs, n_simulations=500, seed=1)
    r2 = simulate("fire", inputs, n_simulations=500, seed=999)
    # Percentiles should differ (not identical)
    assert r1["percentiles"]["p50"] != r2["percentiles"]["p50"] or \
           r1["percentiles"]["p10"] != r2["percentiles"]["p10"]


# ── format_simulation_result ──────────────────────────────────────────────────

def test_format_fire_contains_simulations():
    result = simulate("fire", {
        "current_savings": 50_000,
        "monthly_contribution": 2_000,
        "annual_expenses": 40_000,
    }, n_simulations=200, seed=42)
    text = format_simulation_result(result)
    assert "simulations" in text.lower()
    assert "%" in text  # success rate


def test_format_fire_contains_percentile_values():
    result = simulate("fire", {
        "current_savings": 50_000,
        "monthly_contribution": 2_000,
        "annual_expenses": 40_000,
    }, n_simulations=200, seed=42)
    text = format_simulation_result(result)
    # Should mention a 4-digit year somewhere in the output (e.g. 2038, 2046...)
    import re
    years_found = re.findall(r"\b20\d{2}\b", text)
    assert len(years_found) > 0, f"No 4-digit year found in output: {text[:200]}"


def test_format_contains_assumptions():
    result = simulate("fire", {
        "current_savings": 50_000,
        "monthly_contribution": 2_000,
        "annual_expenses": 40_000,
        "annual_return": 0.07,
    }, n_simulations=100, seed=1)
    text = format_simulation_result(result)
    assert "randomised" in text.lower() or "what was randomised" in text.lower()
    for assumption in result["assumptions"]:
        # At least some key terms from each assumption appear
        first_word = assumption.split()[0].lower()
        assert first_word in text.lower() or assumption[:10].lower() in text.lower()


def test_format_savings_goal():
    result = simulate("savings_goal", {
        "goal_amount": 10_000,
        "monthly_contribution": 500,
    }, n_simulations=100, seed=42)
    text = format_simulation_result(result)
    assert "simulations" in text.lower()
    assert "months" in text.lower()


# ── Performance guard ─────────────────────────────────────────────────────────

def test_n100_runs_under_1_second_fire():
    start = time.time()
    simulate("fire", {
        "current_savings": 50_000,
        "monthly_contribution": 2_000,
        "annual_expenses": 40_000,
    }, n_simulations=100, seed=42)
    elapsed = time.time() - start
    assert elapsed < 1.0, f"100 FIRE simulations took {elapsed:.2f}s (limit: 1s)"


def test_n100_runs_under_1_second_savings():
    start = time.time()
    simulate("savings_goal", {
        "goal_amount": 10_000,
        "monthly_contribution": 400,
    }, n_simulations=100, seed=42)
    elapsed = time.time() - start
    assert elapsed < 1.0, f"100 savings simulations took {elapsed:.2f}s (limit: 1s)"


def test_n100_runs_under_1_second_debt():
    start = time.time()
    simulate("debt_payoff", {
        "balance": 10_000,
        "interest_rate": 0.06,
        "min_payment": 200,
        "extra_monthly": 100,
    }, n_simulations=100, seed=42)
    elapsed = time.time() - start
    assert elapsed < 1.0, f"100 debt simulations took {elapsed:.2f}s (limit: 1s)"


# ── Net worth: property appreciation / debt paydown must be credited ──────────

def test_net_worth_credits_property_appreciation_and_debt_paydown():
    """Regression: prop/debt were used to derive next year's `investable`
    base but their year-over-year changes (appreciation, paydown) were
    never added into `nw` — property gains and the benefit of a shrinking
    liability were silently discarded from the running net-worth total
    every year."""
    inputs_with_assets = {
        "current_net_worth": 100_000, "property_value": 300_000,
        "debt_balance": 250_000, "monthly_savings": 0, "years": 5,
    }
    inputs_no_assets = {
        "current_net_worth": 100_000, "property_value": 0,
        "debt_balance": 0, "monthly_savings": 0, "years": 5,
    }
    with_assets = simulate("net_worth", inputs_with_assets, n_simulations=500, seed=42)
    no_assets = simulate("net_worth", inputs_no_assets, n_simulations=500, seed=42)

    # ~9k/yr appreciation + ~12.5k/yr debt paydown over 5 years is a large,
    # unmistakable effect — the median must reflect it, not be roughly flat.
    assert with_assets["percentiles"]["p50"] > no_assets["percentiles"]["p50"] + 20_000


# ── Invalid input ─────────────────────────────────────────────────────────────

def test_unknown_scenario_type_raises():
    try:
        simulate("unknown_type", {}, n_simulations=10, seed=1)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "unknown_type" in str(e)
