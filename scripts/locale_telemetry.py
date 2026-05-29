"""
Locale usage telemetry.

Records which locale is actually used for tax operations — nothing else (no
amounts, no profile data). Exists to make the "law-accurate multi-locale tax"
positioning bet measurable: which locales do real users exercise?

Append-only JSONL at .finance/telemetry/locale_usage.jsonl. Privacy-safe by
construction — only {ts, locale, operation} is recorded.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime
from typing import Optional

try:
    from finance_storage import ensure_subdir
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import ensure_subdir


def _log_path():
    return ensure_subdir("telemetry") / "locale_usage.jsonl"


def record(locale: str, operation: str) -> None:
    """Record one locale usage event. Best-effort; never raises.

    Args:
        locale: locale code (e.g. "de", "us")
        operation: what was done — "tax_estimate" | "tax_claims" | "tax_brief" | "deadlines"
    """
    try:
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "locale": (locale or "unknown")[:8],
            "operation": (operation or "unknown")[:32],
        }
        path = _log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # telemetry must never interfere with the operation


def get_stats() -> dict:
    """Aggregate locale usage. Returns {by_locale: {...}, by_operation: {...}, total: int}."""
    path = _log_path()
    if not path.exists():
        return {"by_locale": {}, "by_operation": {}, "total": 0}
    by_locale: Counter = Counter()
    by_operation: Counter = Counter()
    total = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                by_locale[e.get("locale", "unknown")] += 1
                by_operation[e.get("operation", "unknown")] += 1
                total += 1
    except Exception:
        pass
    return {
        "by_locale": dict(by_locale.most_common()),
        "by_operation": dict(by_operation.most_common()),
        "total": total,
    }


def format_stats() -> str:
    """Human-readable locale usage summary."""
    s = get_stats()
    if not s["total"]:
        return "No locale usage recorded yet. Run a tax calculation to start tracking."
    lines = [f"**Locale usage** ({s['total']} tax operations recorded)\n"]
    lines.append("By locale:")
    for loc, n in s["by_locale"].items():
        pct = n / s["total"] * 100
        lines.append(f"  {loc.upper():<6} {n:>4}  ({pct:.0f}%)")
    lines.append("\nBy operation:")
    for op, n in s["by_operation"].items():
        lines.append(f"  {op:<16} {n:>4}")
    return "\n".join(lines)
