"""
Finance Assistant Audit Log.

Append-only JSONL of every mutation: transactions, profile updates, budget
edits, goal changes, account changes, debt updates. Lets users answer
"what did the assistant change today?" — critical trust feature before
people let an AI touch real financial numbers.

Log lives at ~/.finance/audit.log (HOME-anchored so it survives between
project directories and is excluded from git via the data_safety gitignore
guard).

All entries are best-effort: a logging failure must never block the mutation.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


_AUDIT_DIR = Path.home() / ".finance"
_AUDIT_PATH = _AUDIT_DIR / "audit.log"

# Cap log size at ~5 MB before rotating to audit.log.1
_MAX_BYTES = 5 * 1024 * 1024


def get_audit_log_path() -> Path:
    return _AUDIT_PATH


def _ensure_dir() -> None:
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _rotate_if_needed() -> None:
    try:
        if _AUDIT_PATH.exists() and _AUDIT_PATH.stat().st_size >= _MAX_BYTES:
            rotated = _AUDIT_PATH.with_suffix(".log.1")
            # Replace any prior rotation — we keep one history file only
            try:
                rotated.unlink()
            except FileNotFoundError:
                pass
            _AUDIT_PATH.replace(rotated)
    except Exception:
        pass


def log_mutation(
    action: str,
    target: str,
    *,
    target_id: Optional[str] = None,
    before: Any = None,
    after: Any = None,
    source: str = "skill",
    metadata: Optional[dict] = None,
) -> None:
    """Append a mutation record to the audit log.

    Args:
        action: verb — "create" | "update" | "delete" | "import"
        target: what was changed — "transaction" | "profile" | "budget" |
                "goal" | "account" | "debt" | "investment" | "insurance"
        target_id: identifier of the affected entity (when applicable)
        before: previous value (small dict ok; large data should be hashed)
        after: new value
        source: where the change came from — "skill" | "import" | "cli" | "digest"
        metadata: any extra context the caller wants to preserve

    This function must never raise. A logging failure must not block the
    underlying mutation.
    """
    try:
        _ensure_dir()
        _rotate_if_needed()
        entry = {
            "ts": datetime.now().isoformat(),
            "action": action,
            "target": target,
            "target_id": target_id,
            "source": source,
        }
        if before is not None:
            entry["before"] = _truncate(before)
        if after is not None:
            entry["after"] = _truncate(after)
        if metadata:
            entry["metadata"] = _truncate(metadata)
        # Atomic append with restrictive permissions on first create
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        if not _AUDIT_PATH.exists():
            fd = os.open(str(_AUDIT_PATH), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        else:
            fd = os.open(str(_AUDIT_PATH), os.O_WRONLY | os.O_APPEND)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception as exc:
        # Surface at debug level — don't spam stderr per mutation in normal use
        if os.environ.get("FINANCE_DEBUG"):
            print(f"[finance_assistant] audit log failed: {exc}", file=sys.stderr)


def _truncate(value: Any, max_chars: int = 1000) -> Any:
    """Truncate large payloads so the audit log doesn't bloat.

    Dicts and lists are passed through unchanged (kept as JSON). Long strings
    are truncated with an ellipsis marker.
    """
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + f"…[+{len(value) - max_chars} chars]"
    return value


# ── Read API ──────────────────────────────────────────────────────────────────

def read_recent(limit: int = 50, since_iso: Optional[str] = None) -> list[dict]:
    """Return the most recent `limit` audit entries (newest first).

    Args:
        limit: max entries to return
        since_iso: ISO timestamp; only entries after this are returned
    """
    if not _AUDIT_PATH.exists():
        return []
    try:
        lines = _AUDIT_PATH.read_text(encoding="utf-8").strip().split("\n")
    except Exception:
        return []

    entries: list[dict] = []
    for line in reversed(lines):
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if since_iso and entry.get("ts", "") < since_iso:
            break
        entries.append(entry)
        if len(entries) >= limit:
            break
    return entries


def format_audit(entries: list[dict]) -> str:
    """Format audit entries for human display."""
    if not entries:
        return "No audit entries yet. (Mutations are logged as they happen.)"

    lines = [f"**Audit log — {len(entries)} most recent entries**\n"]
    for e in entries:
        ts = e.get("ts", "")[:19].replace("T", " ")
        action = e.get("action", "?")
        target = e.get("target", "?")
        tid = e.get("target_id", "")
        tid_str = f" #{tid[:8]}" if tid else ""
        source = e.get("source", "skill")
        src_tag = f" [{source}]" if source != "skill" else ""
        lines.append(f"  {ts}  {action} {target}{tid_str}{src_tag}")

        # Show a diff hint if before/after are short scalars
        before = e.get("before")
        after = e.get("after")
        if before is not None and after is not None and (
            isinstance(before, (str, int, float)) and isinstance(after, (str, int, float))
        ):
            lines.append(f"    {before!r} → {after!r}")

    return "\n".join(lines)


def cli_show(args: list[str]) -> None:
    """CLI entry: `python3 skill.py --audit [--limit N] [--since YYYY-MM-DD]`."""
    limit = 50
    since = None
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == "--since" and i + 1 < len(args):
            since = args[i + 1]
            i += 2
        else:
            i += 1
    entries = read_recent(limit=limit, since_iso=since)
    print(format_audit(entries))
