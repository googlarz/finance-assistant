"""
Monte Carlo simulation engine for Finance Assistant.
Runs N simulations with randomised parameters to produce probability distributions
instead of single-path projections.

All randomisation uses numpy if available, stdlib random as fallback.
"""

from __future__ import annotations

import math
import random as _random
from datetime import datetime
from typing import Optional

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _np = None
    _HAS_NUMPY = False


# ── RNG helpers ──────────────────────────────────────────────────────────────

class _RNG:
    """Thin wrapper: numpy if available, otherwise Box-Muller stdlib fallback."""

    def __init__(self, seed: Optional[int] = None):
        if _HAS_NUMPY:
            self._rng = _np.random.default_rng(seed)
        else:
            self._stdlib = _random.Random(seed)

    def normal(self, mean: float, std: float, size: int = 1) -> list[float]:
        if _HAS_NUMPY:
            return self._rng.normal(mean, std, size).tolist()
        out = []
        while len(out) < size:
            # Box-Muller transform
            u1 = self._stdlib.random()
            u2 = self._stdlib.random()
            if u1 == 0:
                u1 = 1e-10
            z0 = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
            z1 = math.sqrt(-2 * math.log(u1)) * math.sin(2 * math.pi * u2)
            out.append(mean + z0 * std)
            if len(out) < size:
                out.append(mean + z1 * std)
        return out[:size]

    def uniform(self) -> float:
        if _HAS_NUMPY:
            return float(self._rng.random())
        return self._stdlib.random()

    def random_n(self, size: int) -> list[float]:
        if _HAS_NUMPY:
            return self._rng.random(size).tolist()
        return [self._stdlib.random() for _ in range(size)]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ── Simulation helpers ────────────────────────────────────────────────────────

def _build_histogram(values: list[float], n_buckets: int = 10) -> list[dict]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if lo == hi:
        return [{"bucket": f"{lo:.1f}", "count": len(values), "pct": 100.0}]
    width = (hi - lo) / n_buckets
    buckets: list[dict] = []
    for i in range(n_buckets):
        b_lo = lo + i * width
        b_hi = b_lo + width
        label = f"{b_lo:.1f}–{b_hi:.1f}"
        count = sum(1 for v in values if (b_lo <= v < b_hi) or (i == n_buckets - 1 and v == hi))
        buckets.append({"bucket": label, "count": count, "pct": round(count / len(values) * 100, 1)})
    return buckets


def _percentile(sorted_values: list[float], pct: float) -> float:
    """pct in 0–100. Linear interpolation."""
    n = len(sorted_values)
    if n == 0:
        return 0.0
    idx = (pct / 100) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


# ── Per-scenario simulators ───────────────────────────────────────────────────

