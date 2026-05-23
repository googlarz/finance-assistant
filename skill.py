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

__version__ = "3.6.0"

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

    # Phase 3: two-tier monitor output
    try:
        from session_alerts import get_session_alerts
        from financial_monitor import build_monitor_context, format_monitor_output
        alerts = get_session_alerts(profile)
        if alerts:
            context = build_monitor_context(profile, alerts)
            monitor_output = format_monitor_output(context)
            if monitor_output:
                return profile_display + "\n\n" + monitor_output
    except Exception:
        # Fall back to legacy flat alerts
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


def _setup_watcher() -> None:
    """Install a launchd WatchPaths plist to watch ~/.finance/inbox/ on macOS."""
    import pathlib
    import subprocess

    skill_path = pathlib.Path(__file__).resolve()
    inbox_dir = pathlib.Path.home() / ".finance" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    label = "com.financeassistant.inbox-watcher"
    plist_path = pathlib.Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{skill_path}</string>
        <string>--scan-inbox</string>
    </array>
    <key>WatchPaths</key>
    <array>
        <string>{inbox_dir}</string>
    </array>
    <key>StandardOutPath</key>
    <string>{pathlib.Path.home()}/.finance/inbox-watcher.log</string>
    <key>StandardErrorPath</key>
    <string>{pathlib.Path.home()}/.finance/inbox-watcher-error.log</string>
</dict>
</plist>"""

    print("Inbox watcher plist:")
    print("─" * 60)
    print(plist_content)
    print("─" * 60)
    print(f"\nWill install to: {plist_path}")
    print(f"Watches: {inbox_dir}")
    print(f"\nProceed? [y/N] ", end="", flush=True)

    try:
        response = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return
    if response != "y":
        print("Aborted.")
        return

    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist_content)
    print(f"\n✓ Plist written to {plist_path}")

    try:
        subprocess.run(["launchctl", "load", str(plist_path)], check=True)
        print("✓ Watcher loaded by launchd.")
        print(f"\nDrop files into {inbox_dir} — Finance Assistant will detect them automatically.")
    except subprocess.CalledProcessError as exc:
        print(f"⚠  launchctl load failed: {exc}")
        print(f"Try manually: launchctl load {plist_path}")
    except FileNotFoundError:
        print("(launchctl not found — are you on macOS?)")
        print("Plist is ready; activate with: launchctl load", plist_path)


def _setup_digest() -> None:
    """Install a launchd StartCalendarInterval plist for weekly digest delivery."""
    import pathlib
    import subprocess

    skill_path = pathlib.Path(__file__).resolve()
    label = "com.financeassistant.weekly-digest"
    plist_path = pathlib.Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"

    # Sunday 09:00 weekly
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{skill_path}</string>
        <string>--digest</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{pathlib.Path.home()}/.finance/digest.log</string>
    <key>StandardErrorPath</key>
    <string>{pathlib.Path.home()}/.finance/digest-error.log</string>
</dict>
</plist>"""

    print("Weekly digest plist (fires Sunday 09:00):")
    print("─" * 60)
    print(plist_content)
    print("─" * 60)
    print(f"\nWill install to: {plist_path}")
    print("\nProceed? [y/N] ", end="", flush=True)

    try:
        response = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return
    if response != "y":
        print("Aborted.")
        return

    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist_content)
    print(f"\n✓ Plist written to {plist_path}")

    try:
        subprocess.run(["launchctl", "load", str(plist_path)], check=True)
        print("✓ Weekly digest scheduled (Sundays 09:00).")
        print("  Run `python3 skill.py --digest` now to test it.")
    except subprocess.CalledProcessError as exc:
        print(f"⚠  launchctl load failed: {exc}")
    except FileNotFoundError:
        print("(launchctl not found — are you on macOS?)")


def _setup_ambient_context() -> None:
    """Install a PreCompact hook that injects a compact financial snapshot."""
    import json
    import pathlib

    settings_path = pathlib.Path.home() / ".claude" / "settings.json"
    try:
        existing = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    except Exception:
        existing = {}

    skill_path = pathlib.Path(__file__).resolve()
    hook_cmd = (
        f"python3 {skill_path} --ambient-snapshot 2>/dev/null | "
        r"jq -Rs '{hookSpecificOutput:{hookEventName:\"PreCompact\",additionalContext:.}}'"
    )

    hooks = existing.setdefault("hooks", {})
    pre_compact = hooks.setdefault("PreCompact", [])
    # Avoid duplicates
    for entry in pre_compact:
        for h in entry.get("hooks", []):
            if "ambient-snapshot" in h.get("command", ""):
                print("Ambient context hook already installed.")
                return

    pre_compact.append({
        "matcher": "manual",
        "hooks": [{"type": "command", "command": hook_cmd, "timeout": 10}],
    })

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(existing, indent=2))
    print(f"✓ Ambient context hook added to {settings_path}")
    print("  On every /compact, a brief financial snapshot will be injected.")
    print("  Remove by editing hooks.PreCompact in ~/.claude/settings.json")


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"finance-assistant {__version__}")
        sys.exit(0)

    if "--doctor" in sys.argv:
        from doctor import run_checks, format_results
        checks = run_checks()
        print(format_results(checks))
        sys.exit(0 if all(c["status"] != "fail" for c in checks) else 1)

    if "--scan-inbox" in sys.argv:
        # Called by launchd WatchPaths when inbox folder changes
        from inbox_scanner import scan_inbox
        result = scan_inbox()
        if result["new_files"]:
            print(f"Inbox: {len(result['new_files'])} new file(s) queued")
        sys.exit(0)

    if "--inbox" in sys.argv:
        from inbox_scanner import format_inbox_status
        print(format_inbox_status())
        sys.exit(0)

    if "--setup-watcher" in sys.argv:
        _setup_watcher()
        sys.exit(0)

    if "--setup-ambient-context" in sys.argv:
        _setup_ambient_context()
        sys.exit(0)

    if "--alert-stats" in sys.argv:
        from alert_telemetry import format_alert_stats
        days = 30
        for i, arg in enumerate(sys.argv):
            if arg == "--days" and i + 1 < len(sys.argv):
                try:
                    days = int(sys.argv[i + 1])
                except ValueError:
                    pass
        print(format_alert_stats(days))
        sys.exit(0)

    if "--clear-suppression" in sys.argv:
        from alert_telemetry import clear_suppression
        domain = None
        for i, arg in enumerate(sys.argv):
            if arg == "--domain" and i + 1 < len(sys.argv):
                domain = sys.argv[i + 1]
        n = clear_suppression(domain)
        label = f" for domain '{domain}'" if domain else ""
        print(f"Cleared {n} suppressed condition(s){label}.")
        sys.exit(0)

    if "--digest" in sys.argv:
        _setup_db()
        profile = get_profile() or {}
        from weekly_digest import run_digest
        run_digest(profile, notify=True, verbose=True)
        sys.exit(0)

    if "--setup-digest" in sys.argv:
        _setup_digest()
        sys.exit(0)

    if "--ambient-snapshot" in sys.argv:
        _setup_db()
        profile = get_profile()
        if profile:
            from financial_monitor import get_ambient_snapshot
            snapshot = get_ambient_snapshot(profile)
            if snapshot:
                print(snapshot)
        sys.exit(0)

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
