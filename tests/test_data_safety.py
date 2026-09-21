"""Tests for data_safety.py — encryption, permissions, git guard, passphrase strength."""

import json
import os
import stat
import tempfile
from pathlib import Path
import pytest

from scripts.data_safety import (
    _check_passphrase_strength,
    check_permissions,
    harden_permissions,
    ensure_gitignore_protection,
    encrypt_file,
    decrypt_file,
    get_data_inventory,
    get_privacy_summary,
    sanitize_for_sharing,
    export_all_data,
    delete_all_data,
    delete_category,
)
from scripts.finance_storage import get_finance_dir


# ── Passphrase Strength ───────────────────────────────────────────────────────

def test_weak_passphrase_too_short():
    with pytest.raises(ValueError, match="too short"):
        _check_passphrase_strength("short1!")


def test_weak_passphrase_no_variety():
    with pytest.raises(ValueError, match="too simple"):
        _check_passphrase_strength("alllowercasenodigits")


def test_strong_passphrase_passes():
    _check_passphrase_strength("MyS3cure!Passphrase")  # no exception


def test_long_phrase_passes():
    _check_passphrase_strength("correct-horse-battery-staple-42")  # no exception


# ── Encryption / Decryption ───────────────────────────────────────────────────

def test_encrypt_decrypt_roundtrip(tmp_path):
    test_file = tmp_path / "test_profile.json"
    original = {"name": "Test", "balance": 1234.56}
    test_file.write_text(json.dumps(original))

    passphrase = "MyStr0ng!Passphrase"
    encrypt_file(str(test_file), passphrase)

    # File should now be encrypted (not readable as original JSON)
    encrypted_content = json.loads(test_file.read_text())
    assert encrypted_content.get("_encrypted") == "fernet"
    assert "salt" in encrypted_content
    assert "data" in encrypted_content

    decrypt_file(str(test_file), passphrase)
    recovered = json.loads(test_file.read_text())
    assert recovered == original


def test_wrong_passphrase_raises(tmp_path):
    test_file = tmp_path / "data.json"
    test_file.write_text(json.dumps({"x": 1}))
    encrypt_file(str(test_file), "CorrectP@ss1234")
    with pytest.raises(ValueError, match="Wrong passphrase"):
        decrypt_file(str(test_file), "WrongP@ss5678")


def test_each_encryption_uses_unique_salt(tmp_path):
    """Two encryptions of the same file should produce different salts."""
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    payload = json.dumps({"value": 42})
    f1.write_text(payload)
    f2.write_text(payload)

    passphrase = "UniqueS@lt1Test"
    encrypt_file(str(f1), passphrase)
    # Decrypt and re-encrypt to get a fresh salt
    decrypt_file(str(f1), passphrase)
    encrypt_file(str(f1), passphrase)
    encrypt_file(str(f2), passphrase)

    salt1 = json.loads(f1.read_text())["salt"]
    salt2 = json.loads(f2.read_text())["salt"]
    assert salt1 != salt2


def test_already_encrypted_file_is_idempotent(tmp_path):
    test_file = tmp_path / "profile.json"
    test_file.write_text(json.dumps({"k": "v"}))
    passphrase = "T3st!Passphrase99"
    encrypt_file(str(test_file), passphrase)
    content_before = test_file.read_text()
    encrypt_file(str(test_file), passphrase)  # second call
    content_after = test_file.read_text()
    assert content_before == content_after  # no change


# ── File Permissions ──────────────────────────────────────────────────────────

def test_harden_permissions(isolated_finance_dir):
    finance_dir = get_finance_dir()
    finance_dir.mkdir(parents=True, exist_ok=True)
    test_file = finance_dir / "finance_profile.json"
    test_file.write_text(json.dumps({"x": 1}))
    test_file.chmod(0o644)  # world-readable

    harden_permissions()

    mode = test_file.stat().st_mode
    assert not (mode & stat.S_IRGRP), "group read should be removed"
    assert not (mode & stat.S_IROTH), "other read should be removed"
    assert mode & stat.S_IRUSR, "owner read must remain"


def test_check_permissions_detects_insecure(isolated_finance_dir):
    finance_dir = get_finance_dir()
    finance_dir.mkdir(parents=True, exist_ok=True)
    test_file = finance_dir / "finance_profile.json"
    test_file.write_text("{}")
    test_file.chmod(0o644)  # insecure

    result = check_permissions()
    assert result["status"] == "insecure"
    assert len(result["insecure_files"]) > 0


def test_check_permissions_secure_after_harden(isolated_finance_dir):
    finance_dir = get_finance_dir()
    finance_dir.mkdir(parents=True, exist_ok=True)
    (finance_dir / "finance_profile.json").write_text("{}")
    harden_permissions()

    result = check_permissions()
    assert result["status"] == "secure"


# ── Git Guard ─────────────────────────────────────────────────────────────────

def test_gitignore_created_if_missing(tmp_path, isolated_finance_dir, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = ensure_gitignore_protection(str(tmp_path))
    assert result["status"] == "created"
    content = (tmp_path / ".gitignore").read_text()
    assert ".finance/" in content


def test_gitignore_entry_added_to_existing(tmp_path, isolated_finance_dir):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*.pyc\n__pycache__/\n")
    result = ensure_gitignore_protection(str(tmp_path))
    assert result["status"] == "added"
    assert ".finance/" in gitignore.read_text()


def test_gitignore_not_duplicated(tmp_path, isolated_finance_dir):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".finance/\n")
    result = ensure_gitignore_protection(str(tmp_path))
    assert result["status"] == "already_protected"
    assert gitignore.read_text().count(".finance/") == 1


