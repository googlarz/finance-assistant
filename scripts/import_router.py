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


def _resolve_source_accounts(normalized: list[dict], default_account_id: str) -> list[str]:
    """Per-row account routing (#8). For each normalized txn carrying a
    source_account name, resolve it against existing Finance Assistant
    accounts (case-insensitive exact match on name) and set txn["account_id"]
    to the match. Unresolved names are left on the default account_id.

    Returns the sorted list of distinct source_account names that did NOT
    resolve to an existing account — the caller surfaces these so SKILL.md
    can ask the user to map or create them before a real (non-dry-run) import.
    """
    from account_manager import list_accounts

    name_to_id = {}
    for acc in list_accounts():
        name = (acc.get("name") or "").strip().lower()
        if name:
            name_to_id[name] = acc["id"]

    unmapped = set()
    for txn in normalized:
        source_account = (txn.get("source_account") or "").strip()
        if not source_account:
            continue
        resolved = name_to_id.get(source_account.lower())
        if resolved:
            txn["account_id"] = resolved
        else:
            unmapped.add(source_account)

    return sorted(unmapped)


def import_file(
    file_path: str,
    account_id: str,
    format_hint: Optional[str] = None,
    currency: str = "EUR",
    dry_run: bool = True,
    keep_original: bool = True,
    route_by_account: bool = False,
) -> dict:
    """Import transactions from a file. Returns preview or import result.

    Args:
        keep_original: Copy the source file to ~/.finance/originals/ before
            parsing (default True). The copy is timestamped so repeated imports
            of the same file never overwrite each other. Set to False to skip.
        route_by_account: For multi-account-capable formats (Mint/Monarch/YNAB),
            resolve each row's own account name against existing accounts and
            import it there instead of stamping every row with `account_id`.
            Names that don't match an existing account fall back to
            `account_id` and are listed in the result's `unmapped_accounts` —
            the v3.14.0 preview-and-ask pattern applies to those, same as an
            unrouted multi-account file. Default off: existing single-account
            behavior is unchanged unless a caller opts in.
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
    # For CSV, normalize_transactions() needs the SPECIFIC bank format (e.g.
    # "monarch"), not the generic container format ("csv") — Tier 1 transfer
    # detection (#8) looks up TRANSFER_CATEGORIES by this exact name.
    parser_format = fmt

    multi_account_warning = None
    if fmt == "csv":
        from csv_importer import parse_csv, detect_source_accounts, detect_bank_format
        bank_format = detect_bank_format(file_path)
        parser_format = bank_format or "csv"
        raw = parse_csv(file_path, bank_format=bank_format, currency=currency)
        source_accounts = detect_source_accounts(file_path, bank_format)
        if len(source_accounts) > 1:
            if route_by_account:
                consequence = (
                    "Rows will be routed to each account by name — see "
                    "unmapped_accounts for any that don't match an existing account."
                )
            else:
                consequence = (
                    f"but ALL rows will be imported into '{account_id}'. "
                    "Transfers between these accounts will appear as unrelated income/expense. "
                    "Consider passing route_by_account=True, or splitting the file by account."
                )
            multi_account_warning = {
                "source_accounts": source_accounts,
                "message": (
                    f"This file spans {len(source_accounts)} accounts "
                    f"({', '.join(source_accounts[:5])}{'…' if len(source_accounts) > 5 else ''}) "
                    f"{consequence}"
                ),
            }
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
    normalized = normalize_transactions(raw, account_id, parser_format, currency)

    # A known format was detected but yielded nothing (odd layout, locale variant
    # the parser doesn't cover). Fall back to LLM extraction rather than silently
    # importing zero transactions.
    if not normalized:
        from llm_import import prepare_extraction_request
        req = prepare_extraction_request(file_path, account_id, currency)
        req["original_saved"] = original_saved
        req["note"] = f"'{fmt}' parser matched the file type but extracted 0 rows — using LLM fallback."
        return req

    unmapped_accounts: list[str] = []
    if route_by_account:
        unmapped_accounts = _resolve_source_accounts(normalized, account_id)

    # Deduplicate against existing, grouped by the account each row will
    # actually land in (identical to the old single-account behavior when
    # route_by_account left every row on the default account_id — dedup
    # against the wrong account's history would both miss real duplicates
    # and misreport their count).
    #
    # Bank exports commonly span year boundaries (December → January). Load
    # every year that appears in the file so the in-memory dedup fallback
    # doesn't silently miss the other side. SQLite dedup path loads from all
    # years already; this matters when SQLite is unavailable.
    by_account: dict[str, list[dict]] = {}
    for txn in normalized:
        by_account.setdefault(txn.get("account_id", account_id), []).append(txn)

    unique: list[dict] = []
    for target_account, rows in by_account.items():
        years_in_file = set()
        for txn in rows:
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
            existing.extend(get_transactions(account_id=target_account, year=yr))
        unique.extend(deduplicate(rows, existing))

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
    if multi_account_warning:
        result["multi_account_warning"] = multi_account_warning
    if route_by_account:
        result["routed_by_account"] = True
        if unmapped_accounts:
            result["unmapped_accounts"] = unmapped_accounts

    if not dry_run and unique:
        imported = 0
        for txn in unique:
            add_transaction(
                date=txn["date"],
                type=txn.get("type", "expense"),
                amount=txn["amount"],
                category=txn.get("category", "other_expense"),
                description=txn.get("description", ""),
                account_id=txn.get("account_id", account_id),
                currency=txn.get("currency", currency),
                payee=txn.get("payee", ""),
                tags=txn.get("tags", []),
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
