"""
Finance Assistant Alert Telemetry & Suppression.

Tracks which alerts have fired and suppresses unchanged conditions to
prevent alert fatigue without hiding genuinely new information.

Suppression is condition-delta-based, NOT time-based:
  - An alert is suppressed when its condition fingerprint matches the
    last-fired fingerprint for that alert slot.
  - Once the underlying condition changes (drift % moves, new deadline,
    different budget category), the alert fires again immediately.
  - Critical alerts are never suppressed.

Storage:
  Fire log  → <project>/.finance/alert_telemetry/fire_log.jsonl
  Suppression state → <project>/.finance/alert_telemetry/suppression.json
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    from finance_storage import (
        get_alert_telemetry_dir, get_alert_fire_log_path,
        load_json, save_json,
    )
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import (
        get_alert_telemetry_dir, get_alert_fire_log_path,
        load_json, save_json,
    )


def _get_suppression_path() -> Path:
    return get_alert_telemetry_dir() / "suppression.json"


# ── Condition Fingerprinting ──────────────────────────────────────────────────

def _fingerprint(alert: dict) -> str:
    """
    Compute a stable fingerprint of an alert's meaningful condition.

    Domain-specific logic strips volatile parts (exact timestamps, formatting)
    and extracts what actually matters — so "Q2 due in 29 days" and
    "Q2 due in 28 days" don't re-fire the same alert on consecutive days.
    """
    domain = alert.get("domain", "")
    title = alert.get("title", "")
    detail = alert.get("detail", "")
    urgency = alert.get("urgency", "")

    if domain == "budget":
        # Key: category + urgency tier (not the exact % or amount)
        return f"budget|{title}|{urgency}"

    if domain in ("portfolio", "investments"):
        # Key: title + drift percentages rounded to nearest 5%
        import re
        nums = re.findall(r"[+-]?\d+", detail)
        rounded = "|".join(str(round(int(n) / 5) * 5) for n in nums)
        return f"portfolio|{title}|{rounded}"

    if domain == "tax":
        # Key: deadline date extracted from detail
        import re
        date_match = re.search(r"\d{4}-\d{2}-\d{2}|\w+ \d+, \d{4}", detail)
        date_str = date_match.group(0) if date_match else detail[:30]
        return f"tax|{title}|{date_str}"

    if domain == "goals":
        # Key: goal name + urgency tier
        return f"goals|{title}|{urgency}"

    if domain == "recurring":
        # Key: payment name + urgency tier
        return f"recurring|{title}|{urgency}"

    if domain == "inbox":
        # Inbox items are always unique — never suppress
        return f"inbox|{title}|{datetime.now().isoformat()}"

    # Default: hash title + first 60 chars of detail
    raw = f"{domain}|{title}|{detail[:60]}"
    return "h:" + hashlib.md5(raw.encode()).hexdigest()[:12]


# ── Suppression ───────────────────────────────────────────────────────────────

def is_suppressed(alert: dict) -> bool:
    """
    Return True if this alert's condition hasn't changed since it last fired.

    Critical alerts are never suppressed.
    Inbox alerts are never suppressed.
    """
    if alert.get("urgency") == "critical":
        return False
    if alert.get("domain") == "inbox":
        return False

    fp = _fingerprint(alert)
    state = load_json(_get_suppression_path(), default={"fingerprints": {}})
    return fp in state.get("fingerprints", {})


def mark_fired(alert: dict) -> None:
    """Record that an alert fired (passed suppression check)."""
    fp = _fingerprint(alert)
    state = load_json(_get_suppression_path(), default={"fingerprints": {}})
    fps = state.get("fingerprints", {})
    fps[fp] = {
        "title": alert.get("title", ""),
        "domain": alert.get("domain", ""),
        "urgency": alert.get("urgency", ""),
        "fired_at": datetime.now().isoformat(),
    }
    state["fingerprints"] = fps
    save_json(_get_suppression_path(), state)


def clear_suppression(domain: Optional[str] = None) -> int:
    """
    Clear suppression state so all alerts can fire again.
    If domain is given, clears only that domain.
    Returns the number of entries cleared.
    """
    state = load_json(_get_suppression_path(), default={"fingerprints": {}})
    fps = state.get("fingerprints", {})
    if domain:
        to_clear = [k for k, v in fps.items() if v.get("domain") == domain]
    else:
        to_clear = list(fps.keys())
    for k in to_clear:
        del fps[k]
    state["fingerprints"] = fps
    save_json(_get_suppression_path(), state)
    return len(to_clear)


# ── Fire Log ──────────────────────────────────────────────────────────────────

def log_fired(alert: dict) -> None:
    """Append a fired alert record to the JSONL fire log."""
    entry = {
        "ts": datetime.now().isoformat(),
        "domain": alert.get("domain", ""),
        "title": alert.get("title", ""),
        "urgency": alert.get("urgency", ""),
        "fingerprint": _fingerprint(alert),
    }
    log_path = get_alert_fire_log_path()
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Fire log is advisory — never crash for it


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_alert_stats(days: int = 30) -> dict:
    """
    Aggregate alert stats for the last N days from the fire log.

    Returns:
        {
            "total_fired": int,
            "by_domain": {domain: count},
            "suppressed_count": int,
            "suppressed_domains": [str],
        }
    """
    log_path = get_alert_fire_log_path()
    total = 0
    by_domain: dict[str, int] = {}

    if log_path.exists():
        cutoff = datetime.now() - timedelta(days=days)
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts = datetime.fromisoformat(entry.get("ts", ""))
                        if ts >= cutoff:
                            total += 1
                            d = entry.get("domain", "unknown")
                            by_domain[d] = by_domain.get(d, 0) + 1
                    except Exception:
                        pass
        except Exception:
            pass

    state = load_json(_get_suppression_path(), default={"fingerprints": {}})
    fps = state.get("fingerprints", {})
    suppressed_domains = sorted({v.get("domain", "") for v in fps.values()})

    return {
        "total_fired": total,
        "by_domain": by_domain,
        "suppressed_count": len(fps),
        "suppressed_domains": suppressed_domains,
    }


def format_alert_stats(days: int = 30) -> str:
    """Format alert stats for CLI display."""
    stats = get_alert_stats(days)
    lines = [f"**Alert stats (last {days} days):**"]
    lines.append(f"• Total fired: {stats['total_fired']}")
    if stats["by_domain"]:
        for domain, count in sorted(stats["by_domain"].items(), key=lambda x: -x[1]):
            lines.append(f"  · {domain}: {count}")
    sc = stats["suppressed_count"]
    if sc:
        domains = ", ".join(stats["suppressed_domains"]) or "various"
        lines.append(f"• Currently suppressed: {sc} condition(s) ({domains})")
        lines.append("  → Run `python3 skill.py --clear-suppression` to reset.")
    else:
        lines.append("• Currently suppressed: none")
    return "\n".join(lines)
