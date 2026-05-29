"""
Finance Assistant Import Router.

Detects file format and routes to the appropriate parser.
Supports CSV (bank statements), MT940, and OFX/QFX.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from typing import Optional

try:
    from finance_storage import ensure_subdir, get_import_log_path, load_json, save_json
    from transaction_logger import add_transaction, deduplicate, get_transactions
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import ensure_subdir, get_import_log_path, load_json, save_json
    from transaction_logger import add_transaction, deduplicate, get_transactions


def _preserve_original(file_path: str) -> str:
    """
    Copy file to ~/.finance/originals/ with a timestamp prefix.

    Naming: YYYY-MM-DD_HH-MM-SS_<original_filename>
    Ensures repeated imports of the same file never overwrite each other.

    Returns the destination path, or empty string on failure (never raises).
    """
    try:
        originals_dir = ensure_subdir("originals")
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dest_name = f"{timestamp}_{os.path.basename(file_path)}"
        dest = originals_dir / dest_name
        shutil.copy2(file_path, dest)
        return str(dest)
    except Exception:
        return ""


def detect_format(file_path: str) -> str:
    """Detect file format from extension and content sniffing."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".ofx", ".qfx"):
        return "ofx"
    if ext == ".mt940" or ext == ".sta":
        return "mt940"
    if ext == ".csv":
        return "csv"
    if ext == ".pdf":
        return "pdf"
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        return "image"

    # Content sniffing
    try:
        with open(file_path, "rb") as f:
            header_bytes = f.read(8)
        if header_bytes.startswith(b"%PDF"):
            return "pdf"
        first_lines = header_bytes.decode("utf-8", errors="replace")
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            first_lines = f.read(2000)
        if "OFXHEADER" in first_lines or "<OFX>" in first_lines:
            return "ofx"
        if first_lines.startswith(":20:") or ":60F:" in first_lines:
            return "mt940"
        if "," in first_lines or ";" in first_lines or "\t" in first_lines:
            return "csv"
    except Exception:
        pass

    return "unknown"


MAX_IMPORT_BYTES = 50 * 1024 * 1024  # 50 MB


