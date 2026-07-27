"""
Tests for scripts/timeline_engine.py — time-series analysis engine.
Uses an in-memory SQLite DB for all tests.
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
import os
from datetime import date, timedelta

import pytest

# Make scripts/ importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
for p in (PROJECT_ROOT, SCRIPTS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from timeline_engine import (
    _mean,
    _stdev,
    _rolling_mean,
    _linear_regression,
    _pearson_r,
    get_monthly_summary,
    compute_trend,
    detect_seasonality,
    compute_correlations,
    detect_anomalies,
    compute_velocity,
    find_inflection_points,
    build_timeline_context,
    _generate_narrative_bullets,
)
from db import init_db, SCHEMA


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mem_conn():
    """In-memory SQLite connection with the full Finance Assistant schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    yield conn
    conn.close()


def _insert_tx(conn, date_str: str, amount: float, category: str = "food", account_id: str = "acc1", type: str = "expense"):
    import uuid
    conn.execute(
        "INSERT INTO transactions (id, account_id, date, amount, currency, category, description, type, created_at) "
        "VALUES (?, ?, ?, ?, 'EUR', ?, 'test', ?, ?)",
        (str(uuid.uuid4()), account_id, date_str, amount, category, type, date_str),
    )
    conn.commit()


def _insert_snapshot(conn, stype: str, date_str: str, data: dict):
    conn.execute(
        "INSERT INTO snapshots (type, date, data) VALUES (?, ?, ?)",
        (stype, date_str, json.dumps(data)),
    )
    conn.commit()


# ── Math Helpers ──────────────────────────────────────────────────────────────

def test_mean_basic():
    assert _mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)


def test_mean_empty():
    assert _mean([]) == 0.0


def test_stdev_basic():
    # sample stdev (ddof=1) of this sequence
    result = _stdev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
    assert result == pytest.approx(2.138, rel=0.01)


def test_stdev_too_few():
    assert _stdev([5.0]) == 0.0


def test_rolling_mean():
    result = _rolling_mean([1.0, 2.0, 3.0, 4.0, 5.0], window=3)
    assert result[2] == pytest.approx(2.0)
    assert result[4] == pytest.approx(4.0)


def test_linear_regression_flat():
    slope, intercept, r2 = _linear_regression([5.0, 5.0, 5.0, 5.0])
    assert slope == pytest.approx(0.0, abs=1e-9)
    assert r2 == pytest.approx(0.0, abs=1e-9)


def test_linear_regression_up():
    slope, _intercept, r2 = _linear_regression([0.0, 1.0, 2.0, 3.0, 4.0])
    assert slope == pytest.approx(1.0)
    assert r2 == pytest.approx(1.0)


def test_pearson_r_perfect_positive():
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [2.0, 4.0, 6.0, 8.0]
    assert _pearson_r(xs, ys) == pytest.approx(1.0)


def test_pearson_r_perfect_negative():
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [8.0, 6.0, 4.0, 2.0]
    assert _pearson_r(xs, ys) == pytest.approx(-1.0)


def test_pearson_r_no_variance():
    assert _pearson_r([1.0, 1.0, 1.0], [2.0, 3.0, 4.0]) == 0.0


# ── get_monthly_summary ───────────────────────────────────────────────────────

def test_get_monthly_summary_empty(mem_conn):
    result = get_monthly_summary(mem_conn, months=3)
    assert isinstance(result, list)
    assert len(result) == 3
    for m in result:
        assert m["income"] == 0.0
        assert m["expenses"] == 0.0
        assert m["net_worth"] is None


def test_get_monthly_summary_with_data(mem_conn):
    today = date.today()
    year, month = today.year, today.month
    ym = f"{year}-{month:02d}"
    date_str = f"{ym}-15"

    _insert_tx(mem_conn, date_str, 3000.0, "salary")   # income
    _insert_tx(mem_conn, date_str, -500.0, "food")     # expense
    _insert_tx(mem_conn, date_str, -200.0, "transport")

    result = get_monthly_summary(mem_conn, months=1)
    assert len(result) == 1
    m = result[0]
    assert m["month"] == ym
    assert m["income"] == pytest.approx(3000.0)
    assert m["expenses"] == pytest.approx(700.0)
    assert m["net"] == pytest.approx(2300.0)
    assert m["savings_rate"] == pytest.approx(2300 / 3000, rel=0.001)
    assert "food" in m["by_category"]
    assert m["by_category"]["food"] == pytest.approx(500.0)


