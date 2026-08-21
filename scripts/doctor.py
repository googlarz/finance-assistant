"""
doctor.py — Health checks for the Finance Assistant setup.

Public API:
    run_checks() -> list[dict]   Each dict has keys: name, status, message
    format_results(checks) -> str  Human-readable summary
"""

import os
import sys


def _check_python_version() -> dict:
    ok = sys.version_info >= (3, 10)
    return {
        "name": "Python version",
        "status": "ok" if ok else "warn",
        "message": f"{sys.version.split()[0]}" + ("" if ok else " (3.10+ required)"),
    }


def _check_requirements() -> dict:
    try:
        import importlib
        missing = []
        for pkg, display in [
            ("sqlite3", "sqlite3"),
            ("json", "json"),
            ("pathlib", "pathlib"),
        ]:
            try:
                importlib.import_module(pkg)
            except ImportError:
                missing.append(pkg)
        if missing:
            return {"name": "Dependencies", "status": "fail", "message": f"Missing: {', '.join(missing)}"}
        return {"name": "Dependencies", "status": "ok", "message": "All core dependencies present"}
    except Exception as exc:
        return {"name": "Dependencies", "status": "fail", "message": str(exc)}


def _check_finance_dir() -> dict:
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from finance_storage import get_finance_dir
        finance_dir = get_finance_dir()
        exists = os.path.isdir(finance_dir)
        return {
            "name": "Finance data directory",
            "status": "ok" if exists else "warn",
            "message": f"{finance_dir}" + (" (exists)" if exists else " (will be created on first use)"),
        }
    except Exception as exc:
        return {"name": "Finance data directory", "status": "warn", "message": str(exc)}


def _check_db() -> dict:
    try:
        from db import is_initialized
        initialized = is_initialized()
        return {
            "name": "Database",
            "status": "ok" if initialized else "warn",
            "message": "Initialized" if initialized else "Not yet initialized (run skill.py to bootstrap)",
        }
    except Exception as exc:
        return {"name": "Database", "status": "warn", "message": str(exc)}


def _check_locales_submodule() -> dict:
    import os
    locales_dir = os.path.join(os.path.dirname(__file__), "..", "locales")
    locales_dir = os.path.normpath(locales_dir)
    # Submodule is uninitialised if the directory exists but is empty (no __init__.py or de/)
    if not os.path.isdir(locales_dir):
        return {"name": "Locales submodule", "status": "fail",
                "message": "locales/ directory missing. Run: git submodule update --init --recursive"}
    has_content = any(os.scandir(locales_dir))
    if not has_content:
        return {"name": "Locales submodule", "status": "fail",
                "message": "locales/ is empty (submodule not initialised). Run: git submodule update --init --recursive"}
    return {"name": "Locales submodule", "status": "ok", "message": f"Initialised ({locales_dir})"}


def _check_locales() -> dict:
    try:
        from tax_engine import get_available_locales
        locales = [loc["code"] for loc in get_available_locales()]
        return {
            "name": "Locales",
            "status": "ok",
            "message": f"{len(locales)} locale(s) available: {', '.join(locales)}",
        }
    except Exception as exc:
        return {"name": "Locales", "status": "warn", "message": str(exc)}


def _check_cryptography() -> dict:
    try:
        import cryptography  # noqa: F401
        return {"name": "Encryption (cryptography)", "status": "ok", "message": "cryptography package available"}
    except ImportError:
        return {
            "name": "Encryption (cryptography)",
            "status": "fail",
            "message": "Missing: pip install cryptography — required for data encryption/decryption",
        }


def _check_tesseract() -> dict:
    """receipt_scanner.py needs the tesseract system binary (not just the
    pytesseract Python wrapper, which requirements.txt does install) —
    'scan [image]' throws TesseractNotFoundError without it, and until this
    check existed --doctor reported all-clear on a machine missing it."""
    import shutil as _shutil
    if _shutil.which("tesseract"):
        return {"name": "OCR (tesseract)", "status": "ok", "message": "tesseract binary found"}
    return {
        "name": "OCR (tesseract)",
        "status": "warn",
        "message": "tesseract binary not found — 'scan [receipt]' will fail. "
                    "Install: brew install tesseract (macOS) / apt install tesseract-ocr (Linux)",
    }


def run_checks() -> list:
    """Run all health checks. Returns list of {name, status, message} dicts."""
    return [
        _check_python_version(),
        _check_requirements(),
        _check_cryptography(),
        _check_finance_dir(),
        _check_locales_submodule(),
        _check_db(),
        _check_locales(),
        _check_tesseract(),
    ]


def format_results(checks: list) -> str:
    """Format check results as a human-readable string."""
    icons = {"ok": "✓", "warn": "!", "fail": "✗"}
    lines = ["Finance Assistant — health check", ""]
    for c in checks:
        icon = icons.get(c["status"], "?")
        lines.append(f"  [{icon}] {c['name']}: {c['message']}")
    lines.append("")
    failures = [c for c in checks if c["status"] == "fail"]
    warnings = [c for c in checks if c["status"] == "warn"]
    if failures:
        lines.append(f"FAIL — {len(failures)} check(s) failed.")
    elif warnings:
        lines.append(f"OK (with {len(warnings)} warning(s))")
    else:
        lines.append("All checks passed.")
    return "\n".join(lines)
