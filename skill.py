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

__version__ = "3.9.2"

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
            result = migrate_all(finance_dir)
            errors = result.get("errors", []) if isinstance(result, dict) else []
            if errors:
                print(
                    f"[Finance Assistant] Migration completed with {len(errors)} error(s):",
                    file=sys.stderr,
                )
                for err in errors[:5]:
                    print(f"  - {err}", file=sys.stderr)
                if len(errors) > 5:
                    print(f"  ... and {len(errors) - 5} more", file=sys.stderr)
        else:
            init_db()  # ensure schema is current (no-op if up to date)
    except Exception as exc:
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
            "**Want to see what this looks like with sample data first?** Say 'show demo' "
            "and I'll generate a complete sandbox profile with budgets, transactions, "
            "investments, and tax scenarios you can poke at before committing real numbers. "
            "(Demo data is wiped when you start the real onboarding.)\n\n"
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

    # Suppression footer — appended to whatever we return, so the user always
    # learns why the session is quiet (set after get_session_alerts runs).
    def _with_footer(text: str) -> str:
        try:
            from session_alerts import format_suppression_footer
            footer = format_suppression_footer()
            if footer:
                return text + "\n\n" + footer
        except Exception:
            pass
        return text

    # Phase 3: two-tier monitor output
    try:
        from session_alerts import get_session_alerts
        from financial_monitor import build_monitor_context, format_monitor_output
        alerts = get_session_alerts(profile)
        if alerts:
            context = build_monitor_context(profile, alerts)
            monitor_output = format_monitor_output(context)
            if monitor_output:
                return _with_footer(profile_display + "\n\n" + monitor_output)
    except Exception:
        # Fall back to legacy flat alerts
        try:
            from session_alerts import get_session_alerts, format_alerts
            alerts = get_session_alerts(profile)
            if alerts:
                return _with_footer(profile_display + "\n\n" + format_alerts(alerts))
        except Exception:
            pass  # Alerts must never crash the skill

    # Data coach nudge (only when no other alerts to avoid noise)
    try:
        from data_coach import get_unlock_nudge, format_nudge
        nudge = get_unlock_nudge(profile)
        if nudge:
            return _with_footer(profile_display + "\n\n" + format_nudge(nudge))
    except Exception:
        pass

    return _with_footer(profile_display)


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


def _setup_digest(weekday: int = 0, hour: int = 9, minute: int = 0) -> None:
    """Install a launchd StartCalendarInterval plist for weekly digest delivery.

    Args:
        weekday: 0=Sunday, 1=Monday, ..., 6=Saturday (launchd convention)
        hour:    0-23
        minute:  0-59
    """
    import pathlib
    import subprocess

    # Validate inputs — guard against accidental config corruption
    if not (0 <= weekday <= 6):
        print(f"Invalid weekday {weekday} (must be 0=Sunday..6=Saturday)", file=sys.stderr)
        return
    if not (0 <= hour <= 23):
        print(f"Invalid hour {hour} (must be 0-23)", file=sys.stderr)
        return
    if not (0 <= minute <= 59):
        print(f"Invalid minute {minute} (must be 0-59)", file=sys.stderr)
        return

    weekday_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    day_label = weekday_names[weekday]

    skill_path = pathlib.Path(__file__).resolve()
    label = "com.financeassistant.weekly-digest"
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
        <string>--digest</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>{weekday}</integer>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{pathlib.Path.home()}/.finance/digest.log</string>
    <key>StandardErrorPath</key>
    <string>{pathlib.Path.home()}/.finance/digest-error.log</string>