def import_file(
    file_path: str,
    account_id: str,
    format_hint: Optional[str] = None,
    currency: str = "EUR",
    dry_run: bool = True,
    keep_original: bool = True,
) -> dict:
    """Import transactions from a file. Returns preview or import result.

    Args:
        keep_original: Copy the source file to ~/.finance/originals/ before
            parsing (default True). The copy is timestamped so repeated imports
            of the same file never overwrite each other. Set to False to skip.
    """
    try:
        file_size = os.path.getsize(file_path)
        if file_size > MAX_IMPORT_BYTES:
            return {
                "error": f"File too large ({file_size / 1024 / 1024:.1f} MB). Maximum is 50 MB.",
                "file": file_path,
            }
    except OSError as exc:
        return {"error": f"Cannot access file: {exc}", "file": file_path}

    # Preserve the original before any parsing so we always have the raw source
    original_saved = _preserve_original(file_path) if keep_original else ""

    fmt = format_hint or detect_format(file_path)

    if fmt == "csv":
        from csv_importer import parse_csv
        raw = parse_csv(file_path, currency=currency)
    elif fmt == "mt940":
        from mt940_importer import parse_mt940
        raw = parse_mt940(file_path)
    elif fmt == "ofx":
        from ofx_importer import parse_ofx
        raw = parse_ofx(file_path)
    elif fmt == "pdf":
        from pdf_importer import parse_pdf
        raw = parse_pdf(file_path, currency=currency)
    elif fmt == "image":
        from receipt_scanner import scan_to_transaction
        txn = scan_to_transaction(file_path, account_id)
        if "error" in txn.get("scan_result", {}):
            return {
                "error": txn["scan_result"]["error"],
                "file": file_path,
                "format": "image",
            }
        result = {
            "file": os.path.basename(file_path),
            "format": "image",
            "account_id": account_id,
            "currency": txn.get("currency", currency),
            "total_parsed": 1,
            "total_normalized": 1,
            "duplicates_removed": 0,
            "to_import": 1,
            "preview": [txn],
            "dry_run": dry_run,
            "scan_confidence": txn.get("scan_result", {}).get("confidence", "low"),
            "original_saved": original_saved,
        }
        if not dry_run:
            add_transaction(
                date=txn["date"],
                type=txn.get("type", "expense"),
                amount=txn["amount"],
                category=txn.get("category", "other_expense"),
                description=txn.get("description", ""),
                account_id=account_id,
                currency=txn.get("currency", currency),
                payee=txn.get("payee", ""),
                tags=txn.get("tags", []),
                import_source="image",
            )
            result["imported"] = 1
            result["dry_run"] = False
        return result
    else:
        # No built-in parser matched. Don't give up — this skill runs inside
        # Claude, so hand the raw content back for LLM extraction.
        from llm_import import prepare_extraction_request
        req = prepare_extraction_request(file_path, account_id, currency)
        req["original_saved"] = original_saved
        return req

    from transaction_normalizer import normalize_transactions
    normalized = normalize_transactions(raw, account_id, fmt, currency)

    # A known format was detected but yielded nothing (odd layout, locale variant
    # the parser doesn't cover). Fall back to LLM extraction rather than silently
    # importing zero transactions.
    if not normalized:
        from llm_import import prepare_extraction_request
        req = prepare_extraction_request(file_path, account_id, currency)
        req["original_saved"] = original_saved
        req["note"] = f"'{fmt}' parser matched the file type but extracted 0 rows — using LLM fallback."
        return req

    # Deduplicate against existing.
    # Bank exports commonly span year boundaries (December → January). Load
    # every year that appears in the file so the in-memory dedup fallback
    # doesn't silently miss the other side. SQLite dedup path loads from all
    # years already; this matters when SQLite is unavailable.
    years_in_file = set()
    for txn in normalized:
        date_str = txn.get("date", "")
        if len(date_str) >= 4:
            try:
                years_in_file.add(int(date_str[:4]))
            except ValueError:
                continue
    if not years_in_file:
        years_in_file = {datetime.now().year}

    existing: list = []
    for yr in years_in_file:
        existing.extend(get_transactions(account_id=account_id, year=yr))
    unique = deduplicate(normalized, existing)

    result = {
        "file": os.path.basename(file_path),
        "format": fmt,
        "account_id": account_id,
        "currency": currency,
        "total_parsed": len(raw),
        "total_normalized": len(normalized),
        "duplicates_removed": len(normalized) - len(unique),
        "to_import": len(unique),
        "preview": unique[:10],
        "dry_run": dry_run,
        "original_saved": original_saved,
    }

    if not dry_run and unique:
        imported = 0
        for txn in unique:
            add_transaction(
                date=txn["date"],
                type=txn.get("type", "expense"),
                amount=txn["amount"],
                category=txn.get("category", "other_expense"),
                description=txn.get("description", ""),
                account_id=account_id,
                currency=txn.get("currency", currency),
                import_source=fmt,
                import_ref=txn.get("import_ref"),
            )
            imported += 1
        result["imported"] = imported
        result["dry_run"] = False

        # Log import
        log = load_json(get_import_log_path(), default={"imports": []})
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "file": os.path.basename(file_path),
            "format": fmt,
            "account_id": account_id,
            "imported": imported,
        }
        if original_saved:
            log_entry["original_saved"] = original_saved
        log["imports"].append(log_entry)
        save_json(get_import_log_path(), log)

    return result


def sync_bank(days_back: int = 90) -> dict:
    """
    Trigger: user says "sync bank" or "sync transactions".
    Pulls latest transactions from all linked GoCardless accounts.
    """
    try:
        from bank_sync import sync_all
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from bank_sync import sync_all
    return sync_all(days_back=days_back)


def import_folder(
    folder_path: str,
    account_id: str = "default",
    dry_run: bool = True,
    keep_original: bool = True,
) -> dict:
    """Import all supported files from a folder."""
    results = []
    for entry in sorted(os.listdir(folder_path)):
        full_path = os.path.join(folder_path, entry)
        if not os.path.isfile(full_path):
            continue
        fmt = detect_format(full_path)
        if fmt != "unknown":
            result = import_file(
                full_path, account_id,
                format_hint=fmt, dry_run=dry_run, keep_original=keep_original,
            )
            results.append(result)

    return {
        "folder": folder_path,
        "files_found": len(results),
        "results": results,
        "dry_run": dry_run,
    }