def test_get_monthly_summary_excludes_transfers(mem_conn):
    """Issue #7: transfers/investment/debt_payment rows must not count as
    income or expense in the monthly timeline summary."""
    today = date.today()
    year, month = today.year, today.month
    ym = f"{year}-{month:02d}"
    date_str = f"{ym}-15"

    _insert_tx(mem_conn, date_str, 3000.0, "salary")
    _insert_tx(mem_conn, date_str, -500.0, "food")
    _insert_tx(mem_conn, date_str, 10000.0, "savings", type="transfer")
    _insert_tx(mem_conn, date_str, -2000.0, "brokerage", type="investment")
    _insert_tx(mem_conn, date_str, -300.0, "loan", type="debt_payment")

    result = get_monthly_summary(mem_conn, months=1)
    m = result[0]
    assert m["income"] == pytest.approx(3000.0)
    assert m["expenses"] == pytest.approx(500.0)


def test_get_monthly_summary_net_worth_snapshot(mem_conn):
    today = date.today()
    ym = f"{today.year}-{today.month:02d}"
    snap_date = f"{ym}-28"
    _insert_snapshot(mem_conn, "net_worth", snap_date, {"net_worth": 50000.0, "total_assets": 60000.0, "total_liabilities": 10000.0})

    result = get_monthly_summary(mem_conn, months=1)
    assert result[0]["net_worth"] == pytest.approx(50000.0)


def test_get_monthly_summary_portfolio_snapshot(mem_conn):
    today = date.today()
    ym = f"{today.year}-{today.month:02d}"
    _insert_snapshot(mem_conn, "portfolio", f"{ym}-20", {"total_value": 18000.0})

    result = get_monthly_summary(mem_conn, months=1)
    assert result[0]["portfolio_value"] == pytest.approx(18000.0)


# ── compute_trend ─────────────────────────────────────────────────────────────

def test_compute_trend_up():
    trend = compute_trend([10.0, 20.0, 30.0, 40.0, 50.0])
    assert trend["direction"] == "up"
    assert trend["slope"] > 0
    assert trend["r_squared"] == pytest.approx(1.0, abs=0.01)


def test_compute_trend_down():
    trend = compute_trend([50.0, 40.0, 30.0, 20.0, 10.0])
    assert trend["direction"] == "down"
    assert trend["slope"] < 0


def test_compute_trend_flat():
    trend = compute_trend([100.0, 100.0, 100.0, 100.0])
    assert trend["direction"] == "flat"
    assert trend["slope"] == pytest.approx(0.0, abs=0.001)


def test_compute_trend_too_short():
    trend = compute_trend([42.0])
    assert trend["direction"] == "flat"
    assert trend["slope"] == 0.0


# ── detect_seasonality ────────────────────────────────────────────────────────