def _simulate_fire(inputs: dict, n: int, rng: _RNG) -> list[float]:
    """
    Simulate FIRE timeline N times.

    Randomised parameters per simulation:
    - Annual return: Normal(mean=inputs["annual_return"], std=0.12)
      clamped to [-0.40, 0.50] — reflects historical equity volatility
    - Inflation: Normal(mean=inputs.get("inflation_rate", 0.02), std=0.008)
      clamped to [0.0, 0.08]
    - Income growth: Normal(mean=0.02, std=0.015) per year — salary drift
    - Sequence-of-returns risk: apply actual bad year(s) in first 5 years
      of retirement with 15% probability

    Returns list of N values: years_to_fire (float, or 999 if never reached
    within 50 years)
    """
    base_return = float(inputs.get("annual_return", 0.07))
    base_inflation = float(inputs.get("inflation_rate", 0.02))
    current_savings = float(inputs.get("current_savings", 0.0))
    monthly_contribution = float(inputs.get("monthly_contribution", 1000.0))
    annual_expenses = float(inputs.get("annual_expenses", 40000.0))
    withdrawal_rate = float(inputs.get("withdrawal_rate", 0.04))

    # Log-normal: arithmetic mean → geometric mean in log space
    _sigma = 0.12
    _mu_log = math.log(1 + base_return) - 0.5 * _sigma ** 2
    returns = [math.exp(r) - 1 for r in rng.normal(_mu_log, _sigma, n)]
    inflations = rng.normal(base_inflation, 0.008, n)
    income_growths = rng.normal(0.02, 0.015, n)
    seq_risks = rng.random_n(n)

    results = []
    for i in range(n):
        annual_return = _clamp(returns[i], -0.40, 0.50)
        inflation = _clamp(inflations[i], 0.0, 0.08)
        income_growth = _clamp(income_growths[i], -0.05, 0.10)
        has_seq_risk = seq_risks[i] < 0.15

        # Real return
        real_return = (1 + annual_return) / (1 + inflation) - 1
        monthly_return = (1 + real_return) ** (1 / 12) - 1
        fire_number = annual_expenses / withdrawal_rate

        balance = current_savings
        contrib = monthly_contribution
        months = 0
        max_months = 12 * 50
        reached = False

        while months < max_months:
            months += 1
            balance = balance * (1 + monthly_return) + contrib
            # Apply income growth annually
            if months % 12 == 0:
                contrib *= (1 + income_growth)
            if balance >= fire_number:
                reached = True
                break

        if not reached:
            results.append(999.0)
            continue

        years_to_fire = months / 12

        # Sequence-of-returns risk: apply a crash in first 5 retirement years
        # (re-check if still viable after that)
        if has_seq_risk:
            crash_return = _clamp(rng.normal(-0.25, 0.10, 1)[0], -0.40, 0.0)
            real_crash = (1 + crash_return) / (1 + inflation) - 1
            post_balance = balance
            still_ok = True
            for _ in range(60):  # 5 years of monthly withdrawals after crash
                post_balance *= (1 + real_crash / 12)
                post_balance -= annual_expenses / 12
                if post_balance <= 0:
                    still_ok = False
                    break
            if not still_ok:
                # Portfolio depleted: add 3–7 years penalty
                years_to_fire += rng.normal(5.0, 1.5, 1)[0]

        results.append(max(0.0, years_to_fire))

    return results


def _simulate_savings_goal(inputs: dict, n: int, rng: _RNG) -> list[float]:
    """
    Simulate months to reach savings goal N times.

    Randomised:
    - Monthly contribution variance: Normal(mean=inputs["monthly_contribution"],
      std=inputs["monthly_contribution"] * 0.15) — ±15% month-to-month
    - Interest rate (if savings account): Normal(mean=inputs.get("rate", 0.02),
      std=0.005)
    - Income shock: 5% chance per year of one month with zero contribution
      (job loss / emergency)

    Returns list of N values: months_to_goal
    """
    goal = float(inputs.get("goal_amount", 10000.0))
    base_contrib = float(inputs.get("monthly_contribution", 500.0))
    current = float(inputs.get("current_savings", 0.0))
    base_rate = float(inputs.get("rate", 0.02))

    rates = rng.normal(base_rate, 0.005, n)
    results = []

    for i in range(n):
        monthly_rate = _clamp(rates[i], 0.0, 0.12) / 12
        balance = current
        months = 0
        max_months = 12 * 30

        while balance < goal and months < max_months:
            months += 1
            # Income shock: 5% annual = ~0.4% monthly chance
            if rng.uniform() < 0.004:
                contrib = 0.0
            else:
                contrib = max(0.0, rng.normal(base_contrib, base_contrib * 0.15, 1)[0])
            balance = balance * (1 + monthly_rate) + contrib

        results.append(float(months if balance >= goal else max_months))

    return results


