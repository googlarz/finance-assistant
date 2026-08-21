"""Tests for goal_tracker.py."""
from goal_tracker import (
    get_goals, add_goal, update_goal, delete_goal,
    project_goal_completion, suggest_emergency_fund, format_goals_display,
)
from datetime import date, timedelta


def test_empty_goals(isolated_finance_dir):
    assert get_goals() == []


def test_add_goal(isolated_finance_dir):
    g = add_goal({"name": "Emergency Fund", "type": "emergency_fund",
                   "target_amount": 15000, "current_amount": 3000, "monthly_contribution": 500})
    assert g["name"] == "Emergency Fund"
    assert g["status"] == "active"


def test_update_goal(isolated_finance_dir):
    g = add_goal({"name": "Vacation", "target_amount": 3000})
    updated = update_goal(g["id"], {"current_amount": 1500})
    assert updated["current_amount"] == 1500


def test_delete_goal(isolated_finance_dir):
    g = add_goal({"name": "Test", "target_amount": 1000})
    assert delete_goal(g["id"]) is True
    assert len(get_goals()) == 0


def test_project_completion(isolated_finance_dir):
    g = add_goal({"name": "House", "target_amount": 50000,
                   "current_amount": 10000, "monthly_contribution": 1000})
    proj = project_goal_completion(g["id"])
    assert proj["months_to_go"] == 40.0
    assert proj["pct_complete"] == 20.0
    assert proj["status"] == "on_track"


def test_project_stalled(isolated_finance_dir):
    g = add_goal({"name": "Stalled", "target_amount": 5000, "current_amount": 1000})
    proj = project_goal_completion(g["id"])
    assert proj["status"] == "stalled"
    assert "suggestion" in proj


def test_suggest_emergency_fund():
    suggestion = suggest_emergency_fund(2500, months=6)
    assert suggestion["suggested_target"] == 15000.0
    assert suggestion["months_coverage"] == 6


def test_format_display(isolated_finance_dir):
    add_goal({"name": "Emergency", "type": "emergency_fund",
              "target_amount": 10000, "current_amount": 5000})
    display = format_goals_display()
    assert "Emergency" in display
    assert "50%" in display


# ── DB-present: goals used to be SQLite-frozen after first-boot migration ──

def test_add_goal_db_present_reaches_check_goal_drift(isolated_finance_dir_db):
    """Regression: goals were written to SQLite only once, by the first-boot
    migration — a goal added after that point was invisible to
    accountability_engine.check_goal_drift(), which reads goals SQLite-only."""
    from db import get_conn
    from accountability_engine import check_goal_drift

    created = (date.today() - timedelta(days=180)).isoformat()
    target = (date.today() + timedelta(days=30)).isoformat()
    goal = add_goal({
        "name": "Behind Schedule", "type": "custom",
        "target_amount": 10000, "current_amount": 100,  # way behind pace
        "target_date": target,
    })
    # add_goal stamps created_at itself; overwrite it in both stores so the
    # drift math has a real multi-month history to compare against.
    update_goal(goal["id"], {"created_at": created})

    with get_conn() as conn:
        alerts = check_goal_drift(conn)
    assert any(a["goal_name"] == "Behind Schedule" for a in alerts)


def test_delete_goal_db_present_actually_deletes(isolated_finance_dir_db):
    from db import get_conn
    goal = add_goal({"name": "Test Goal", "type": "custom", "target_amount": 1000})
    assert delete_goal(goal["id"]) is True
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal["id"],)).fetchone()
    assert row is None
