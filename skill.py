"""
Finance Assistant Skill — entry point for Claude Code.

This file is the skill entry point that was missing in the original TaxDE.
It bootstraps the scripts/ directory and provides the initial session hook.
"""

import sys
import os

# Ensure scripts/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))

from profile_manager import get_profile, display_profile
from onboarding import (
    is_onboarding_complete, get_current_step, get_step_prompt,
    get_resume_message, get_completion_message, get_onboarding_state,
)

__version__ = "3.2.0"

_timeline_ctx: dict = {}


def _setup_db() -> None:
    """Bootstrap SQLite DB and run migration on first run."""
    global _timeline_ctx
    try:
        from db import init_db, is_initialized
        from db_migrate import migrate_all
        from finance_storage import get_finance_dir

        if not is_initialized():
            init_db()
            finance_dir = get_finance_dir()
            migrate_all(finance_dir)
        else:
            init_db()  # ensure schema is current (no-op if up to date)
    except Exception as exc:
        import sys
        print(f"[Finance Assistant] Warning: DB bootstrap failed: {exc}", file=sys.stderr)

    # Load timeline context if there is enough history
    try:
        from timeline_engine import build_timeline_context, get_monthly_summary
        from db import get_conn
        with get_conn() as conn:
            summary = get_monthly_summary(conn, months=3)
        # Count months that have any transactions
        populated = [m for m in summary if m["income"] > 0 or m["expenses"] > 0]
        if len(populated) >= 3:
            _timeline_ctx = build_timeline_context(months=24)
    except Exception:
        pass  # Timeline must never crash the skill


def get_timeline_context() -> dict:
    """Return the cached timeline context (or empty dict if not loaded)."""
    return _timeline_ctx


def _setup_security_defaults() -> None:
    """Run once-per-session security hygiene: gitignore guard + permission check."""
    try:
        from data_safety import ensure_gitignore_protection, check_permissions
        ensure_gitignore_protection()
        result = check_permissions()
        if result.get("status") == "insecure":
            # Non-fatal — just surface a hint in the session log
            print(
                "[Finance Assistant] Warning: some .finance/ files have loose permissions. "
                "Run harden_permissions() to restrict access to your OS user only."
            )
    except Exception:
        pass  # Security helpers must never crash the skill


def main() -> str:
    """Called at skill load time. Returns initial greeting or status."""
    _setup_db()
    _setup_security_defaults()
    profile = get_profile()

    # ── Onboarding: new user (no profile created yet) ─────────────────────────
    if not profile or not profile.get("meta", {}).get("created"):
        return (
            "Hey! I'm your Finance Assistant — think of me as a financially literate friend "
            "who can help you make sense of your money: budgets, savings goals, investments, "
            "debt, taxes, the works.\n\n"
            "I keep a private profile with just the essentials — no raw documents, no account "
            "numbers. You can delete everything with one command any time.\n\n"
            + get_step_prompt("basics")
        )

    # ── Onboarding: mid-wizard (profile exists but onboarding incomplete) ─────
    onboarding_state = get_onboarding_state()
    if onboarding_state.get("started") and not is_onboarding_complete():
        return get_resume_message()

    # ── Onboarding: just finished — show completion summary once ──────────────
    if is_onboarding_complete() and not onboarding_state.get("completion_shown"):
        onboarding_state["completion_shown"] = True
        from onboarding import save_onboarding_state
        save_onboarding_state(onboarding_state)
        return get_completion_message(profile)

    profile_display = display_profile(compact=True)

    # Surface proactive alerts after the profile summary
    try:
        from session_alerts import get_session_alerts, format_alerts
        alerts = get_session_alerts(profile)
        if alerts:
            return profile_display + "\n\n" + format_alerts(alerts)
    except Exception:
        pass  # Alerts must never crash the skill

    # Data coach nudge (only when no other alerts to avoid noise)
    try:
        from data_coach import get_unlock_nudge, format_nudge
        nudge = get_unlock_nudge(profile)
        if nudge:
            return profile_display + "\n\n" + format_nudge(nudge)
    except Exception:
        pass

    return profile_display


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"finance-assistant {__version__}")
        sys.exit(0)

    if "--doctor" in sys.argv:
        from doctor import run_checks, format_results
        checks = run_checks()
        print(format_results(checks))
        sys.exit(0 if all(c["status"] != "fail" for c in checks) else 1)

    if "--demo" in sys.argv:
        from scripts.demo_data import seed_demo_data
        from workspace_builder import generate_html_dashboard
        _setup_db()
        seed_demo_data()
        path = os.path.expanduser("~/.finance/dashboard_demo.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        generate_html_dashboard(output_path=path)
        print(f"Demo dashboard: {path}")
        sys.exit(0)

    if "--dashboard" in sys.argv:
        from workspace_builder import generate_html_dashboard
        import pathlib
        out = pathlib.Path.home() / ".finance" / "dashboard.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        _setup_db()
        generate_html_dashboard(output_path=str(out))
        print(str(out))
    else:
        print(main())
