"""v4.2.4 trust fixes: license, full-data encryption, rotated-log deletion, doctor, install.sh."""

import json
import subprocess
from pathlib import Path

import pytest

from scripts import data_safety as ds
from scripts.finance_storage import get_finance_dir, ensure_subdir, save_json

ROOT = Path(__file__).resolve().parent.parent
PASS = "Corr3ct-Horse-Battery!"


def test_license_is_mit():
    text = (ROOT / "LICENSE").read_text()
    assert text.startswith("MIT License")
    assert "Copyright (c) 2025 Dawid" in text
    assert "Creative Commons" not in text


def test_no_cc_by_in_docs():
    for f in [ROOT / "CONTRIBUTING.md", *(ROOT / "docs").glob("*.md")]:
        assert "CC BY" not in f.read_text(), f


def _seed():
    save_json(ensure_subdir("budgets") / "b.json", {"limit": 5})
    save_json(ensure_subdir("net_worth", "snapshots") / "2025-01.json", {"nw": 1})
    save_json(ensure_subdir("accounts") / "accounts.json", {"a": 1})
    save_json(get_finance_dir() / "onboarding_state.json", ["list", "json"])
    ds._log_access("test", "seed")


@pytest.mark.skipif(not ds._CRYPTO_AVAILABLE, reason="cryptography missing")
def test_encrypt_covers_everything_and_roundtrips():
    _seed()
    fd = get_finance_dir()
    before = {p: p.read_text() for p in fd.rglob("*.json")}
    assert ds.get_encryption_status()["status"] == "plaintext"
    res = ds.encrypt_sensitive_files(PASS)
    assert "audit/access_log.json" in res["files"]
    st = ds.get_encryption_status()
    assert st["status"] == "encrypted" and st["plaintext"] == 0
    for p in before:
        assert json.loads(p.read_text())["_encrypted"] == "fernet"
    assert ds.get_access_log() == []          # encrypted log does not crash readers
    ds._log_access("x", "y")                   # nor writers
    assert "all" in ds.get_privacy_summary()
    ds.decrypt_sensitive_files(PASS)
    after = {p: p.read_text() for p in fd.rglob("*.json")}
    for p, txt in before.items():
        if p.name != "access_log.json":
            assert json.loads(after[p]) == json.loads(txt)
    assert ds.get_access_log()[0]["action"] == "test"
    assert ds.get_encryption_status()["encrypted"] == 0


@pytest.mark.skipif(not ds._CRYPTO_AVAILABLE, reason="cryptography missing")
def test_passphrase_from_env(monkeypatch):
    _seed()
    monkeypatch.setenv("FINANCE_PASSPHRASE", PASS)
    assert ds.encrypt_sensitive_files()["encrypted_count"] > 0
    assert ds.decrypt_sensitive_files()["decrypted_count"] > 0
    monkeypatch.delenv("FINANCE_PASSPHRASE")
    with pytest.raises(ValueError, match="FINANCE_PASSPHRASE"):
        ds.encrypt_sensitive_files()


def test_delete_all_removes_rotated_logs(tmp_path, monkeypatch):
    import audit_log
    log = tmp_path / "home" / "audit.log"
    log.parent.mkdir()
    monkeypatch.setattr(audit_log, "_AUDIT_PATH", log)
    for n in ("audit.log", "audit.log.1", "audit.log.2"):
        (log.parent / n).write_text("x")
    (log.parent / "keep.txt").write_text("x")
    ensure_subdir("accounts")
    ds.delete_all_data(confirm=True)
    assert sorted(p.name for p in log.parent.iterdir()) == ["keep.txt"]


def test_doctor_checks(monkeypatch):
    from scripts import doctor
    names = {c["name"]: c for c in doctor.run_checks()}
    assert "Network (requests)" in names
    assert "pip install" in doctor._check_cryptography()["message"] or doctor._check_cryptography()["status"] == "ok"
    assert "3.10" in names["Python version"]["message"]
    import os
    monkeypatch.setattr(os.path, "isdir", lambda p: False)
    c = doctor._check_locales_submodule()
    assert c["status"] == "warn" and "git submodule update --init" in c["message"]


def test_install_sh():
    sh = ROOT / "install.sh"
    subprocess.run(["bash", "-n", str(sh)], check=True)
    txt = sh.read_text()
    assert "submodule update --init" in txt and "py -3" in txt and "WSL" in txt