def _simulate_debt_payoff(inputs: dict, n: int, rng: _RNG) -> list[float]:
    """
    Simulate months to debt-free N times.

    Randomised:
    - Extra monthly payment: Normal(mean=inputs["extra_monthly"],
      std=inputs["extra_monthly"] * 0.20)
    - Income shock: 8% annual probability of one month minimum-payment-only
    - Interest rate drift: for variable-rate debts, Normal(mean=rate, std=0.005)
      per year

    Returns list of N values: months_to_debt_free
    """
    balance_start = float(inputs.get("balance", 10000.0))
    base_rate = float(inputs.get("interest_rate", 0.05))  # annual
    min_payment = float(inputs.get("min_payment", 200.0))
    extra_monthly = float(inputs.get("extra_monthly", 100.0))
    variable_rate = bool(inputs.get("variable_rate", False))

    results = []
    for _ in range(n):
        balance = balance_start
        months = 0
        max_months = 12 * 30
        annual_rate = base_rate

        while balance > 0 and months < max_months:
            months += 1
            # Annual rate drift for variable rate
            if variable_rate and months % 12 == 0:
                drift = rng.normal(0.0, 0.005, 1)[0]
                annual_rate = _clamp(annual_rate + drift, 0.0, 0.30)

            monthly_rate = annual_rate / 12
            interest = balance * monthly_rate

            # Income shock: 8% annual ~= 0.67% monthly
            if rng.uniform() < 0.0067:
                payment = min_payment
            else:
                extra = max(0.0, rng.normal(extra_monthly, extra_monthly * 0.20, 1)[0])
                payment = min_payment + extra

            balance = max(0.0, balance + interest - payment)

        results.append(float(months if balance <= 0 else max_months))

    return results


def _simulate_net_worth(inputs: dict, n: int, rng: _RNG) -> list[dict]:
    """
    Simulate net worth at each of the next 10 years, N times.

    Randomised per year:
    - Portfolio return: Normal(mean=0.07, std=0.15)
    - Savings rate: Normal(mean=inputs["monthly_savings"]*12, std=inputs["monthly_savings"]*12*0.10)
    - Property appreciation: Normal(mean=0.03, std=0.06) if homeowner

    Returns list of N dicts: {year: net_worth_at_that_year}
    """
    current_net_worth = float(inputs.get("current_net_worth", 0.0))
    monthly_savings = float(inputs.get("monthly_savings", 500.0))
    annual_savings_base = monthly_savings * 12
    property_value = float(inputs.get("property_value", 0.0))
    debt_balance = float(inputs.get("debt_balance", 0.0))
    horizon = int(inputs.get("years", 10))

    results = []
    for _ in range(n):
        nw = current_net_worth
        prop = property_value
        debt = debt_balance
        sim_result = {}

        for yr in range(1, horizon + 1):
            _pmu = math.log(1 + 0.07) - 0.5 * 0.15 ** 2
            port_return = math.exp(rng.normal(_pmu, 0.15, 1)[0]) - 1
            annual_savings = max(0.0, rng.normal(annual_savings_base, annual_savings_base * 0.10, 1)[0])

            # Portfolio portion grows
            investable = max(0.0, nw - prop + debt)
            investable_growth = investable * _clamp(port_return, -0.50, 0.50)

            # Property appreciation
            prop_before = prop
            if prop > 0:
                prop_return = rng.normal(0.03, 0.06, 1)[0]
                prop *= (1 + _clamp(prop_return, -0.20, 0.30))
            property_gain = prop - prop_before

            # Debt reduction (simplified: 5% of balance per year via repayments)
            debt_before = debt
            debt = max(0.0, debt * 0.95)
            debt_reduction = debt_before - debt  # shrinking a liability raises net worth

            # property_gain/debt_reduction used to feed only next year's
            # `investable` base via prop/debt, never actually crediting nw —
            # appreciation and debt paydown were silently discarded from the
            # running net-worth total every year.
            nw = nw + investable_growth + annual_savings + property_gain + debt_reduction
            sim_result[yr] = round(nw, 2)

        results.append(sim_result)

    return results


# ── Main simulate function ────────────────────────────────────────────────────