# ── Encrypted Export ──────────────────────────────────────────────────────────

def test_export_encrypted(tmp_path, isolated_finance_dir):
    finance_dir = get_finance_dir()
    finance_dir.mkdir(parents=True, exist_ok=True)
    (finance_dir / "finance_profile.json").write_text(json.dumps({"name": "Test"}))

    export_path = str(tmp_path / "export.json")
    passphrase = "Exp0rt!Secure99"
    export_all_data(export_path=export_path, passphrase=passphrase)

    content = json.loads(Path(export_path).read_text())
    assert content.get("_encrypted") == "fernet"


def test_export_plaintext_by_default(tmp_path, isolated_finance_dir):
    finance_dir = get_finance_dir()
    finance_dir.mkdir(parents=True, exist_ok=True)
    (finance_dir / "finance_profile.json").write_text(json.dumps({"name": "Test"}))

    export_path = str(tmp_path / "export.json")
    export_all_data(export_path=export_path)

    content = json.loads(Path(export_path).read_text())
    assert "data" in content
    assert content.get("_encrypted") is None


# ── Sanitize for Sharing ──────────────────────────────────────────────────────

def test_sanitize_redacts_pii():
    data = {
        "name": "Max Mustermann",
        "employer": "Siemens AG",
        "balance": 5000,
        "transactions": [
            {"payee": "REWE Berlin", "amount": 42.50}
        ]
    }
    sanitized = sanitize_for_sharing(data)
    assert sanitized["name"] == "[REDACTED]"
    assert sanitized["employer"] == "[REDACTED]"
    assert sanitized["balance"] == 5000  # financial data kept
    assert sanitized["transactions"][0]["payee"] == "[REDACTED]"


def test_sanitize_preserves_amounts():
    data = {"balance": 9999, "goal_target": 50000, "currency": "EUR"}
    sanitized = sanitize_for_sharing(data)
    assert sanitized["balance"] == 9999
    assert sanitized["goal_target"] == 50000
    assert sanitized["currency"] == "EUR"


# ── delete_category path traversal guard ─────────────────────────────────────

def test_delete_category_blocks_path_traversal(isolated_finance_dir):
    """delete_category must reject paths that escape .finance/."""
    result = delete_category("../../escape")
    assert "error" in result
    assert "Invalid category path" in result["error"]


def test_delete_category_blocks_absolute_path(isolated_finance_dir):
    """delete_category must reject absolute paths."""
    result = delete_category("/tmp/evil")
    assert "error" in result


def test_delete_category_valid_path(isolated_finance_dir):
    """delete_category accepts a valid category name."""
    finance_dir = get_finance_dir()
    finance_dir.mkdir(parents=True, exist_ok=True)
    (finance_dir / "goals").mkdir(exist_ok=True)
    (finance_dir / "goals" / "goals.json").write_text("{}")

    result = delete_category("goals", confirm=True)
    assert result["action"] == "deleted"
    assert not (finance_dir / "goals").exists()


# ── export excludes bank_sync ─────────────────────────────────────────────────

def test_export_excludes_bank_sync(tmp_path, isolated_finance_dir):
    """export_all_data must not include bank_sync/ directory."""
    finance_dir = get_finance_dir()
    finance_dir.mkdir(parents=True, exist_ok=True)
    (finance_dir / "finance_profile.json").write_text(json.dumps({"name": "Test"}))
    bank_sync_dir = finance_dir / "bank_sync"
    bank_sync_dir.mkdir(exist_ok=True)
    (bank_sync_dir / "token_cache.json").write_text(json.dumps({"access": "SECRET_TOKEN"}))

    export_path = str(tmp_path / "export.json")
    export_all_data(export_path=export_path)

    content = json.loads(Path(export_path).read_text())
    keys = list(content.get("data", {}).keys())
    assert not any("bank_sync" in k for k in keys), f"bank_sync leaked into export: {keys}"


# ── Privacy Summary ───────────────────────────────────────────────────────────

def test_privacy_summary_contains_key_sections(isolated_finance_dir):
    summary = get_privacy_summary()
    assert "Data Safety Summary" in summary
    assert "NEVER store" in summary
    assert "harden_permissions" in summary
    assert "ensure_gitignore" in summary


def test_encrypt_covers_db_and_originals_and_roundtrips(isolated_finance_dir_db):
    import data_safety as ds
    from finance_storage import get_finance_dir
    from account_manager import add_account
    from db import is_encrypted
    add_account({"name": "Checking", "type": "checking", "current_balance": 1})
    fdir = get_finance_dir()
    (fdir / "originals").mkdir(exist_ok=True)
    (fdir / "originals" / "stmt.csv").write_text("date,amount\n2026-01-01,-5\n")
    pw = "correct horse battery 42"
    res = ds.encrypt_sensitive_files(pw)
    assert "finance.db" in res["files"] and "originals/stmt.csv" in res["files"]
    assert is_encrypted()
    assert b"Checking" not in (fdir / "finance.db").read_bytes()
    assert b"date,amount" not in (fdir / "originals" / "stmt.csv").read_bytes()
    assert not (fdir / "finance.db-wal").exists()
    ds.decrypt_sensitive_files(pw)
    assert not is_encrypted()
    assert (fdir / "originals" / "stmt.csv").read_text().startswith("date,amount")
    from account_manager import list_accounts
    assert [a["name"] for a in list_accounts()] == ["Checking"]


def test_backup_rejects_weak_passphrase(monkeypatch):
    import backup
    monkeypatch.setattr("getpass.getpass", lambda *_: "a")
    import pytest
    with pytest.raises(ValueError):
        backup._read_passphrase(confirm=True)
