"""
Finance Assistant Proactive Financial Monitor.

Produces two-tier session output:
  Immediate tier — critical/warning alerts: shown in full, demand attention now
  Digest tier    — info alerts: shown compact, useful but not urgent

Cross-session diff:
  Compares current alerts to previous session's snapshot to surface
  what's new ("3 new alerts since 6h ago") and what's resolved.

Inbox integration:
  Pending inbox files always show in the immediate tier.

Ambient snapshot (opt-in only):
  get_ambient_snapshot() produces a terse string for PreCompact hook injection.
  Enable with: python3 skill.py --setup-ambient-context
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

try:
    from finance_storage import get_monitor_state_path, load_json, save_json
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import get_monitor_state_path, load_json, save_json


# ── State persistence ─────────────────────────────────────────────────────────

def _load_state() -> dict:
    return load_json(get_monitor_state_path(), default={
        "last_run": None,
        "last_alert_titles": [],
        "last_inbox_count": 0,
    })


def _save_state(alerts: list[dict], inbox_count: int) -> None:
    save_json(get_monitor_state_path(), {
        "last_run": datetime.now().isoformat(),
        "last_alert_titles": [a["title"] for a in alerts],
        "last_inbox_count": inbox_count,
    })


# ── Monitor context ───────────────────────────────────────────────────────────

def build_monitor_context(profile: dict, alerts: list[dict]) -> dict:
    """
    Partition alerts into tiers and compute cross-session diff.

    Returns:
        {
            "immediate": [alerts],          # critical + warning
            "digest": [alerts],             # info
            "new_since_last": [str],        # titles new this session
            "resolved_since_last": [str],   # titles gone since last session
            "inbox_pending": int,
            "last_run": str | None,
        }
    """
    state = _load_state()
    prev_titles = set(state.get("last_alert_titles", []))
    last_run = state.get("last_run")

    immediate = [a for a in alerts if a.get("urgency") in ("critical", "warning")]
    digest = [a for a in alerts if a.get("urgency") == "info"]

    current_titles = {a["title"] for a in alerts}
    new_since_last = sorted(current_titles - prev_titles)
    resolved_since_last = sorted(prev_titles - current_titles)

    inbox_count = 0
    try:
        from inbox_scanner import get_pending_items
        inbox_count = len(get_pending_items())
    except Exception:
        pass

    _save_state(alerts, inbox_count)

    return {
        "immediate": immediate,
        "digest": digest,
        "new_since_last": new_since_last,
        "resolved_since_last": resolved_since_last,
        "inbox_pending": inbox_count,
        "last_run": last_run,
    }


# ── Formatting ────────────────────────────────────────────────────────────────

def format_monitor_output(context: dict) -> str:
    """
    Format the two-tier monitor output for session start.

    Immediate alerts shown in full.
    Digest shown compact (count + domain summary if > 3 items).
    Cross-session diff shown when there's something meaningful to say.
    """
    lines: list[str] = []
    icons = {"critical": "[!]", "warning": "[~]", "info": "[i]"}

    # ── Cross-session diff ────────────────────────────────────────────────────
    last_run = context.get("last_run")
    if last_run:
        try:
            elapsed = datetime.now() - datetime.fromisoformat(last_run)
            hours = elapsed.total_seconds() / 3600
            since_str = f"{int(hours)}h ago" if hours < 24 else f"{int(hours / 24)}d ago"
        except Exception:
            since_str = "last session"

        new = context.get("new_since_last", [])
        resolved = context.get("resolved_since_last", [])
        diff_parts = []
        if new:
            diff_parts.append(f"{len(new)} new alert{'s' if len(new) != 1 else ''}")
        if resolved:
            diff_parts.append(f"{len(resolved)} resolved")
        if diff_parts:
            lines.append(f"*Since {since_str}: {', '.join(diff_parts)}.*\n")

    # ── Inbox ─────────────────────────────────────────────────────────────────
    inbox_pending = context.get("inbox_pending", 0)
    if inbox_pending:
        lines.append(
            f"[i] **{inbox_pending} file{'s' if inbox_pending != 1 else ''} in inbox** "
            f"— Say 'show inbox' to review and import."
        )

    # ── Immediate tier ────────────────────────────────────────────────────────
    # Cap at the top few so session-open never becomes a wall (SKILL.md §2:
    # "pick the 2-3 things that actually matter"). Critical before warning.
    IMMEDIATE_CAP = 3
    immediate = context.get("immediate", [])
    if immediate:
        immediate = sorted(
            immediate, key=lambda a: 0 if a.get("urgency") == "critical" else 1
        )
        shown, overflow = immediate[:IMMEDIATE_CAP], immediate[IMMEDIATE_CAP:]
        if lines:
            lines.append("")
        lines.append("**Needs attention:**")
        for a in shown:
            icon = icons.get(a.get("urgency", "info"), "•")
            lines.append(f"{icon} **{a['title']}** — {a['detail']}")
            if a.get("action"):
                lines.append(f"   → {a['action']}")
        if overflow:
            lines.append(
                f"   …and {len(overflow)} more — say 'show all alerts' to see everything."
            )

    # ── Digest tier ───────────────────────────────────────────────────────────
    digest = context.get("digest", [])
    if digest:
        if lines:
            lines.append("")
        if len(digest) <= 3:
            lines.append("**Also noted:**")
            for a in digest:
                lines.append(f"[i] {a['title']} — {a['detail']}")
        else:
            # Compact summary by domain
            domains: dict[str, int] = {}
            for a in digest:
                d = a.get("domain", "other")
                domains[d] = domains.get(d, 0) + 1
            summary = ", ".join(
                f"{count} {dom}" for dom, count in sorted(domains.items(), key=lambda x: -x[1])
            )
            lines.append(f"[i] {len(digest)} background items: {summary}")
            lines.append("   Say 'show all alerts' for full details.")

    return "\n".join(lines)


# ── Ambient snapshot (opt-in) ─────────────────────────────────────────────────

def get_ambient_snapshot(profile: dict) -> str:
    """
    Produce a compact financial context string for PreCompact hook injection.

    This is ONLY used when the user explicitly sets up ambient context
    via `python3 skill.py --setup-ambient-context`. Intentionally terse
    to minimize context window impact.
    """
    parts: list[str] = []

    # Net worth
    try:
        from net_worth_engine import calculate_net_worth
        nw = calculate_net_worth(profile) or {}
        nw_val = nw.get("net_worth", 0)
        if nw_val:
            parts.append(f"Net worth: €{nw_val:,.0f}")
    except Exception:
        pass

    # Budget overspend
    today = date.today()
    try:
        from finance_storage import get_finance_dir
        budget_path = get_finance_dir() / "budgets" / f"{today.year}-{today.month:02d}.json"
        budget = load_json(budget_path)
        if budget:
            limits = budget.get("category_limits", {})
            actuals = budget.get("actuals", {})
            overspent = [
                cat for cat, limit in limits.items()
                if float(actuals.get(cat, 0) or 0) > float(limit or 0)
            ]
            if overspent:
                parts.append(f"Over budget: {', '.join(overspent[:3])}")
    except Exception:
        pass

    # Inbox
    try:
        from inbox_scanner import get_pending_items
        pending = get_pending_items()
        if pending:
            parts.append(f"Inbox: {len(pending)} file(s) pending")
    except Exception:
        pass

    if not parts:
        return ""
    return "[Finance: " + " | ".join(parts) + "]"
