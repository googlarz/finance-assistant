"""
Subscription action tracking — closes the loop on subscription_detector.

The detector (subscription_detector.py) finds recurring charges. This module
lets the user *act* on them: flag a subscription to cancel, get reminded if
it's still charging, and mark it cancelled (logged to the audit trail).

State lives at .finance/subscriptions/actions.json keyed by merchant. Status
machine:  watching → flagged_to_cancel → cancelled
                                       ↘ kept (explicitly decided to keep)

Surfaced via session alerts (still-charging-after-flagged) and the
--subscriptions CLI.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

try:
    from finance_storage import ensure_subdir, load_json, save_json
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import ensure_subdir, load_json, save_json


_VALID_STATUS = {"watching", "flagged_to_cancel", "cancelled", "kept"}


def _actions_path():
    return ensure_subdir("subscriptions") / "actions.json"


def _load() -> dict:
    return load_json(_actions_path(), default={"actions": {}})


def _save(data: dict) -> None:
    save_json(_actions_path(), data)


def _normalize_key(merchant: str) -> str:
    """Stable key for a subscription — lowercased merchant."""
    return (merchant or "").strip().lower()[:60]


def set_action(
    merchant: str,
    status: str,
    *,
    monthly_cost: Optional[float] = None,
    note: str = "",
) -> dict:
    """Record an action decision for a subscription.

    status ∈ {watching, flagged_to_cancel, cancelled, kept}
    Returns the stored action record.
    """
    if status not in _VALID_STATUS:
        raise ValueError(f"Invalid status {status!r}. Must be one of {sorted(_VALID_STATUS)}.")

    key = _normalize_key(merchant)
    if not key:
        raise ValueError("merchant cannot be empty")

    data = _load()
    actions = data.setdefault("actions", {})
    prev = actions.get(key, {})
    record = {
        "merchant": merchant,
        "status": status,
        "monthly_cost": monthly_cost if monthly_cost is not None else prev.get("monthly_cost"),
        "note": note or prev.get("note", ""),
        "flagged_at": prev.get("flagged_at"),
        "cancelled_at": prev.get("cancelled_at"),
        "updated_at": datetime.now().isoformat(),
    }
    if status == "flagged_to_cancel" and not record["flagged_at"]:
        record["flagged_at"] = datetime.now().isoformat()
    if status == "cancelled":
        record["cancelled_at"] = datetime.now().isoformat()

    actions[key] = record
    _save(data)

    # Audit trail
    try:
        from audit_log import log_mutation
        log_mutation(
            action="update",
            target="subscription_action",
            target_id=key,
            before={"status": prev.get("status")} if prev else None,
            after={"status": status, "merchant": merchant},
            source="skill",
        )
    except Exception:
        pass

    return record


def get_action(merchant: str) -> Optional[dict]:
    return _load().get("actions", {}).get(_normalize_key(merchant))


def get_all_actions() -> dict:
    return _load().get("actions", {})


def get_flagged() -> list[dict]:
    """Subscriptions the user flagged to cancel but hasn't confirmed cancelled."""
    return [
        a for a in _load().get("actions", {}).values()
        if a.get("status") == "flagged_to_cancel"
    ]


def still_charging_after_flag(detected_subscriptions: list[dict]) -> list[dict]:
    """Cross-reference flagged subscriptions against freshly detected active ones.

    Returns flagged subscriptions that are STILL being charged — the user
    intended to cancel but money is still going out. This is the high-value
    alert: a forgotten cancellation costing real money.

    Args:
        detected_subscriptions: output of subscription_detector.detect_subscriptions
    """
    flagged_keys = {_normalize_key(a["merchant"]) for a in get_flagged()}
    if not flagged_keys:
        return []

    result = []
    for sub in detected_subscriptions:
        if not sub.get("active"):
            continue
        if _normalize_key(sub.get("merchant", "")) in flagged_keys:
            action = get_action(sub["merchant"])
            result.append({**sub, "flagged_at": action.get("flagged_at") if action else None})
    return result


def format_actions() -> str:
    """Human-readable list of all tracked subscription actions."""
    actions = get_all_actions()
    if not actions:
        return "No subscription actions tracked yet. Flag one with 'cancel <merchant>'."

    by_status: dict[str, list] = {}
    for a in actions.values():
        by_status.setdefault(a.get("status", "watching"), []).append(a)

    labels = {
        "flagged_to_cancel": "⚑ Flagged to cancel",
        "cancelled": "✓ Cancelled",
        "kept": "• Keeping",
        "watching": "· Watching",
    }
    lines = ["**Subscription actions**\n"]
    for status in ("flagged_to_cancel", "cancelled", "kept", "watching"):
        items = by_status.get(status, [])
        if not items:
            continue
        lines.append(f"{labels[status]}:")
        for a in items:
            cost = a.get("monthly_cost")
            cost_str = f" (€{abs(cost):.2f}/mo)" if cost else ""
            note = f" — {a['note']}" if a.get("note") else ""
            lines.append(f"  {a['merchant']}{cost_str}{note}")
        lines.append("")
    return "\n".join(lines).rstrip()
