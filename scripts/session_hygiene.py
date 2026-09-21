"""
Session-start hygiene: one idempotent pass that keeps the ledger current.

Runs every step independently (a failure in one never blocks the others) and
returns short human-readable notes for anything it changed or found.
"""
from __future__ import annotations


def run() -> list[str]:
    notes: list[str] = []

    try:  # recurring transactions that came due since the last session
        from recurring_engine import generate_due_transactions
        r = generate_due_transactions()
        if r["generated_count"]:
            notes.append(f"Booked {r['generated_count']} recurring transaction(s) that came due.")
    except Exception:
        pass

    try:  # periodic net-worth / portfolio snapshots
        from snapshot_scheduler import check_and_snapshot
        snap = check_and_snapshot()
        if snap.get("snapshots_taken"):
            notes.append("Took a net-worth/portfolio snapshot.")
    except Exception:
        pass

    try:  # current-month budget actuals
        import datetime
        from budget_engine import refresh_budgets
        refresh_budgets([datetime.date.today().isoformat()])
    except Exception:
        pass

    try:  # balance assertions the ledger can't explain
        from reconciliation import check_all, format_alerts
        notes += [f"Reconciliation: {line}" for line in format_alerts(check_all())]
    except Exception:
        pass

    try:  # no launchd off macOS: deliver the weekly digest at session start instead
        import sys
        if sys.platform != "darwin":
            from weekly_digest import days_since_last_digest, run_digest
            from profile_manager import get_profile
            days = days_since_last_digest()
            if days is None or days >= 7:
                notes.append("Weekly digest:\n" + run_digest(get_profile(), notify=False))
    except Exception:
        pass

    return notes
