"""
Session Alerts — proactive nudges surfaced at the start of every session.

Checks six domains and returns a list of actionable alerts ranked by urgency:
  1. Budget overspend warnings (>80% used, >10 days left in month)
  2. Upcoming recurring payments (due in the next 7 days)
  3. Savings goal deadlines (within 30 days and underfunded)
  4. Tax deadlines (within 45 days)
  5. FIRE milestone progress (shown once per month)
  6. User-configured threshold milestones (net worth, portfolio, debt, etc.)

Usage:
    from session_alerts import get_session_alerts, format_alerts
    alerts = get_session_alerts(profile)
    print(format_alerts(alerts))
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Optional

try:
    from finance_storage import load_json, ensure_subdir, get_finance_dir
    from profile_manager import get_profile
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import load_json, ensure_subdir, get_finance_dir
    from profile_manager import get_profile


# ── Alert Model ───────────────────────────────────────────────────────────────

URGENCY_LEVELS = ("critical", "warning", "info")


def _alert(urgency: str, domain: str, title: str, detail: str, action: str = "") -> dict:
    return {
        "urgency": urgency,
        "domain": domain,
        "title": title,
        "detail": detail,
        "action": action,
    }


# ── Budget Alerts ─────────────────────────────────────────────────────────────

def _budget_alerts(today: date) -> list[dict]:
    alerts = []
    year, month = today.year, today.month

    import calendar
    days_in_month = calendar.monthrange(year, month)[1]
    days_elapsed = today.day
    days_remaining = days_in_month - days_elapsed
    month_progress = days_elapsed / days_in_month  # 0..1

    budget_path = get_finance_dir() / "budgets" / f"{year}-{month:02d}.json"
    budget = load_json(budget_path)
    if not budget:
        return alerts

    limits = budget.get("category_limits", {})
    actuals_raw = budget.get("actuals", {})
    # Also support legacy schema: {"categories": {"cat": {"planned": X, "actual": Y}}}
    legacy_cats = budget.get("categories", {})
    if legacy_cats and not limits:
        for cat, data in legacy_cats.items():
            if isinstance(data, dict):
                limits[cat] = data.get("planned", 0)
                actuals_raw[cat] = data.get("actual", 0)
    all_cats = set(limits) | set(actuals_raw)
    for cat in all_cats:
        planned = limits.get(cat, 0)
        actual_entry = actuals_raw.get(cat, 0)
        actual = actual_entry.get("spent", 0) if isinstance(actual_entry, dict) else float(actual_entry or 0)
        if planned <= 0:
            continue

        usage = actual / planned
        overspend = actual > planned

        if overspend:
            over = actual - planned
            alerts.append(_alert(
                "critical", "budget",
                f"Over budget: {cat}",
                f"Spent €{actual:.0f} of €{planned:.0f} planned (+€{over:.0f}, {days_remaining}d left)",
                f"Review {cat} spending and adjust remaining purchases.",
            ))
        elif usage >= 0.9 and days_remaining > 5:
            alerts.append(_alert(
                "warning", "budget",
                f"Budget almost full: {cat}",
                f"Used {usage*100:.0f}% (€{actual:.0f}/€{planned:.0f}) with {days_remaining} days left",
                f"Slow down {cat} spending or increase the budget.",
            ))
        elif usage >= 0.8 and days_remaining > 10 and month_progress < 0.7:
            alerts.append(_alert(
                "warning", "budget",
                f"Pacing fast: {cat}",
                f"Already {usage*100:.0f}% used at {month_progress*100:.0f}% of month",
                f"At this rate you'll overspend {cat} by ~€{(actual/month_progress - planned):.0f}.",
            ))

    return alerts


# ── Recurring Payment Alerts ──────────────────────────────────────────────────

def _recurring_alerts(today: date) -> list[dict]:
    alerts = []
    try:
        from recurring_engine import get_upcoming
    except ImportError:
        return alerts

    upcoming = get_upcoming(days=7)
    for item in upcoming:
        due_str = item.get("due_date", "")
        if not due_str:
            continue
        try:
            due = date.fromisoformat(due_str[:10])
        except ValueError:
            continue
        days_until = (due - today).days
        name = item.get("name", "Payment")
        amount = item.get("amount", 0)
        currency = item.get("currency", "EUR")

        if days_until <= 1:
            urgency = "critical"
            when = "today" if days_until == 0 else "tomorrow"
        elif days_until <= 3:
            urgency = "warning"
            when = f"in {days_until} days"
        else:
            urgency = "info"
            when = f"in {days_until} days"

        alerts.append(_alert(
            urgency, "recurring",
            f"Payment due {when}: {name}",
            f"{currency} {amount:.2f} due {due.strftime('%d %b')}",
            "Ensure sufficient balance in your account.",
        ))

    return alerts


# ── Savings Goal Alerts ───────────────────────────────────────────────────────

def _goal_alerts(today: date) -> list[dict]:
    alerts = []
    goals_path = get_finance_dir() / "goals" / "goals.json"
    goals_data = load_json(goals_path)
    if not goals_data:
        return alerts

    goals = goals_data.get("goals", [])
    for goal in goals:
        deadline_str = goal.get("deadline", "")
        if not deadline_str:
            continue
        try:
            deadline = date.fromisoformat(deadline_str[:10])
        except ValueError:
            continue

        days_until = (deadline - today).days
        if days_until < 0:
            alerts.append(_alert(
                "warning", "goals",
                f"Goal deadline passed: {goal.get('name', 'Unnamed goal')}",
                f"Deadline was {abs(days_until)} day(s) ago — consider updating the target date.",
                f"Review your contribution plan for '{goal.get('name', '')}'.",
            ))
            continue
        if days_until > 45:
            continue

        name = goal.get("name", "Goal")
        target = goal.get("target_amount", 0)
        current = goal.get("current_amount", 0)
        gap = target - current
        currency = goal.get("currency", "EUR")

        if gap <= 0:
            continue  # Already reached

        if days_until <= 7:
            urgency = "critical"
        elif days_until <= 30:
            urgency = "warning"
        else:
            urgency = "info"

        pct = (current / target * 100) if target > 0 else 0
        daily_needed = gap / max(days_until, 1)

        alerts.append(_alert(
            urgency, "goals",
            f"Goal deadline approaching: {name}",
            f"{pct:.0f}% funded ({currency} {current:.0f}/{target:.0f}), {days_until}d left",
            f"Need {currency} {daily_needed:.1f}/day to reach goal by {deadline.strftime('%d %b')}.",
        ))

    return alerts


# ── Tax Deadline Alerts ───────────────────────────────────────────────────────

def _tax_alerts(today: date, locale: str = "de") -> list[dict]:
    alerts = []
    _FILING_ACTIONS = {
        "de": "File via ELSTER or a Steuerberater. Extension (Fristverlängerung) possible.",
        "uk": "File via HMRC Self Assessment online. Late filing penalty applies after 3 months.",
        "fr": "Declare via impots.gouv.fr. Extension may be available for online filers.",
        "nl": "File via Mijn Belastingdienst portal at belastingdienst.nl.",
        "pl": "File via e-Deklaracje or Twój e-PIT at podatki.gov.pl.",
    }
    filing_action = _FILING_ACTIONS.get(locale, "File your tax return before the deadline.")
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from tax_engine import get_tax_deadlines
        for tax_year in [today.year - 1, today.year]:
            deadlines = get_tax_deadlines(year=tax_year)
            for d in deadlines:
                deadline_str = d.get("deadline", "")
                if not deadline_str:
                    continue
                try:
                    deadline = date.fromisoformat(deadline_str[:10])
                except ValueError:
                    continue
                days_until = (deadline - today).days
                if days_until < 0 or days_until > 45:
                    continue
                label = d.get("label", f"{tax_year} tax deadline")
                urgency = "critical" if days_until <= 7 else "warning" if days_until <= 21 else "info"
                alerts.append(_alert(urgency, "tax", f"Tax deadline: {label}",
                    f"Due {deadline.strftime('%d %b %Y')} ({days_until} days)",
                    filing_action))
    except Exception:
        pass
    return alerts


# ── FIRE Progress Alert ───────────────────────────────────────────────────────

def _fire_alert(profile: dict, today: date) -> list[dict]:
    """Show FIRE progress once per month as an info nudge."""
    # Check if we already showed this month
    marker_path = get_finance_dir() / "workspace" / "fire_alert_marker.json"
    marker = load_json(marker_path, default={})
    last_shown = marker.get("last_shown", "")
    this_month = today.strftime("%Y-%m")
    if last_shown == this_month:
        return []

    prefs = profile.get("preferences", {})
    fire_target = prefs.get("fire_target")
    if not fire_target:
        return []

    try:
        portfolio_path = get_finance_dir() / "investments" / "portfolio.json"
        portfolio = load_json(portfolio_path, default={})
        holdings = portfolio.get("holdings", [])
        using_cost_basis = any(h.get("current_value") is None for h in holdings)
        total_invested = sum(
            h.get("current_value") if h.get("current_value") is not None
            else h.get("quantity", 0) * h.get("purchase_price", 0)
            for h in holdings
        )
    except Exception:
        return []

    if total_invested <= 0:
        return []

    pct = min(total_invested / fire_target * 100, 100)
    bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))

    # Update marker so we don't show again this month
    try:
        from finance_storage import save_json
        ensure_subdir("workspace")
        save_json(marker_path, {"last_shown": this_month})
    except Exception:
        pass

    return [_alert(
        "info", "investments",
        f"FIRE progress: {pct:.1f}%",
        f"[{bar}] €{total_invested:,.0f} / €{fire_target:,.0f}",
        ("Portfolio value estimated from cost basis — update current prices for accuracy. " if using_cost_basis else "") + "Keep investing consistently. Review allocation if needed.",
    )]


# ── Threshold Milestone Alerts ────────────────────────────────────────────────

def _threshold_alerts(profile: dict) -> list[dict]:
    """Check user-configured thresholds against current metrics."""
    try:
        from threshold_alerts import check_thresholds, format_threshold_alerts
        from net_worth_engine import calculate_net_worth
        from investment_tracker import get_portfolio
    except ImportError:
        return []

    try:
        nw_data = calculate_net_worth(profile) or {}
        portfolio_data = get_portfolio() or {}
        holdings = portfolio_data.get("holdings", [])
        using_cost_basis = any(h.get("current_value") is None for h in holdings)
        portfolio_value = sum(
            h.get("current_value") if h.get("current_value") is not None
            else h.get("quantity", 0) * h.get("purchase_price", 0)
            for h in holdings
        )

        current_metrics = {
            "net_worth": nw_data.get("net_worth", 0),
            "portfolio_value": portfolio_value,
            "debt_total": nw_data.get("total_liabilities", 0),
        }

        # Add savings_rate and emergency_fund_months from profile if available
        fin = profile.get("financial_summary", {})
        if "savings_rate" in fin:
            current_metrics["savings_rate"] = fin["savings_rate"]
        if "emergency_fund_months" in fin:
            current_metrics["emergency_fund_months"] = fin["emergency_fund_months"]

        triggered = check_thresholds(current_metrics)
        if not triggered:
            return []

        alerts = []
        for item in triggered:
            alerts.append(_alert(
                "info", "milestones",
                f"Milestone: {item.get('label', item['metric'])}",
                f"Current: {item['current']:,.2f} (threshold: {item['threshold']:,.2f}, direction: {item['direction']})",
                "Review your milestone or set a new higher target.",
            ))
        return alerts
    except Exception:
        return []


# ── US Quarterly Estimated Tax Alerts ────────────────────────────────────────

def _quarterly_us_tax_alert(today: date) -> list[dict]:
    """
    Alert US self-employed users when an IRS estimated tax deadline is within 30 days.

    Uses get_quarterly_deadlines() from the US locale — deadlines are already
    stored in tax_rules.py, so no network call is needed.
    """
    alerts = []
    try:
        import os as _os
        import sys as _sys
        _root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from locales.us.tax_calculator import get_quarterly_deadlines  # type: ignore[import]
    except ImportError:
        return alerts

    # Check current year + next year: Q4 of year N is due in January of year N+1.
    # Deduplicate by due date — a year without its own rules falls back to the
    # most-recent known year, which could produce the same deadline twice.
    seen_dues: set[str] = set()
    for year in [today.year, today.year + 1]:
        try:
            deadlines = get_quarterly_deadlines(year)
        except Exception:
            continue
        for d in deadlines:
            due_str = d.get("due", "")
            if not due_str:
                continue
            try:
                due = date.fromisoformat(due_str)
            except ValueError:
                continue
            if due_str in seen_dues:
                continue
            seen_dues.add(due_str)
            days_until = (due - today).days
            if days_until < 0 or days_until > 30:
                continue
            quarter = d.get("quarter", "?")
            period = d.get("period", "")
            if days_until <= 7:
                urgency = "critical"
            elif days_until <= 21:
                urgency = "warning"
            else:
                urgency = "info"
            alerts.append(_alert(
                urgency, "tax",
                f"Q{quarter} estimated tax due in {days_until} day{'s' if days_until != 1 else ''}",
                f"Form 1040-ES · {period} · Due {due.strftime('%b %-d, %Y')}",
                (
                    f"Ask: 'What do I owe for Q{quarter} estimated taxes?' "
                    "then pay at IRS Direct Pay (irs.gov/payments) or EFTPS."
                ),
            ))
    return alerts


# ── Portfolio Drift Alert ─────────────────────────────────────────────────────

def _portfolio_drift_alert(profile: dict) -> list[dict]:
    """
    Alert when any asset class has drifted ≥10% from the target allocation.
    Requires a target_allocation to be set in the portfolio file — silently
    skips if none is configured (no false alarms for users who don't use
    target allocations).
    """
    try:
        from investment_tracker import get_portfolio_drift  # type: ignore[import]
    except ImportError:
        return []
    try:
        drift = get_portfolio_drift()
    except Exception:
        return []

    if not drift.get("has_target"):
        return []

    large_drifts = [d for d in drift.get("drifts", []) if abs(d["drift_pct"]) >= 10]
    if not large_drifts:
        return []

    overweight = [d for d in large_drifts if d["drift_pct"] > 0]
    underweight = [d for d in large_drifts if d["drift_pct"] < 0]
    parts = []
    if overweight:
        parts.append("overweight: " + ", ".join(
            f"{d['asset_type']} (+{d['drift_pct']:.0f}%)" for d in overweight
        ))
    if underweight:
        parts.append("underweight: " + ", ".join(
            f"{d['asset_type']} ({d['drift_pct']:.0f}%)" for d in underweight
        ))

    n = len(large_drifts)
    return [_alert(
        "info", "portfolio",
        f"Portfolio drift: {n} asset class{'es' if n != 1 else ''} off target by ≥10%",
        "; ".join(parts),
        "Say 'show portfolio drift' or 'how should I rebalance?' for a full rebalancing plan.",
    )]


# ── Inbox Alert ──────────────────────────────────────────────────────────────

def _inbox_alert() -> list[dict]:
    """Alert when files are waiting in the inbox for review/import."""
    try:
        from inbox_scanner import get_pending_items
    except ImportError:
        return []
    try:
        pending = get_pending_items()
    except Exception:
        return []
    if not pending:
        return []

    if len(pending) == 1:
        item = pending[0]
        name = item.get("name", "file")
        preview = item.get("preview", {})
        if preview.get("importable"):
            txn = preview.get("transaction_count", "?")
            detail = f"{name} — {txn} transactions ready to import"
        else:
            detail = f"{name} — awaiting review"
        return [_alert(
            "warning", "inbox",
            "File waiting in inbox",
            detail,
            "Say 'show inbox' to preview and import.",
        )]

    return [_alert(
        "warning", "inbox",
        f"{len(pending)} files waiting in inbox",
        "Bank statements or other financial files ready to review",
        "Say 'show inbox' to preview and import all files.",
    )]


# ── Main Entry Point ──────────────────────────────────────────────────────────

def get_session_alerts(profile: Optional[dict] = None) -> list[dict]:
    """
    Return all active session alerts, sorted by urgency then domain.
    Pass in profile dict if already loaded to avoid a second disk read.
    """
    if profile is None:
        profile = get_profile() or {}

    today = date.today()
    locale = profile.get("meta", {}).get("locale", "de")

    all_alerts: list[dict] = []
    all_alerts.extend(_inbox_alert())
    all_alerts.extend(_budget_alerts(today))
    all_alerts.extend(_recurring_alerts(today))
    all_alerts.extend(_goal_alerts(today))
    all_alerts.extend(_tax_alerts(today, locale))
    if locale == "us":
        all_alerts.extend(_quarterly_us_tax_alert(today))
    all_alerts.extend(_fire_alert(profile, today))
    all_alerts.extend(_threshold_alerts(profile))
    all_alerts.extend(_portfolio_drift_alert(profile))

    # Timeline narrative bullets as info alerts
    try:
        from timeline_engine import build_timeline_context
        timeline = build_timeline_context(months=24)
        for bullet in timeline.get("narrative_bullets", []):
            if bullet and "No historical data" not in bullet:
                all_alerts.append(_alert("info", "timeline", "Trend insight", bullet))
    except Exception:
        pass  # Timeline must never crash alerts

    # Accountability nudges
    try:
        from accountability_engine import get_accountability_alerts
        from db import get_conn
        _severity_to_urgency = {"high": "critical", "medium": "warning", "low": "info"}
        with get_conn() as conn:
            for item in get_accountability_alerts(conn):
                urgency = _severity_to_urgency.get(item.get("severity", "low"), "info")
                all_alerts.append(_alert(
                    urgency,
                    "accountability",
                    item.get("message", ""),
                    item.get("suggestion", item.get("detail", "")),
                    item.get("action", ""),
                ))
    except Exception:
        pass  # Accountability must never crash alerts

    # Cash flow overdraft risk alerts
    try:
        from overdraft_detector import get_cashflow_alerts
        from db import get_conn
        with get_conn() as conn:
            for item in get_cashflow_alerts(conn):
                all_alerts.append(_alert(
                    item.get("urgency", "info"),
                    item.get("domain", "cashflow"),
                    item.get("title", "Cash flow alert"),
                    item.get("detail", ""),
                    item.get("action", ""),
                ))
    except Exception:
        pass  # Cashflow alerts must never crash the session

    all_alerts.extend(_data_coach_alerts(profile))

    # Stale portfolio prices nudge
    try:
        from price_sync import get_stale_holding_count
        stale_count, max_age_hours = get_stale_holding_count()
        if stale_count > 0:
            age_str = f"{max_age_hours:.0f}h" if max_age_hours < float("inf") else "never synced"
            all_alerts.append(_alert(
                "info",
                "portfolio",
                f"{stale_count} holding{'s' if stale_count != 1 else ''} with stale prices",
                f"Last updated: {age_str} ago — prices may not reflect current market values.",
                "Say 'sync prices' to refresh before running FIRE or net worth calculations.",
            ))
    except Exception:
        pass  # Never crash the session over a price staleness check

    # Phase 2: telemetry + condition-delta suppression
    # Critical alerts never suppressed. Inbox alerts never suppressed.
    try:
        from alert_telemetry import is_suppressed, mark_fired, log_fired as _log_fired
        to_emit = []
        for alert in all_alerts:
            if not is_suppressed(alert):
                mark_fired(alert)
                _log_fired(alert)
                to_emit.append(alert)
        all_alerts = to_emit
    except Exception:
        pass  # Telemetry must never crash alerts

    # Sort: critical → warning → info, then by domain
    order = {u: i for i, u in enumerate(URGENCY_LEVELS)}
    all_alerts.sort(key=lambda a: (order.get(a["urgency"], 99), a["domain"]))
    return all_alerts


def _data_coach_alerts(profile: dict) -> list[dict]:
    """
    Surface 1-2 insight unlock nudges as info alerts.
    Only shown if user has less than 60% of insights available.
    Suppressed once user has rich data (>=8 insights available).
    """
    try:
        from data_coach import get_available_insights, get_locked_insights, get_unlock_nudge
    except ImportError:
        return []

    try:
        available = get_available_insights(profile)
        if len(available) >= 8:
            return []  # User has rich data — don't nag

        locked = get_locked_insights(profile)
        total = len(available) + len(locked)
        if total > 0 and len(available) / total >= 0.6:
            return []  # Already at 60%+ — no nudge needed

        nudge = get_unlock_nudge(profile)
        if not nudge:
            return []

        return [_alert(
            "info",
            "data_coach",
            "Unlock more insights",
            nudge["lead"],
            nudge["how"],
        )]
    except Exception:
        return []


def format_alerts(alerts: list[dict]) -> str:
    """Format alerts as a concise session-start summary."""
    if not alerts:
        return ""

    icons = {"critical": "[!]", "warning": "[~]", "info": "[i]"}
    lines = ["**Session alerts:**"]
    for a in alerts:
        icon = icons.get(a.get("urgency", "info"), "•")
        detail = a.get("detail", "")
        lines.append(f"{icon} **{a['title']}** — {detail}")
        if a.get("action"):
            lines.append(f"   → {a['action']}")

    return "\n".join(lines)
