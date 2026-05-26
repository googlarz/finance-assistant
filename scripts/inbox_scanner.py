"""
Finance Assistant Inbox Scanner.

Watches ~/.finance/inbox/ for dropped files and:
  1. Identifies new files via manifest keyed on (path, mtime, size)
  2. Debounces recently-modified files (still being written)
  3. Dry-runs import to preview transaction count / format
  4. Sends a native OS notification
  5. Adds the file to the processing queue

Called automatically by launchd WatchPaths when the inbox folder changes.
Also callable interactively via skill.py --inbox.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

try:
    from finance_storage import (
        get_inbox_dir, get_inbox_manifest_path, get_inbox_queue_path,
        load_json, save_json,
    )
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import (
        get_inbox_dir, get_inbox_manifest_path, get_inbox_queue_path,
        load_json, save_json,
    )

SUPPORTED_EXTENSIONS = {".csv", ".ofx", ".qfx", ".qif", ".pdf", ".xlsx", ".xls"}
DEBOUNCE_SECONDS = 5  # Skip files modified < 5s ago (might still be writing)


# ── Manifest helpers ──────────────────────────────────────────────────────────

def _file_key(path: Path) -> str:
    """Stable key: path + mtime + size. Changes when file is replaced."""
    stat = path.stat()
    return f"{path}|{stat.st_mtime:.0f}|{stat.st_size}"


def _load_manifest() -> dict:
    return load_json(get_inbox_manifest_path(), default={"seen": {}})


def _save_manifest(manifest: dict) -> None:
    save_json(get_inbox_manifest_path(), manifest)


# ── Notifications ─────────────────────────────────────────────────────────────

def _send_notification(title: str, body: str) -> None:
    """Send a native OS notification. Silently ignored if not permitted."""
    try:
        import subprocess
        # macOS
        safe_title = title.replace('"', "'")
        safe_body = body.replace('"', "'")
        script = (
            f'display notification "{safe_body}" '
            f'with title "{safe_title}" '
            f'subtitle "Finance Assistant"'
        )
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass  # Best-effort only


# ── Preview ───────────────────────────────────────────────────────────────────

def _preview_file(file_path: Path) -> dict:
    """Dry-run import to get transaction count and format without committing."""
    try:
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from import_router import import_file
        # account_id="__preview__" — deduplication runs against an empty account,
        # so all rows appear as unique. Accurate for counting; not for dedup.
        result = import_file(str(file_path), account_id="__preview__", dry_run=True)
        return {
            "importable": True,
            "format": result.get("format", "unknown"),
            "transaction_count": result.get("to_import", result.get("total_normalized", 0)),
            "total_parsed": result.get("total_parsed", 0),
            "duplicates_removed": result.get("duplicates_removed", 0),
            "date_range": result.get("date_range", ""),
            "account": result.get("account_id", ""),
        }
    except Exception as exc:
        return {"importable": False, "error": str(exc)}


def _do_import(file_path: Path, account_id: str = "") -> dict:
    """Actually import a file (commit mode). Returns reconciliation numbers.

    Refuses to commit when no account is configured — previously fell back to
    an `__unknown__` sentinel that polluted storage and made later re-imports
    impossible. The inbox item stays at "pending" so it retries after the user
    creates an account.
    """
    try:
        from import_router import import_file
        if not account_id:
            try:
                from account_manager import list_accounts
                accounts = list_accounts()
            except Exception:
                accounts = []
            if not accounts:
                return {
                    "success": False,
                    "error": "No accounts configured. Create an account first (say 'add account').",
                }
            account_id = accounts[0]["id"]
        result = import_file(str(file_path), account_id=account_id, dry_run=False)
        return {
            "success": True,
            "imported": result.get("imported", 0),
            "total_parsed": result.get("total_parsed", 0),
            "duplicates_removed": result.get("duplicates_removed", 0),
            **result,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── Scanner ───────────────────────────────────────────────────────────────────

def scan_inbox(commit: bool = False) -> dict:
    """
    Scan inbox for new files.

    Args:
        commit: If True, immediately import detected files.
                If False (default), dry-run only — user reviews before importing.

    Returns:
        {"new_files": [...], "skipped": [...], "queue_size": int}
    """
    inbox = get_inbox_dir()
    manifest = _load_manifest()
    seen = manifest.get("seen", {})

    queue_path = get_inbox_queue_path()
    queue = load_json(queue_path, default={"items": []})
    existing_ids = {item["id"] for item in queue["items"]}

    now = time.time()
    new_files: list[dict] = []
    skipped: list[dict] = []

    for file_path in sorted(inbox.iterdir()):
        if file_path.name.startswith("."):
            continue
        if file_path.name in {"manifest.json", "queue.json"}:
            continue
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            stat = file_path.stat()
        except FileNotFoundError:
            continue

        # Debounce: file still being written
        age_secs = now - stat.st_mtime
        if age_secs < DEBOUNCE_SECONDS:
            skipped.append({"path": str(file_path), "reason": "debounce"})
            continue

        key = _file_key(file_path)
        if key in seen:
            continue  # Already processed this exact version

        preview = _preview_file(file_path)

        entry: dict = {
            "id": key,
            "path": str(file_path),
            "name": file_path.name,
            "size": stat.st_size,
            "added_at": datetime.now().isoformat(),
            "preview": preview,
            "status": "pending",
        }

        if commit and preview.get("importable"):
            result = _do_import(file_path)
            if result.get("success"):
                entry["status"] = "imported"
            else:
                # Don't mark error if it's just "no accounts" — stay pending,
                # retry on next scan after user creates an account.
                err = result.get("error", "")
                if "No accounts configured" in err:
                    entry["status"] = "pending"
                else:
                    entry["status"] = "error"
            entry["import_result"] = result

        if key not in existing_ids:
            queue["items"].append(entry)
            existing_ids.add(key)

        seen[key] = {"name": file_path.name, "added_at": entry["added_at"]}
        new_files.append(entry)

        # Notify
        if preview.get("importable"):
            txn = preview.get("transaction_count", "?")
            _send_notification(
                "Finance Assistant",
                f"New file: {file_path.name} — {txn} transactions detected",
            )
        else:
            _send_notification("Finance Assistant", f"New file in inbox: {file_path.name}")

    manifest["seen"] = seen
    _save_manifest(manifest)
    save_json(queue_path, queue)

    return {
        "new_files": new_files,
        "skipped": skipped,
        "queue_size": len(queue["items"]),
    }


# ── Queue access ──────────────────────────────────────────────────────────────

def get_pending_items() -> list[dict]:
    """Return queue items with status='pending'."""
    queue = load_json(get_inbox_queue_path(), default={"items": []})
    return [item for item in queue["items"] if item.get("status") == "pending"]


def mark_imported(item_id: str) -> bool:
    """Mark a queue item as imported."""
    queue_path = get_inbox_queue_path()
    queue = load_json(queue_path, default={"items": []})
    for item in queue["items"]:
        if item["id"] == item_id:
            item["status"] = "imported"
            item["imported_at"] = datetime.now().isoformat()
            save_json(queue_path, queue)
            return True
    return False


# ── Display ───────────────────────────────────────────────────────────────────

def format_inbox_status() -> str:
    """Format inbox status for Claude display."""
    pending = get_pending_items()
    if not pending:
        inbox = get_inbox_dir()
        return (
            f"Inbox is empty.\n"
            f"Drop files into {inbox} to auto-detect and queue for import.\n"
            f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    lines = [f"**Inbox: {len(pending)} pending file(s)**\n"]
    for item in pending:
        preview = item.get("preview", {})
        import_result = item.get("import_result", {})
        name = item["name"]

        if item.get("status") == "imported" and import_result:
            # Show reconciliation: what actually changed
            imported = import_result.get("imported", 0)
            dupes = import_result.get("duplicates_removed", 0)
            parsed = import_result.get("total_parsed", imported + dupes)
            recon = f"{imported} new"
            if dupes:
                recon += f", {dupes} duplicate{'s' if dupes != 1 else ''} skipped"
            lines.append(f"• **{name}** ✓ imported — {parsed} parsed, {recon}")
        elif preview.get("importable"):
            txn = preview.get("transaction_count", "?")
            fmt = preview.get("format", "unknown")
            date_range = preview.get("date_range", "")
            dupes = preview.get("duplicates_removed", 0)
            date_part = f" · {date_range}" if date_range else ""
            dupe_note = f" ({dupes} likely duplicates)" if dupes else ""
            lines.append(f"• **{name}** — {txn} transactions ({fmt}{date_part}{dupe_note})")
            lines.append(f"  → Say 'import {name}' to add to your account.")
        else:
            err = preview.get("error", "unrecognized format")
            lines.append(f"• **{name}** — ⚠ {err}")

    return "\n".join(lines)