def simulate(
    scenario_type: str,
    base_inputs: dict,
    n_simulations: int = 10_000,
    seed: int = None,
) -> dict:
    """
    Run N Monte Carlo simulations for the given scenario.

    scenario_type: "fire" | "savings_goal" | "debt_payoff" | "net_worth"

    Returns:
    {
      "scenario_type": str,
      "n_simulations": int,
      "percentiles": {
        "p10": <outcome at 10th percentile>,
        "p25": <outcome at 25th percentile>,
        "p50": <outcome at 50th percentile — median>,
        "p75": <outcome at 75th percentile>,
        "p90": <outcome at 90th percentile>,
      },
      "probability": {
        "success": float,   # e.g. P(retire by target year)
        "failure": float,
        "description": str  # e.g. "87.3% chance of reaching FIRE by 2043"
      },
      "histogram": [{"bucket": str, "count": int, "pct": float}],  # 10 buckets
      "inputs_used": dict,
      "assumptions": [str],  # plain-language list of what was randomised
    }
    """
    rng = _RNG(seed=seed)
    current_year = datetime.now().year

    if scenario_type == "fire":
        raw = _simulate_fire(base_inputs, n_simulations, rng)
        valid = [v for v in raw if v < 999]
        success_count = len(valid)
        success_rate = success_count / n_simulations

        sorted_all = sorted(raw)
        p10 = _percentile(sorted_all, 10)
        p25 = _percentile(sorted_all, 25)
        p50 = _percentile(sorted_all, 50)
        p75 = _percentile(sorted_all, 75)
        p90 = _percentile(sorted_all, 90)

        target_year_p50 = current_year + round(p50) if p50 < 999 else None
        desc = (
            f"{success_rate*100:.1f}% chance of reaching FIRE"
            + (f" by {current_year + round(p50)}" if target_year_p50 else " within 50 years")
        )

        histogram_values = [v for v in raw if v < 999]
        if not histogram_values:
            histogram_values = raw

        assumptions = [
            "Annual returns: log-normal, geometric mean {:.0f}% ± 12% (historical equity volatility)".format(
                base_inputs.get("annual_return", 0.07) * 100
            ),
            "Inflation: avg {:.0f}% ± 0.8%".format(
                base_inputs.get("inflation_rate", 0.02) * 100
            ),
            "Income growth: avg 2% ± 1.5%/year",
            "Sequence-of-returns risk: 15% chance of bad early retirement years",
        ]

        return {
            "scenario_type": scenario_type,
            "n_simulations": n_simulations,
            "percentiles": {
                "p10": round(p10, 1),
                "p25": round(p25, 1),
                "p50": round(p50, 1),
                "p75": round(p75, 1),
                "p90": round(p90, 1),
            },
            "probability": {
                "success": round(success_rate, 4),
                "failure": round(1 - success_rate, 4),
                "description": desc,
            },
            "histogram": _build_histogram(histogram_values),
            "inputs_used": dict(base_inputs),
            "assumptions": assumptions,
        }

    elif scenario_type == "savings_goal":
        raw = _simulate_savings_goal(base_inputs, n_simulations, rng)
        sorted_raw = sorted(raw)
        max_months = 12 * 30
        success_count = sum(1 for v in raw if v < max_months)
        success_rate = success_count / n_simulations

        desc = f"{success_rate*100:.1f}% chance of reaching savings goal"

        assumptions = [
            "Monthly contribution: avg {:.0f} ± 15% month-to-month".format(
                base_inputs.get("monthly_contribution", 500)
            ),
            "Interest rate: avg {:.1f}% ± 0.5%".format(
                base_inputs.get("rate", 0.02) * 100
            ),
            "Income shock: 5% annual chance of one zero-contribution month",
        ]

        return {
            "scenario_type": scenario_type,
            "n_simulations": n_simulations,
            "percentiles": {
                "p10": round(_percentile(sorted_raw, 10), 1),
                "p25": round(_percentile(sorted_raw, 25), 1),
                "p50": round(_percentile(sorted_raw, 50), 1),
                "p75": round(_percentile(sorted_raw, 75), 1),
                "p90": round(_percentile(sorted_raw, 90), 1),
            },
            "probability": {
                "success": round(success_rate, 4),
                "failure": round(1 - success_rate, 4),
                "description": desc,
            },
            "histogram": _build_histogram(raw),
            "inputs_used": dict(base_inputs),
            "assumptions": assumptions,
        }

    elif scenario_type == "debt_payoff":
        raw = _simulate_debt_payoff(base_inputs, n_simulations, rng)
        sorted_raw = sorted(raw)
        max_months = 12 * 30
        success_count = sum(1 for v in raw if v < max_months)
        success_rate = success_count / n_simulations

        desc = f"{success_rate*100:.1f}% chance of becoming debt-free within 30 years"

        assumptions = [
            "Extra monthly payment: avg {:.0f} ± 20%".format(
                base_inputs.get("extra_monthly", 100)
            ),
            "Income shock: 8% annual chance of one minimum-payment-only month",
            "Interest rate drift: ±0.5%/year (variable rate)" if base_inputs.get("variable_rate") else "Fixed interest rate",
        ]

        return {
            "scenario_type": scenario_type,
            "n_simulations": n_simulations,
            "percentiles": {
                "p10": round(_percentile(sorted_raw, 10), 1),
                "p25": round(_percentile(sorted_raw, 25), 1),
                "p50": round(_percentile(sorted_raw, 50), 1),
                "p75": round(_percentile(sorted_raw, 75), 1),
                "p90": round(_percentile(sorted_raw, 90), 1),
            },
            "probability": {
                "success": round(success_rate, 4),
                "failure": round(1 - success_rate, 4),
                "description": desc,
            },
            "histogram": _build_histogram(raw),
            "inputs_used": dict(base_inputs),
            "assumptions": assumptions,
        }

    elif scenario_type == "net_worth":
        raw_list = _simulate_net_worth(base_inputs, n_simulations, rng)
        horizon = int(base_inputs.get("years", 10))

        # Build percentiles per year and summarise final year
        final_values = [sim[horizon] for sim in raw_list if horizon in sim]
        sorted_final = sorted(final_values)

        target = base_inputs.get("target_net_worth")
        if target:
            success_count = sum(1 for v in final_values if v >= float(target))
            success_rate = success_count / n_simulations
            desc = f"{success_rate*100:.1f}% chance of reaching target net worth of {target:,.0f} in {horizon} years"
        else:
            success_rate = 1.0
            desc = f"Net worth projection over {horizon} years"

        assumptions = [
            "Portfolio return: avg 7% ± 15%/year",
            "Annual savings: avg {:.0f} ± 10%".format(base_inputs.get("monthly_savings", 500) * 12),
            "Property appreciation: avg 3% ± 6%/year (if homeowner)",
        ]

        return {
            "scenario_type": scenario_type,
            "n_simulations": n_simulations,
            "percentiles": {
                "p10": round(_percentile(sorted_final, 10), 2),
                "p25": round(_percentile(sorted_final, 25), 2),
                "p50": round(_percentile(sorted_final, 50), 2),
                "p75": round(_percentile(sorted_final, 75), 2),
                "p90": round(_percentile(sorted_final, 90), 2),
            },
            "probability": {
                "success": round(success_rate, 4),
                "failure": round(1 - success_rate, 4),
                "description": desc,
            },
            "histogram": _build_histogram(final_values),
            "inputs_used": dict(base_inputs),
            "assumptions": assumptions,
        }

    else:
        raise ValueError(f"Unknown scenario_type: {scenario_type!r}. Use 'fire', 'savings_goal', 'debt_payoff', or 'net_worth'.")


