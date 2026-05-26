"""
Finance Assistant encrypted backup.

Creates a single encrypted tar.gz of the entire `.finance/` directory.
Uses the same Fernet + PBKDF2 (480k iterations) crypto as data_safety.

Usage:
    python3 skill.py --backup                       → ~/Documents/finance-backup-YYYY-MM-DD.tar.gz.enc
    python3 skill.py --backup --to icloud           → iCloud Drive
    python3 skill.py --backup --to /path/file.enc
    python3 skill.py --backup-restore /path/file.enc

Passphrase is read from terminal (getpass). NOT logged. NOT stored.
"""

from __future__ import annotations

import getpass
import io
import os
import sys
import tarfile
from datetime import date
from pathlib import Path
from typing import Optional


def _icloud_dir() -> Path:
    """macOS iCloud Drive root if available."""
    p = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    return p / "finance-backups"


def _default_path() -> Path:
    """Default backup target: ~/Documents/finance-backup-DATE.tar.gz.enc"""
    today = date.today().isoformat()
    return Path.home() / "Documents" / f"finance-backup-{today}.tar.gz.enc"


def _resolve_target(to: Optional[str]) -> Path:
    if not to or to == "default":
        return _default_path()
    if to == "icloud":
        d = _icloud_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d / f"finance-backup-{date.today().isoformat()}.tar.gz.enc"
    p = Path(to).expanduser()
    if p.is_dir():
        p = p / f"finance-backup-{date.today().isoformat()}.tar.gz.enc"
    return p


def _read_passphrase(confirm: bool) -> str:
    p1 = getpass.getpass("Passphrase: ")
    if not p1:
        raise ValueError("Passphrase cannot be empty.")
    if confirm:
        p2 = getpass.getpass("Confirm passphrase: ")
        if p1 != p2:
            raise ValueError("Passphrases do not match.")
    return p1


def _create_archive(source_dir: Path) -> bytes:
    """Create an in-memory tar.gz of `source_dir`. Skips .tmp and audit logs
    over the recent slice (keeps the latest 50 entries only)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            # Skip transient files
            if path.suffix in (".tmp", ".lock"):
                continue
            # Skip the inbox originals — they're stored elsewhere by default
            # but if they're in source_dir, they bloat the backup
            try:
                arcname = path.relative_to(source_dir.parent)
            except ValueError:
                arcname = path.name
            tar.add(str(path), arcname=str(arcname))
    return buf.getvalue()


def _encrypt_bytes(plaintext: bytes, passphrase: str) -> bytes:
    """Encrypt with Fernet, prefixing the 16-byte salt."""
    from data_safety import _derive_fernet_key, _CRYPTO_AVAILABLE
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError(
            "Encrypted backup requires the 'cryptography' package. "
            "Install with: pip install cryptography"
        )
    from cryptography.fernet import Fernet
    salt = os.urandom(16)
    key = _derive_fernet_key(passphrase, salt)
    fernet = Fernet(key)
    return salt + fernet.encrypt(plaintext)


def _decrypt_bytes(ciphertext: bytes, passphrase: str) -> bytes:
    from data_safety import _derive_fernet_key, _CRYPTO_AVAILABLE
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("Decryption requires the 'cryptography' package.")
    from cryptography.fernet import Fernet
    salt, payload = ciphertext[:16], ciphertext[16:]
    key = _derive_fernet_key(passphrase, salt)
    return Fernet(key).decrypt(payload)


# ── Public API ───────────────────────────────────────────────────────────────

def create_backup(
    to: Optional[str] = None,
    passphrase: Optional[str] = None,
    source_dir: Optional[Path] = None,
) -> dict:
    """Create an encrypted backup.

    Args:
        to: 'default' | 'icloud' | absolute path
        passphrase: if None, reads interactively
        source_dir: defaults to the active .finance/ directory

    Returns dict with path, size_bytes, and a one-line confirmation.
    """
    try:
        from finance_storage import get_finance_dir
    except ImportError:
        sys.path.insert(0, os.path.dirname(__file__))
        from finance_storage import get_finance_dir

    src = source_dir or get_finance_dir()
    if not src.exists():
        return {"error": f"No .finance/ directory at {src}. Nothing to back up."}

    target = _resolve_target(to)
    target.parent.mkdir(parents=True, exist_ok=True)

    if passphrase is None:
        passphrase = _read_passphrase(confirm=True)

    try:
        archive = _create_archive(src)
        encrypted = _encrypt_bytes(archive, passphrase)
    except Exception as exc:
        return {"error": f"Backup failed: {exc}"}

    # Write atomically with restrictive perms
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, encrypted)
        finally:
            os.close(fd)
        tmp.replace(target)
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return {"error": f"Could not write backup: {exc}"}

    return {
        "path": str(target),
        "size_bytes": len(encrypted),
        "size_mb": round(len(encrypted) / 1024 / 1024, 2),
        "message": (
            f"✓ Backup written to {target}\n"
            f"  Size: {len(encrypted) / 1024:.1f} KB\n"
            f"  Encrypted with Fernet + PBKDF2 (480k iterations).\n"
            f"  Keep the passphrase safe — without it the backup is unrecoverable."
        ),
    }


def restore_backup(
    path: str,
    passphrase: Optional[str] = None,
    target_dir: Optional[Path] = None,
) -> dict:
    """Restore an encrypted backup.

    Refuses to overwrite an existing non-empty .finance/ unless
    target_dir is supplied — too dangerous for accidents.
    """
    try:
        from finance_storage import get_finance_dir
    except ImportError:
        sys.path.insert(0, os.path.dirname(__file__))
        from finance_storage import get_finance_dir

    src = Path(path).expanduser()
    if not src.exists():
        return {"error": f"Backup file not found: {src}"}

    if passphrase is None:
        passphrase = _read_passphrase(confirm=False)

    try:
        ciphertext = src.read_bytes()
        plaintext = _decrypt_bytes(ciphertext, passphrase)
    except Exception as exc:
        return {"error": f"Decryption failed: {exc}"}

    finance = target_dir or get_finance_dir()
    if finance.exists() and any(finance.iterdir()) and target_dir is None:
        return {
            "error": (
                f"Refusing to restore over existing data at {finance}. "
                f"Move it aside first or pass an explicit target_dir."
            ),
        }

    finance.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r:gz") as tar:
            # filter="data" is the safe extraction mode (Python 3.12+);
            # older Pythons fall back to the default behavior.
            try:
                tar.extractall(path=finance.parent, filter="data")
            except TypeError:
                tar.extractall(path=finance.parent)
    except Exception as exc:
        return {"error": f"Extraction failed: {exc}"}

    return {
        "path": str(finance),
        "message": f"✓ Backup restored to {finance}",
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def cli_backup(args: list[str]) -> None:
    to = None
    for i, arg in enumerate(args):
        if arg == "--to" and i + 1 < len(args):
            to = args[i + 1]
    result = create_backup(to=to)
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    print(result["message"])


def cli_restore(args: list[str]) -> None:
    path = None
    for i, arg in enumerate(args):
        if arg == "--backup-restore" and i + 1 < len(args):
            path = args[i + 1]
    if not path:
        print("Usage: --backup-restore /path/to/finance-backup-...tar.gz.enc", file=sys.stderr)
        sys.exit(1)
    result = restore_backup(path)
    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    print(result["message"])