</dict>
</plist>"""

    print(f"Weekly digest plist (fires {day_label} {hour:02d}:{minute:02d}):")
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

    if "--tax-compare" in sys.argv:
        # --tax-compare {filing-status|employment-type|pretax} --gross N
        #   [--year Y] [--contribution C] [--save NAME]
        _setup_db()
        from tax_scenarios import (
            compare_filing_status, compare_employment_type,
            compare_pretax_contribution, format_comparison, save as _save_cmp,
        )
        args = sys.argv

        def _arg(flag, default=None, cast=str):
            for i, a in enumerate(args):
                if a == flag and i + 1 < len(args):
                    try:
                        return cast(args[i + 1])
                    except ValueError:
                        return default
            return default

        kind = _arg("--tax-compare")
        gross = _arg("--gross", 0.0, float)
        year = _arg("--year", None, int)
        contribution = _arg("--contribution", 20000.0, float)
        save_name = _arg("--save")
        profile = get_profile() or {}
        currency = {"de": "EUR", "fr": "EUR", "nl": "EUR", "pl": "PLN",
                    "uk": "GBP", "us": "USD"}.get(
            profile.get("tax_profile", {}).get("locale")
            or profile.get("meta", {}).get("locale", "us"), "USD")

        if not gross:
            print("Usage: --tax-compare {filing-status|employment-type|pretax} --gross N "
                  "[--year Y] [--contribution C] [--save NAME]", file=sys.stderr)
            sys.exit(1)

        if kind == "filing-status":
            cmp = compare_filing_status(gross, year, profile)
        elif kind == "employment-type":
            cmp = compare_employment_type(gross, year, profile)
        elif kind == "pretax":
            cmp = compare_pretax_contribution(gross, contribution, year, profile)
        else:
            print("Unknown comparison. Use: filing-status | employment-type | pretax", file=sys.stderr)
            sys.exit(1)

        print(format_comparison(cmp, currency))
        if save_name:
            _save_cmp(save_name, cmp, profile)
            print(f"\n✓ Saved as '{save_name}' — recall with the scenario tools.")
        sys.exit(0)

    if "--backup" in sys.argv:
        from backup import cli_backup
        cli_backup(sys.argv)
        sys.exit(0)

    if "--backup-restore" in sys.argv:
        from backup import cli_restore
        cli_restore(sys.argv)
        sys.exit(0)

    if "--debt-strategy" in sys.argv:
        _setup_db()
        from debt_optimizer import compare_payoff_strategies, format_debt_display
        extra = 0.0
        for i, arg in enumerate(sys.argv):
            if arg == "--extra" and i + 1 < len(sys.argv):
                try:
                    extra = float(sys.argv[i + 1])
                except ValueError:
                    pass
        print(format_debt_display())
        cmp = compare_payoff_strategies(extra_monthly=extra)
        c = cmp["comparison"]
        a = cmp["avalanche"]
        s = cmp["snowball"]
        print("\nStrategy comparison")
        print(f"  Avalanche : {a['months']} months  |  €{a['total_interest']:,.2f} interest")
        print(f"  Snowball  : {s['months']} months  |  €{s['total_interest']:,.2f} interest")
        print(f"  Avalanche saves €{c['interest_saved_by_avalanche']:,.2f} "
              f"and {c['months_saved_by_avalanche']} month(s)")
        print(f"  Recommendation: {c['recommendation']}")
        sys.exit(0)

    if "--household" in sys.argv:
        _setup_db()
        from household import format_household_summary
        print(format_household_summary())
        sys.exit(0)

    if "--locale-stats" in sys.argv:
        _setup_db()
        from locale_telemetry import format_stats
        print(format_stats())
        sys.exit(0)

    if "--tax-brief" in sys.argv:
        _setup_db()
        from tax_brief import generate as _gen_brief
        year = None
        for i, arg in enumerate(sys.argv):
            if arg == "--year" and i + 1 < len(sys.argv):
                try:
                    year = int(sys.argv[i + 1])
                except ValueError:
                    pass
        path = _gen_brief(get_profile() or {}, year)
        print(f"Tax filing brief written to: {path}")
        sys.exit(0)

    if "--show-suppressed" in sys.argv:
        _setup_db()
        import session_alerts as _sa
        _sa.get_session_alerts(get_profile() or {})  # populates _last_suppressed
        sup = _sa._last_suppressed
        if not sup:
            print("No alerts are currently suppressed.")
        else:
            print(f"**{len(sup)} suppressed alert(s)** (unchanged since last shown):\n")
            for a in sup:
                print(f"[{a.get('urgency','info')}] {a.get('title','')} — {a.get('detail','')}")
            print("\nSay 'clear suppression' or run --clear-suppression to resurface them.")
        sys.exit(0)

    if "--subscriptions" in sys.argv:
        _setup_db()
        from subscription_detector import get_for_account, format_subscriptions
        subs = get_for_account(account_id="default")
        print(format_subscriptions(subs))
        try:
            from subscription_actions import format_actions, get_all_actions
            if get_all_actions():
                print("\n" + format_actions())
        except Exception:
            pass
        sys.exit(0)

    if "--flag-subscription" in sys.argv or "--mark-subscription" in sys.argv:
        # --flag-subscription "Netflix"  → flag to cancel
        # --mark-subscription "Netflix" cancelled|kept|watching
        _setup_db()
        from subscription_actions import set_action
        args = sys.argv
        merchant, status = None, "flagged_to_cancel"
        for i, a in enumerate(args):
            if a == "--flag-subscription" and i + 1 < len(args):
                merchant, status = args[i + 1], "flagged_to_cancel"
            elif a == "--mark-subscription" and i + 1 < len(args):
                merchant = args[i + 1]
                status = args[i + 2] if i + 2 < len(args) else "cancelled"
        if not merchant:
            print("Usage: --flag-subscription <merchant> | --mark-subscription <merchant> <status>", file=sys.stderr)
            sys.exit(1)
        rec = set_action(merchant, status)
        print(f"✓ {rec['merchant']} → {rec['status']}")
        sys.exit(0)

    if "--audit" in sys.argv:
        from audit_log import cli_show
        cli_show(sys.argv)
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
        # Defaults: Sunday 09:00. Override with --day [0-6] and --time HH:MM.
        weekday, hour, minute = 0, 9, 0
        for i, arg in enumerate(sys.argv):
            if arg == "--day" and i + 1 < len(sys.argv):
                try:
                    weekday = int(sys.argv[i + 1])
                except ValueError:
                    pass
            elif arg == "--time" and i + 1 < len(sys.argv):
                t = sys.argv[i + 1]
                try:
                    parts = t.split(":")
                    hour = int(parts[0])
                    minute = int(parts[1]) if len(parts) > 1 else 0
                except (ValueError, IndexError):
                    pass
        _setup_digest(weekday=weekday, hour=hour, minute=minute)
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

    if "--demo" in sys.argv or "--show-demo" in sys.argv:
        from scripts.demo_data import seed_demo_data
        from workspace_builder import generate_html_dashboard
        _setup_db()
        seeded = seed_demo_data()
        path = os.path.expanduser("~/.finance/dashboard_demo.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        generate_html_dashboard(output_path=path)
        if seeded:
            print("Demo data seeded — sample profile, accounts, transactions, goals, debts, holdings.")
        else:
            print("Demo data already present (skipped reseeding).")
        print(f"Demo dashboard: {path}")
        print("\nWhen you're ready for the real thing, say 'wipe demo and start over'.")
        sys.exit(0)

    if "--wipe-demo" in sys.argv:
        # Removes ONLY demo-marked entities (DKB Demo account + linked txns).
        # Real user data is untouched.
        _setup_db()
        try:
            from account_manager import list_accounts, delete_account
            removed = 0
            for acc in list_accounts():
                if acc.get("name") == "DKB Demo" or acc.get("id", "").endswith("-demo"):
                    delete_account(acc["id"])
                    removed += 1
            print(f"Removed {removed} demo account(s) and their data.")
        except Exception as exc:
            print(f"Demo wipe failed: {exc}", file=sys.stderr)
            sys.exit(1)
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