# ── Format function ───────────────────────────────────────────────────────────

def format_simulation_result(result: dict, currency: str = "EUR") -> str:
    """
    Plain-text summary of Monte Carlo result.

    Example output for FIRE:
      Monte Carlo FIRE Analysis (10,000 simulations)
      ─────────────────────────────────────────────
      Success rate: 87.3% retire by 2043

      Retirement year distribution:
        Best case  (10%): 2038
        Likely     (25%): 2040
        Median     (50%): 2043  ← most likely
        Cautious   (75%): 2047
        Worst case (90%): 2053
    """
    stype = result.get("scenario_type", "unknown")
    n = result.get("n_simulations", 0)
    pct = result.get("percentiles", {})
    prob = result.get("probability", {})
    assumptions = result.get("assumptions", [])
    current_year = datetime.now().year

    label_map = {
        "fire": "FIRE Analysis",
        "savings_goal": "Savings Goal Analysis",
        "debt_payoff": "Debt Payoff Analysis",
        "net_worth": "Net Worth Projection",
    }
    title = f"Monte Carlo {label_map.get(stype, stype.title())} ({n:,} simulations)"
    sep = "─" * len(title)

    lines = [title, sep, ""]
    lines.append(f"Success rate: {prob.get('description', '')}")
    lines.append("")

    if stype == "fire":
        lines.append("Retirement year distribution:")
        for label, key, note in [
            ("Best case  (10%)", "p10", ""),
            ("Likely     (25%)", "p25", ""),
            ("Median     (50%)", "p50", "  ← most likely"),
            ("Cautious   (75%)", "p75", ""),
            ("Worst case (90%)", "p90", ""),
        ]:
            v = pct.get(key, 0)
            year_str = str(current_year + round(v)) if v < 999 else "never (within 50 yrs)"
            lines.append(f"  {label}: {year_str}{note}")
    elif stype == "savings_goal":
        lines.append("Months to reach goal:")
        for label, key, note in [
            ("Best case  (10%)", "p10", ""),
            ("Likely     (25%)", "p25", ""),
            ("Median     (50%)", "p50", "  ← most likely"),
            ("Cautious   (75%)", "p75", ""),
            ("Worst case (90%)", "p90", ""),
        ]:
            v = pct.get(key, 0)
            lines.append(f"  {label}: {round(v)} months{note}")
    elif stype == "debt_payoff":
        lines.append("Months to become debt-free:")
        for label, key, note in [
            ("Best case  (10%)", "p10", ""),
            ("Likely     (25%)", "p25", ""),
            ("Median     (50%)", "p50", "  ← most likely"),
            ("Cautious   (75%)", "p75", ""),
            ("Worst case (90%)", "p90", ""),
        ]:
            v = pct.get(key, 0)
            lines.append(f"  {label}: {round(v)} months{note}")
    elif stype == "net_worth":
        lines.append(f"Net worth in {result['inputs_used'].get('years', 10)} years ({currency}):")
        for label, key, note in [
            ("Best case  (10%)", "p10", ""),
            ("Likely     (25%)", "p25", ""),
            ("Median     (50%)", "p50", "  ← most likely"),
            ("Cautious   (75%)", "p75", ""),
            ("Worst case (90%)", "p90", ""),
        ]:
            v = pct.get(key, 0)
            lines.append(f"  {label}: {currency} {v:,.0f}{note}")

    if assumptions:
        lines.append("")
        lines.append("What was randomised:")
        for a in assumptions:
            lines.append(f"  • {a}")

    return "\n".join(lines)


