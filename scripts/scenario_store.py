"""
Finance Assistant Scenario Store — Save & Recall Named Scenarios.

Persists named scenario results to .finance/scenarios/{slug}.json so users
can revisit, compare, and track how a plan has changed over time.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

try:
    from finance_storage import ensure_subdir, get_finance_dir, load_json, save_json
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import ensure_subdir, get_finance_dir, load_json, save_json


# ── Helpers ──────────────────────────────────────────────────────────────────

def _scenarios_dir() -> Path:
    return ensure_subdir("scenarios")


def _slug(name: str) -> str:
    """Convert a scenario name to a filesystem-safe slug."""
    return re.sub(r"[^a-z0-9_]", "_", name.lower().strip()).strip("_")


def _scenario_path(name: str) -> Path:
    return _scenarios_dir() / f"{_slug(name)}.json"


def _profile_snapshot(profile_snapshot: Optional[dict]) -> dict:
    """Extract key metrics from a profile snapshot for storage."""
    if not profile_snapshot:
        return {}
    snap = {}
    for key in ("net_worth", "portfolio_value", "debt_total", "savings_rate",
                "emergency_fund_months", "fire_pct"):
        if key in profile_snapshot:
            snap[key] = profile_snapshot[key]
    return snap


# ── Public API ───────────────────────────────────────────────────────────────

def save_scenario(
    name: str,
    scenario_type: str,
    inputs: dict,
    result: dict,
    profile_snapshot: Optional[dict] = None,
) -> dict:
    """
    Save a named scenario to .finance/scenarios/{slug}.json.

    slug = name.lower().replace(" ", "_")
    Stores: name, type, inputs, result, saved_at, profile_snapshot (key metrics only).
    Returns the saved record.
    """
    record = {
        "name": name,
        "slug": _slug(name),
        "type": scenario_type,
        "inputs": inputs,
        "result": result,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "profile_snapshot": _profile_snapshot(profile_snapshot),
    }
    _scenarios_dir()  # ensure dir exists
    path = _scenario_path(name)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def load_scenario(name: str) -> Optional[dict]:
    """Load scenario by name (fuzzy match on slug). Returns None if not found."""
    target = _slug(name)
    scenarios_dir = _scenarios_dir()
    # Exact match first
    exact = scenarios_dir / f"{target}.json"
    if exact.exists():
        try:
            return json.loads(exact.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    # Fuzzy: find files whose slug starts with or contains target
    for path in sorted(scenarios_dir.glob("*.json")):
        slug_on_disk = path.stem
        if target in slug_on_disk or slug_on_disk.startswith(target):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
    return None


def list_scenarios() -> list[dict]:
    """List all saved scenarios with name, type, saved_at, one-line summary."""
    results = []
    for path in sorted(_scenarios_dir().glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        # Build a one-line summary from the result dict
        result_data = record.get("result", {})
        summary_parts = []
        for key in ("years_to_fire", "recommendation", "best_option", "net_worth",
                    "monthly_payment", "total_interest"):
            val = result_data.get(key)
            if val is not None:
                if isinstance(val, dict):
                    val = val.get("label") or val.get("estimated_annual_net") or str(val)
                summary_parts.append(f"{key}={val}")
            if len(summary_parts) >= 2:
                break
        summary = "; ".join(str(s) for s in summary_parts) if summary_parts else "—"
        results.append({
            "name": record.get("name", path.stem),
            "type": record.get("type", "unknown"),
            "saved_at": record.get("saved_at", ""),
            "summary": summary,
            "slug": record.get("slug", path.stem),
        })
    results.sort(key=lambda r: r.get("saved_at", ""))
    return results


def delete_scenario(name: str) -> bool:
    """Delete a scenario by name. Returns True if deleted."""
    # Try exact slug first, then fuzzy load
    target = _slug(name)
    exact = _scenarios_dir() / f"{target}.json"
    if exact.exists():
        exact.unlink()
        return True
    # Fuzzy
    for path in _scenarios_dir().glob("*.json"):
        if target in path.stem or path.stem.startswith(target):
            path.unlink()
            return True
    return False


def compare_scenario_to_current(name: str, current_profile: dict) -> Optional[dict]:
    """
    Load a saved scenario and compare its profile_snapshot to current profile.

    Returns:
        {
          "scenario_name": str,
          "saved_at": str,
          "days_ago": int,
          "changes_since_saved": {
            "net_worth_delta": float,
            "portfolio_delta": float,
            "debt_delta": float,
            "notes": [str]
          },
          "original_result": dict
        }
    """
    record = load_scenario(name)
    if record is None:
        return None

    saved_at_str = record.get("saved_at", "")
    try:
        saved_at = datetime.fromisoformat(saved_at_str)
        days_ago = (datetime.now() - saved_at).days
    except (ValueError, TypeError):
        days_ago = 0

    snap = record.get("profile_snapshot", {})
    # Current metrics — accept a flat dict or nested under common keys
    def _get(profile: dict, key: str) -> Optional[float]:
        if key in profile:
            return float(profile[key])
        # Also check a nested "metrics" key
        metrics = profile.get("metrics", {})
        if key in metrics:
            return float(metrics[key])
        return None

    net_worth_old = snap.get("net_worth")
    portfolio_old = snap.get("portfolio_value")
    debt_old = snap.get("debt_total")

    net_worth_now = _get(current_profile, "net_worth")
    portfolio_now = _get(current_profile, "portfolio_value")
    debt_now = _get(current_profile, "debt_total")

    def _delta(old, now) -> Optional[float]:
        if old is not None and now is not None:
            return round(now - old, 2)
        return None

    nw_delta = _delta(net_worth_old, net_worth_now)
    pf_delta = _delta(portfolio_old, portfolio_now)
    debt_delta = _delta(debt_old, debt_now)

    notes: list[str] = []
    if nw_delta is not None:
        direction = "grew" if nw_delta >= 0 else "fell"
        notes.append(f"Net worth {direction} €{abs(nw_delta):,.0f} since this scenario was saved")
    if pf_delta is not None:
        direction = "grew" if pf_delta >= 0 else "fell"
        notes.append(f"Portfolio {direction} €{abs(pf_delta):,.0f}")
    if debt_delta is not None:
        direction = "increased" if debt_delta > 0 else "decreased"
        notes.append(f"Total debt {direction} €{abs(debt_delta):,.0f}")
    if not notes:
        notes.append("No comparable metrics in the saved profile snapshot")

    return {
        "scenario_name": record.get("name", name),
        "saved_at": saved_at_str,
        "days_ago": days_ago,
        "changes_since_saved": {
            "net_worth_delta": nw_delta,
            "portfolio_delta": pf_delta,
            "debt_delta": debt_delta,
            "notes": notes,
        },
        "original_result": record.get("result", {}),
    }


def compare_scenarios(names: list[str]) -> dict:
    """
    Load two or more saved scenarios and return a side-by-side comparison dict.

    Returns:
        {
          "scenarios": [{"name", "type", "saved_at", "inputs", "result", "profile_snapshot"}, ...],
          "diff": {key: [val_a, val_b, ...]},  # numeric keys present in any result
          "missing": [str],                     # names that couldn't be loaded
        }
    """
    loaded = []
    missing = []
    for name in names:
        record = load_scenario(name)
        if record is None:
            missing.append(name)
        else:
            loaded.append(record)

    if not loaded:
        return {"scenarios": [], "diff": {}, "missing": missing}

    # Collect all numeric keys present in any result dict
    all_keys: set[str] = set()
    for record in loaded:
        for k, v in record.get("result", {}).items():
            if isinstance(v, (int, float)):
                all_keys.add(k)

    diff: dict[str, list] = {
        key: [record.get("result", {}).get(key) for record in loaded]
        for key in sorted(all_keys)
    }

    return {
        "scenarios": [
            {
                "name": r.get("name", ""),
                "type": r.get("type", ""),
                "saved_at": r.get("saved_at", ""),
                "inputs": r.get("inputs", {}),
                "result": r.get("result", {}),
                "profile_snapshot": r.get("profile_snapshot", {}),
            }
            for r in loaded
        ],
        "diff": diff,
        "missing": missing,
    }


def format_scenario_comparison(names: list[str]) -> str:
    """Plain-text side-by-side table for two or more saved scenarios."""
    data = compare_scenarios(names)
    scenarios = data["scenarios"]

    if not scenarios:
        missing_str = ", ".join(data["missing"])
        return f"Could not find scenarios: {missing_str}"

    if len(scenarios) == 1:
        return format_scenario_list()

    col_width = max(len(s["name"]) for s in scenarios) + 2
    lines = ["Scenario comparison:"]
    header = "Metric".ljust(28) + "".join(s["name"].ljust(col_width) for s in scenarios)
    lines += [header, "-" * len(header)]
    lines.append("Type".ljust(28) + "".join(s["type"].ljust(col_width) for s in scenarios))

    DISPLAY_KEYS = [
        ("years_to_fire", "Years to FIRE"),
        ("fire_number", "FIRE target"),
        ("monthly_savings_needed", "Monthly savings needed"),
        ("success_probability", "Success probability"),
        ("retirement_age", "Retirement age"),
        ("safe_withdrawal", "Safe withdrawal (yr)"),
        ("net_worth", "Net worth at retirement"),
    ]
    diff = data["diff"]
    shown: set[str] = set()
    for key, label in DISPLAY_KEYS:
        if key not in diff:
            continue
        shown.add(key)
        values = diff[key]
        row = label.ljust(28)
        for val in values:
            if val is None:
                cell = "—"
            elif isinstance(val, float):
                cell = f"{val:,.1f}" if val < 10_000 else f"{val:,.0f}"
            else:
                cell = str(val)
            row += cell.ljust(col_width)
        lines.append(row)

    extras = [k for k in diff if k not in shown]
    if extras:
        lines.append("\nOther metrics:")
        for key in extras:
            values = diff[key]
            row = key.ljust(28) + "".join(
                (f"{v:,.2f}" if isinstance(v, float) else str(v) if v is not None else "—").ljust(col_width)
                for v in values
            )
            lines.append(row)

    if data["missing"]:
        lines.append(f"\n(Could not load: {', '.join(data['missing'])})")

    return "\n".join(lines)


def format_scenario_list() -> str:
    """Plain-text list of saved scenarios with type, age, one-liner."""
    items = list_scenarios()
    if not items:
        return "No saved scenarios yet. After any calculation say 'save as [name]' to keep it."

    lines = ["Saved scenarios:"]
    for item in items:
        saved_at = item.get("saved_at", "")
        try:
            saved_dt = datetime.fromisoformat(saved_at)
            days_ago = (datetime.now() - saved_dt).days
            age = f"{days_ago}d ago" if days_ago > 0 else "today"
        except (ValueError, TypeError):
            age = "unknown age"
        lines.append(
            f"  • {item['name']} [{item['type']}] — {age} — {item['summary']}"
        )
    return "\n".join(lines)