def _make_seasonal_data(months: int = 24) -> list[dict]:
    """Build 24 months with a December spending spike (2x average)."""
    today = date.today()
    result = []
    for i in range(months):
        d = date(today.year - (i + 1) // 12, ((today.month - 1 - i) % 12) + 1, 1)
        ym = f"{d.year}-{d.month:02d}"
        base = 500.0
        spending = base * 2.0 if d.month == 12 else base
        result.append({
            "month": ym,
            "income": 3000.0,
            "expenses": spending,
            "net": 3000.0 - spending,
            "savings_rate": (3000.0 - spending) / 3000.0,
            "by_category": {"food": spending * 0.4, "gifts": spending * 0.6},
            "net_worth": None,
            "portfolio_value": None,
        })
    return result


def test_detect_seasonality_december_spike():
    data = _make_seasonal_data(24)
    result = detect_seasonality(data, "expenses")
    assert result["has_seasonality"] is True
    assert result["peak_month"] == 12
    assert result["peak_vs_average_pct"] > 14.0  # December is notably above average


def test_detect_seasonality_not_enough_data():
    data = _make_seasonal_data(10)
    result = detect_seasonality(data, "expenses")
    assert result["has_seasonality"] is False


def test_detect_seasonality_flat():
    data = [{"month": f"2024-{m:02d}", "expenses": 500.0, "by_category": {}, "income": 3000.0, "net": 2500.0, "savings_rate": 0.83, "net_worth": None, "portfolio_value": None} for m in range(1, 13)]
    data += [{"month": f"2023-{m:02d}", "expenses": 500.0, "by_category": {}, "income": 3000.0, "net": 2500.0, "savings_rate": 0.83, "net_worth": None, "portfolio_value": None} for m in range(1, 13)]
    result = detect_seasonality(data, "expenses")
    assert result["has_seasonality"] is False


# ── compute_correlations ──────────────────────────────────────────────────────

def test_compute_correlations_perfect_positive():
    data = [
        {"month": f"2024-{i:02d}", "income": float(i * 1000), "expenses": float(i * 500),
         "net": float(i * 500), "savings_rate": 0.5, "net_worth": float(i * 5000),
         "portfolio_value": float(i * 2000), "by_category": {}}
        for i in range(1, 13)
    ]
    results = compute_correlations(data)
    # income vs expenses should show strong positive correlation
    ie = next((r for r in results if set([r["metric_a"], r["metric_b"]]) == {"income", "expenses"}), None)
    assert ie is not None
    assert ie["strength"] == "strong"
    assert ie["direction"] == "positive"


def test_compute_correlations_too_few():
    data = [{"month": "2024-01", "income": 3000.0, "expenses": 1000.0, "net": 2000.0, "savings_rate": 0.67, "net_worth": 10000.0, "portfolio_value": None, "by_category": {}}]
    assert compute_correlations(data) == []


# ── detect_anomalies ──────────────────────────────────────────────────────────

def _anomaly_data() -> list[dict]:
    """12 months with one obvious outlier in month 6."""
    data = []
    for i in range(12):
        ym = f"2024-{i+1:02d}"
        expenses = 500.0 if i != 5 else 5000.0  # huge spike in June
        data.append({
            "month": ym,
            "income": 3000.0,
            "expenses": expenses,
            "net": 3000.0 - expenses,
            "savings_rate": (3000.0 - expenses) / 3000.0,
            "by_category": {},
            "net_worth": None,
            "portfolio_value": None,
        })
    return data


def test_detect_anomalies_finds_outlier():
    data = _anomaly_data()
    result = detect_anomalies(data, "expenses", sigma=2.0)
    assert len(result) >= 1
    spike = result[0]
    assert spike["direction"] == "above"
    assert spike["value"] == pytest.approx(5000.0)
    assert spike["deviation_sigma"] > 2.0


def test_detect_anomalies_empty_when_no_outliers():
    data = [{"month": f"2024-{i:02d}", "expenses": 500.0, "income": 3000.0, "net": 2500.0, "savings_rate": 0.83, "by_category": {}, "net_worth": None, "portfolio_value": None} for i in range(1, 13)]
    result = detect_anomalies(data, "expenses", sigma=2.0)
    assert result == []


def test_detect_anomalies_too_few_data():
    data = [{"month": "2024-01", "expenses": 500.0, "income": 3000.0, "net": 2500.0, "savings_rate": 0.83, "by_category": {}, "net_worth": None, "portfolio_value": None}]
    result = detect_anomalies(data, "expenses")
    assert result == []


# ── compute_velocity ──────────────────────────────────────────────────────────

def test_compute_velocity_accelerating():
    # Second half grows faster
    series = [1.0, 2.0, 3.0, 4.0, 6.0, 9.0, 13.0, 18.0]
    assert compute_velocity(series) == "accelerating"


def test_compute_velocity_decelerating():
    # First half grows faster
    series = [18.0, 13.0, 9.0, 6.0, 4.0, 3.0, 2.0, 1.0]
    # Negative slope shrinking in magnitude = decelerating
    series2 = [1.0, 5.0, 9.0, 12.0, 14.0, 15.5, 16.5, 17.0]
    result = compute_velocity(series2)
    assert result == "decelerating"


def test_compute_velocity_stable():
    # Perfect linear = same slope both halves
    series = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    assert compute_velocity(series) == "stable"


def test_compute_velocity_reversing():
    series = [1.0, 2.0, 3.0, 4.0, 3.0, 2.0, 1.0, 0.0]
    assert compute_velocity(series) == "reversing"


def test_compute_velocity_too_short():
    assert compute_velocity([1.0, 2.0]) == "stable"


# ── find_inflection_points ────────────────────────────────────────────────────

def test_find_inflection_points_peak():
    series = [1.0, 2.0, 5.0, 10.0, 5.0, 2.0, 1.0, 0.5, 0.3, 0.1]
    months = [f"2024-{i:02d}" for i in range(1, len(series) + 1)]
    pts = find_inflection_points(series, months)
    peaks = [p for p in pts if p["type"] == "peak"]
    assert len(peaks) >= 1
    assert peaks[0]["value"] == pytest.approx(10.0)


def test_find_inflection_points_too_short():
    series = [1.0, 2.0, 3.0]
    months = ["2024-01", "2024-02", "2024-03"]
    assert find_inflection_points(series, months) == []


# ── build_timeline_context ────────────────────────────────────────────────────

def test_build_timeline_context_no_data(monkeypatch, tmp_path):
    """With an empty DB, should return minimal structure."""
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    result = build_timeline_context(months=3)
    assert "monthly_summary" in result
    assert "narrative_bullets" in result
    assert isinstance(result["narrative_bullets"], list)
    assert len(result["narrative_bullets"]) >= 1


def test_build_timeline_context_structure_with_data(monkeypatch, tmp_path):
    """With some data, should return full context structure."""
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    # Init DB and add data
    from db import init_db, get_conn
    init_db()

    today = date.today()
    import uuid

    with get_conn() as conn:
        for month_offset in range(4):
            d = today.replace(day=15)
            for _ in range(month_offset):
                d = d.replace(day=1) - timedelta(days=1)
                d = d.replace(day=15)
            date_str = d.strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO transactions (id, account_id, date, amount, currency, category, description, created_at) VALUES (?, 'acc1', ?, 3000.0, 'EUR', 'salary', 'salary', ?)",
                (str(uuid.uuid4()), date_str, date_str),
            )
            conn.execute(
                "INSERT INTO transactions (id, account_id, date, amount, currency, category, description, created_at) VALUES (?, 'acc1', ?, -800.0, 'EUR', 'food', 'food', ?)",
                (str(uuid.uuid4()), date_str, date_str),
            )

    result = build_timeline_context(months=6)
    assert "monthly_summary" in result
    assert "trends" in result
    assert "correlations" in result
    assert "anomalies" in result
    assert "velocity" in result
    assert "inflection_points" in result
    assert "narrative_bullets" in result