# ── Integration wrappers ──────────────────────────────────────────────────────

def run_fire_monte_carlo(profile: dict) -> dict:
    """
    Build inputs from profile and run Monte Carlo FIRE simulation.
    Returns simulation result dict.
    """
    inputs = {
        "current_savings": float(profile.get("current_savings", 0.0)),
        "monthly_contribution": float(profile.get("monthly_savings", 1000.0)),
        "annual_expenses": float(profile.get("annual_expenses", profile.get("monthly_expenses", 3000.0) * 12)),
        "annual_return": float(profile.get("expected_return", 0.07)),
        "inflation_rate": float(profile.get("inflation_rate", 0.02)),
        "withdrawal_rate": float(profile.get("withdrawal_rate", 0.04)),
    }
    return simulate("fire", inputs)


def run_savings_goal_monte_carlo(profile: dict, goal_amount: float = None) -> dict:
    """
    Build inputs from profile and run Monte Carlo savings goal simulation.
    Returns simulation result dict.
    """
    inputs = {
        "goal_amount": float(goal_amount or profile.get("savings_goal", 10000.0)),
        "monthly_contribution": float(profile.get("monthly_savings", 500.0)),
        "current_savings": float(profile.get("current_savings", 0.0)),
        "rate": float(profile.get("savings_rate", 0.02)),
    }
    return simulate("savings_goal", inputs)


def run_debt_payoff_monte_carlo(profile: dict) -> dict:
    """
    Build inputs from profile and run Monte Carlo debt payoff simulation.
    Returns simulation result dict.
    """
    total_debt = float(profile.get("total_debt", 0.0))
    inputs = {
        "balance": total_debt,
        "interest_rate": float(profile.get("debt_interest_rate", 0.05)),
        "min_payment": float(profile.get("min_debt_payment", total_debt * 0.02)),
        "extra_monthly": float(profile.get("extra_debt_payment", 100.0)),
        "variable_rate": bool(profile.get("variable_rate_debt", False)),
    }
    return simulate("debt_payoff", inputs)
