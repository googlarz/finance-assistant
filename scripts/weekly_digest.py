"""
Finance Assistant Weekly Digest.

Generates a self-contained financial summary that runs via launchd cron —
no Claude session required. Covers the domains that matter most week-to-week:
budget pacing, upcoming deadlines, portfolio drift, FIRE progress, inbox.

Called by: python3 skill.py --digest
Installed by: python3 skill.py --setup-digest
Writes to: ~/.finance/digest_log.jsonl (for history)
Sends: macOS OS notification with a one-line summary
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from finance_storage import get_finance_dir, load_json, save_json
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import get_finance_dir, load_json, save_json


# ── Budget summary ────────────────────────────────────────────────────────────

def _budget_summary(today: date) -> list[str]:
    import calendar
    year, month = today.year, today.month
    days_in_month = calendar.monthrange(year, month)[1]
    days_remaining = days_in_month - today.day
    month_progress = today.day / days_in_month

    budget_path = get_finance_dir() / "budgets" / f"{year}-{month:02d}.json"
    budget = load_json(budget_path)
    if not budget:
        return []

    limits = budget.get("category_limits", {})
    actuals_raw = budget.get("actuals", {})
    legacy = budget.get("categories", {})
    if legacy and not limits:
        for cat, data in legacy.items():
            if isinstance(data, dict):
                limits[cat] = data.get("planned", 0)
                actuals_raw[cat] = data.get("actual", 0)

    over, on_track = [], []
    for cat, planned in limits.items():
        if not planned:
            continue
        raw = actuals_raw.get(cat, 0)
        actual = raw.get("spent", 0) if isinstance(raw, dict) else float(raw or 0)
        usage = actual / planned
        if actual > planned:
            over.append(f"{cat} +{actual - planned:.0f}")
        elif usage >= 0.8 and month_progress < 0.75:
            over.append(f"{cat} {usage*100:.0f}%")
        else:
            on_track.append(cat)

    lines = []
    if over:
        lines.append(f"Budget: ⚠ {', '.join(over[:3])}")
    elif on_track:
        lines.append(f"Budget: on track ({len(on_track)} categories, {days_remaining}d left)")
    return lines


# ── Upcoming deadlines ────────────────────────────────────────────────────────

def _deadline_summary(today: date, locale: str = "de") -> list[str]:
    lines = []

    # Tax deadlines (general)
    try:
        from tax_engine import get_tax_deadlines
        for year in [today.year - 1, today.year]:
            for d in get_tax_deadlines(year=year):
                deadline_str = d.get("deadline", "")
                if not deadline_str:
                    continue
                try:
                    dl = date.fromisoformat(deadline_str[:10])
                except ValueError:
                    continue
                days = (dl - today).days
                if 0 <= days <= 45:
                    lines.append(f"Tax: {d.get('label','deadline')} in {days}d")
    except Exception:
        pass

    # US quarterly estimated tax
    if locale == "us":
        try:
            import sys as _sys, os as _os
            _root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
            if _root not in _sys.path:
                _sys.path.insert(0, _root)
            from locales.us.tax_calculator import get_quarterly_deadlines
            seen: set[str] = set()
            for year in [today.year, today.year + 1]:
                try:
                    for d in get_quarterly_deadlines(year):
                        due_str = d.get("due", "")
                        if not due_str or due_str in seen:
                            continue
                        seen.add(due_str)
                        due = date.fromisoformat(due_str)
                        days = (due - today).days
                        if 0 <= days <= 30:
                            lines.append(f"Q{d['quarter']} estimated tax due in {days}d")
                except Exception:
                    pass
        except ImportError:
            pass

    # Savings goal deadlines
    try:
        goals_path = get_finance_dir() / "goals" / "goals.json"
        goals = load_json(goals_path, default={}).get("goals", [])
        for goal in goals:
            dl_str = goal.get("deadline", "")
            if not dl_str:
                continue
            try:
                dl = date.fromisoformat(dl_str[:10])
            except ValueError:
                continue
            days = (dl - today).days
            if 0 <= days <= 30:
                name = goal.get("name", "Goal")
                target = goal.get("target_amount", 0)
                current = goal.get("current_amount", 0)
                pct = int(current / target * 100) if target else 0
                lines.append(f"Goal '{name}' due in {days}d ({pct}% funded)")
    except Exception:
        pass

    return lines


# ── Portfolio & FIRE ──────────────────────────────────────────────────────────

def _portfolio_summary(profile: dict) -> list[str]:
    lines = []

    # Drift
    try:
        from investment_tracker import get_portfolio_drift
        drift = get_portfolio_drift()
        if drift.get("has_target"):
            max_drift = drift.get("max_drift_pct", 0)
            if max_drift >= 10:
                lines.append(f"Portfolio: drift {max_drift:.0f}% off target — rebalance needed")
            elif max_drift >= 5:
                lines.append(f"Portfolio: minor drift {max_drift:.0f}%")
    except Exception:
        pass

    # FIRE progress
    try:
        fire_target = profile.get("preferences", {}).get("fire_target")
        if fire_target:
            portfolio_path = get_finance_dir() / "investments" / "portfolio.json"
            portfolio = load_json(portfolio_path, default={})
            holdings = portfolio.get("holdings", [])
            total = sum(
                h.get("current_value") or h.get("quantity", 0) * h.get("purchase_price", 0)
                for h in holdings
            )
            pct = min(total / fire_target * 100, 100)
            lines.append(f"FIRE: {pct:.1f}% (€{total:,.0f} / €{fire_target:,.0f})")
    except Exception:
        pass

    return lines


# ── Inbox ─────────────────────────────────────────────────────────────────────

def _inbox_summary() -> list[str]:
    try:
        from inbox_scanner import get_pending_items, get_inbox_dir
        pending = get_pending_items()
        if pending:
            return [f"Inbox: {len(pending)} file(s) awaiting import"]
    except Exception:
        pass
    return []


# ── Net worth delta ───────────────────────────────────────────────────────────

def _net_worth_summary(profile: dict) -> list[str]:
    try:
        from net_worth_engine import calculate_net_worth
        nw = calculate_net_worth(profile) or {}
        nw_val = nw.get("net_worth", 0)
        if nw_val:
            return [f"Net worth: €{nw_val:,.0f}"]
    except Exception:
        pass
    return []


# ── Digest builder ────────────────────────────────────────────────────────────

def generate_digest(profile: dict) -> dict:
    """
    Build a weekly digest dict. All failures are silent — digest must not crash.

    Returns:
        {
            "date": "YYYY-MM-DD",
            "sections": [str],          # one line per item
            "notification_line": str,   # ≤ 100 chars for OS notification
        }
    """
    today = date.today()
    locale = profile.get("meta", {}).get("locale", "de")

    sections: list[str] = []
    sections.extend(_net_worth_summary(profile))
    sections.extend(_budget_summary(today))
    sections.extend(_portfolio_summary(profile))
    sections.extend(_deadline_summary(today, locale))
    sections.extend(_inbox_summary())

    if not sections:
        sections = ["All quiet — no alerts this week."]

    # One-line notification (truncated)
    notif = sections[0]
    if len(sections) > 1:
        notif += f" (+{len(sections) - 1} more)"
    notification_line = notif[:100]

    return {
        "date": today.isoformat(),
        "sections": sections,
        "notification_line": notification_line,
    }


# ── Output formatters ─────────────────────────────────────────────────────────

def format_digest_full(digest: dict) -> str:
    """Multi-line formatted digest for log file / verbose output."""
    lines = [f"Finance Assistant — Weekly Digest ({digest['date']})", "─" * 48]
    lines.extend(f"  {s}" for s in digest["sections"])
    lines.append("─" * 48)
    return "\n".join(lines)


def format_digest_notification(digest: dict) -> str:
    """Single line for OS notification body."""
    return digest["notification_line"]


# ── Delivery ──────────────────────────────────────────────────────────────────

def _send_notification(title: str, body: str) -> None:
    try:
        import subprocess
        safe_body = body.replace('"', "'")
        script = (
            f'display notification "{safe_body}" '
            f'with title "{title}" subtitle "Weekly digest"'
        )
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass


def _write_log(digest: dict) -> None:
    log_path = Path.home() / ".finance" / "digest_log.jsonl"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(),
                **digest,
            }) + "\n")
    except Exception:
        pass


def run_digest(profile: dict, notify: bool = True, verbose: bool = False) -> str:
    """
    Run the full digest cycle: generate → log → notify → return formatted output.
    """
    digest = generate_digest(profile)
    _write_log(digest)
    if notify:
        _send_notification("Finance Assistant", format_digest_notification(digest))
    output = format_digest_full(digest)
    if verbose:
        print(output)
    return output