# ── _generate_narrative_bullets ───────────────────────────────────────────────

def test_generate_narrative_bullets_returns_list():
    bullets = _generate_narrative_bullets([], {}, {}, {}, {})
    assert isinstance(bullets, list)
    assert 1 <= len(bullets) <= 5


def test_generate_narrative_bullets_count():
    trends = {
        "expenses": {"direction": "up", "slope": 50.0, "r_squared": 0.9, "pct_change_per_period": 8.0},
        "income": {"direction": "up", "slope": 20.0, "r_squared": 0.8, "pct_change_per_period": 3.0},
        "net_worth": {"direction": "up", "slope": 500.0, "r_squared": 0.95, "pct_change_per_period": 2.0},
        "savings_rate": {"direction": "flat", "slope": 0.0, "r_squared": 0.0, "pct_change_per_period": 0.0},
        "portfolio_value": {"direction": "up", "slope": 300.0, "r_squared": 0.7, "pct_change_per_period": 1.5},
        "by_category": {},
    }
    anomalies = {
        "expenses": [{"month": "2024-06", "value": 5000.0, "mean": 800.0, "deviation_sigma": 3.2, "direction": "above"}],
    }
    velocity = {"expenses": "accelerating", "net_worth": "stable"}
    monthly_data = [{"month": "2024-01", "expenses": 800.0}]
    bullets = _generate_narrative_bullets(monthly_data, trends, anomalies, velocity, {})
    assert 3 <= len(bullets) <= 5
    assert all(isinstance(b, str) for b in bullets)
