"""Tests for backup.py."""
import json
from pathlib import Path

import pytest

from backup import create_backup, restore_backup, _create_archive


# Skip if cryptography isn't installed (CI may not have it)
try:
    from cryptography.fernet import Fernet  # noqa
    _CRYPTO = True
except ImportError:
    _CRYPTO = False

crypto_required = pytest.mark.skipif(not _CRYPTO, reason="cryptography package not installed")


@pytest.fixture
def fake_finance_dir(tmp_path):
    """Build a minimal .finance/ tree with a profile and a transaction file."""
    d = tmp_path / ".finance"
    d.mkdir()
    (d / "finance_profile.json").write_text(json.dumps({"meta": {"created": "2026-01-01"}}))
    (d / "accounts").mkdir()
    (d / "accounts" / "accounts.json").write_text(json.dumps({"accounts": [{"id": "x"}]}))
    return d


def test_create_archive_includes_files(fake_finance_dir):
    archive_bytes = _create_archive(fake_finance_dir)
    assert len(archive_bytes) > 100  # gzip-compressed but non-empty
    # Decompress and check entry names
    import io, tarfile
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        names = tar.getnames()
    assert any("finance_profile.json" in n for n in names)
    assert any("accounts.json" in n for n in names)


@crypto_required
def test_backup_roundtrip(fake_finance_dir, tmp_path):
    """End-to-end: create → restore returns identical files."""
    target = tmp_path / "backup.tar.gz.enc"
    result = create_backup(
        to=str(target),
        passphrase="ThisIsAStrongPass1!",
        source_dir=fake_finance_dir,
    )
    assert "error" not in result
    assert target.exists()
    assert target.stat().st_size > 100

    # Restore to a new location
    restore_target = tmp_path / "restored" / ".finance"
    restore_target.parent.mkdir()
    result = restore_backup(
        path=str(target),
        passphrase="ThisIsAStrongPass1!",
        target_dir=restore_target,
    )
    assert "error" not in result
    # File contents preserved
    profile_path = restore_target / "finance_profile.json"
    assert profile_path.exists()
    loaded = json.loads(profile_path.read_text())
    assert loaded["meta"]["created"] == "2026-01-01"


@crypto_required
def test_backup_wrong_passphrase_fails(fake_finance_dir, tmp_path):
    target = tmp_path / "backup.tar.gz.enc"
    create_backup(
        to=str(target),
        passphrase="CorrectPass1!",
        source_dir=fake_finance_dir,
    )
    result = restore_backup(
        path=str(target),
        passphrase="WrongPass!",
        target_dir=tmp_path / "out" / ".finance",
    )
    assert "error" in result
    assert "Decryption failed" in result["error"]


def test_backup_writes_with_restrictive_perms(fake_finance_dir, tmp_path):
    if not _CRYPTO:
        pytest.skip("cryptography not installed")
    target = tmp_path / "backup.tar.gz.enc"
    create_backup(
        to=str(target),
        passphrase="StrongPassword1!",
        source_dir=fake_finance_dir,
    )
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600
