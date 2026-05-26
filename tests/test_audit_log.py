"""Tests for audit_log module."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from audit_log import log_mutation, read_recent, format_audit, get_audit_log_path


@pytest.fixture
def audit_isolated(tmp_path, monkeypatch):
    """Redirect the audit log to a temp path for the test."""
    fake_dir = tmp_path / ".finance"
    fake_dir.mkdir()
    fake_path = fake_dir / "audit.log"
    # Patch both module-level constants
    import audit_log
    monkeypatch.setattr(audit_log, "_AUDIT_DIR", fake_dir)
    monkeypatch.setattr(audit_log, "_AUDIT_PATH", fake_path)
    return fake_path


def test_log_mutation_creates_file(audit_isolated):
    log_mutation(action="create", target="transaction", target_id="abc123")
    assert audit_isolated.exists()
    content = audit_isolated.read_text()
    entry = json.loads(content.strip())
    assert entry["action"] == "create"
    assert entry["target"] == "transaction"
    assert entry["target_id"] == "abc123"
    assert "ts" in entry


def test_log_mutation_appends(audit_isolated):
    log_mutation(action="create", target="transaction", target_id="a")
    log_mutation(action="update", target="goal", target_id="b")
    log_mutation(action="delete", target="account", target_id="c")
    lines = audit_isolated.read_text().strip().split("\n")
    assert len(lines) == 3
    assert json.loads(lines[2])["action"] == "delete"


def test_log_mutation_never_raises(audit_isolated, monkeypatch):
    """A logging failure must not propagate to callers."""
    import audit_log
    monkeypatch.setattr(audit_log, "_AUDIT_PATH", Path("/proc/nonexistent/fake"))
    # Must not raise
    log_mutation(action="create", target="transaction", target_id="x")


def test_read_recent_returns_newest_first(audit_isolated):
    for i in range(5):
        log_mutation(action="create", target="transaction", target_id=f"t{i}")
    entries = read_recent(limit=3)
    assert len(entries) == 3
    assert entries[0]["target_id"] == "t4"
    assert entries[2]["target_id"] == "t2"


def test_format_audit_handles_empty():
    out = format_audit([])
    assert "No audit entries" in out


def test_format_audit_shows_entries(audit_isolated):
    log_mutation(action="update", target="profile", before="old", after="new")
    entries = read_recent()
    out = format_audit(entries)
    assert "update" in out
    assert "profile" in out


def test_log_mutation_creates_file_with_restrictive_perms(audit_isolated):
    log_mutation(action="create", target="x")
    # Owner read/write only — no group/other
    mode = audit_isolated.stat().st_mode & 0o777
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


def test_truncate_long_strings(audit_isolated):
    long_str = "x" * 5000
    log_mutation(action="create", target="x", after=long_str)
    entry = read_recent()[0]
    assert len(entry["after"]) < 5000
    assert "…" in entry["after"]
