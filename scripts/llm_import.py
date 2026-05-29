"""
LLM-native import fallback.

Finance Assistant ships 14 hardcoded bank-CSV parsers plus MT940/OFX/PDF. But
it's a skill that runs *inside Claude* — so when a file doesn't match any known
format (a foreign bank, an odd CSV layout, a copy-pasted table, a PDF the
structured parser can't crack, a screenshot), the right move isn't to give up.
It's to let Claude read the raw content and extract the transactions.

This module is the bridge. The Python layer does NOT call an LLM (the skill is
local-first, no API key) — Claude is already the runtime. So:

  1. `prepare_extraction_request()` reads the raw file content and returns a
     structured request: the target schema + the raw text + instructions.
     `import_router.import_file()` returns this (with needs_llm_extraction=True)
     instead of an error when no parser matches.

  2. Claude reads the raw content, extracts rows into the schema, and calls
     `ingest_extracted()` with them.

  3. `ingest_extracted()` sanitizes every field (same CSV-injection guard as the
     hardcoded importers), normalizes + auto-categorizes, deduplicates against
     existing transactions (multi-year window), and returns the SAME preview /
     import result shape as a normal import — so the preview → confirm flow is
     identical. LLM-extracted data gets no special trust.

Net effect: "works with any statement format" without sending anything new off
the machine — the extraction happens in the same Claude session the user is
already in.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

try:
    from finance_storage import get_import_log_path, load_json, save_json
    from transaction_normalizer import normalize_transactions
    from transaction_logger import add_transaction, deduplicate, get_transactions
    from csv_importer import _sanitize_cell
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import get_import_log_path, load_json, save_json
    from transaction_normalizer import normalize_transactions
    from transaction_logger import add_transaction, deduplicate, get_transactions
    from csv_importer import _sanitize_cell


# Cap how much raw text we hand back to Claude — a sane bound so a giant file
# doesn't blow the context window. ~200 KB of text is thousands of transactions.
_MAX_RAW_CHARS = 200_000

# Text-like extensions we can read directly as UTF-8.
_TEXT_EXTS = {".csv", ".txt", ".tsv", ".ofx", ".qfx", ".qif", ".mt940", ".sta", ".json", ".md"}

# The schema Claude should extract each transaction into.
EXTRACTION_SCHEMA = {
    "date": "ISO date YYYY-MM-DD",
    "amount": "float; NEGATIVE for money out (expense), POSITIVE for money in (income)",
    "description": "merchant / purpose text",
    "payee": "counterparty name if distinct from description (optional)",
    "currency": "ISO 4217 code, e.g. EUR/USD/GBP (optional; defaults to import currency)",
}


def _read_raw_text(file_path: str) -> tuple[str, str]:
    """Return (raw_text, how) for a file Claude should parse.

    `how` is a hint about what the text is: "text", "pdf-text", or "image"
    (image means there's no extractable text — Claude must vision-read the file).
    Never raises — returns ("", "error: ...") on failure.
    """
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif"):
            return "", "image"

        if ext == ".pdf":
            try:
                from pdf_importer import _require_pdfplumber
                import pdfplumber
                _require_pdfplumber()
                parts = []
                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        parts.append(page.extract_text() or "")
                text = "\n".join(parts).strip()
                if text:
                    return text[:_MAX_RAW_CHARS], "pdf-text"
                return "", "image"  # scanned PDF with no text layer → vision
            except Exception:
                return "", "image"

        # Text-like (or unknown extension we'll try as text)
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(_MAX_RAW_CHARS), "text"
    except Exception as exc:
        return "", f"error: {exc}"


def prepare_extraction_request(
    file_path: str,
    account_id: str,
    currency: str = "EUR",
) -> dict:
    """Build the structured request Claude uses to extract transactions.

    Returned by import_file() when no parser matches. The skill (Claude) reads
    `raw_text` (or vision-reads the file if `source` == "image"), extracts rows
    matching EXTRACTION_SCHEMA, and calls ingest_extracted().
    """
    raw_text, how = _read_raw_text(file_path)
    return {
        "needs_llm_extraction": True,
        "file": os.path.basename(file_path),
        "file_path": file_path,
        "account_id": account_id,
        "currency": currency,
        "source": how,                 # "text" | "pdf-text" | "image" | "error: ..."
        "raw_text": raw_text,          # empty when source == "image"
        "schema": EXTRACTION_SCHEMA,
        "instructions": (
            "No built-in parser matched this file. Read the content "
            + ("(vision-read the image)" if how == "image" else "below")
            + " and extract every transaction into a list of objects matching "
            "`schema`. One object per transaction. Amounts: negative = money out, "
            "positive = money in. Skip header rows, totals, and running balances. "
            "Then call llm_import.ingest_extracted(rows, account_id, currency) "
            "with dry_run=True first to preview, then dry_run=False to commit."
        ),
    }


def ingest_extracted(
    rows: list[dict],
    account_id: str,
    currency: str = "EUR",
    dry_run: bool = True,
    source_label: str = "llm",
) -> dict:
    """Ingest Claude-extracted transaction rows.

    Sanitizes, normalizes, auto-categorizes, and deduplicates the rows through
    the exact same pipeline as a normal import — LLM-extracted data is given no
    special trust. Returns the same result shape as import_router.import_file().

    Args:
        rows: list of dicts with at least date + amount (per EXTRACTION_SCHEMA)
        account_id: target account
        currency: default currency for rows that don't specify one
        dry_run: True = preview only; False = commit
    """
    if not isinstance(rows, list) or not rows:
        return {"error": "No rows to ingest.", "to_import": 0, "imported": 0}

    # 1. Sanitize every text field (CSV-injection guard) + coerce types.
    cleaned: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if "amount" not in r or r.get("amount") in ("", None):
            continue  # no amount → not a transaction (header/total/blank row)
        try:
            amount = round(float(r.get("amount", 0)), 2)
        except (TypeError, ValueError):
            continue
        if amount == 0:
            continue  # zero-amount rows are never meaningful imports
        date = str(r.get("date", "")).strip()[:10]
        if not date:
            continue
        cleaned.append({
            "date": date,
            "amount": amount,
            "description": _sanitize_cell(str(r.get("description", "")).strip()),
            "payee": _sanitize_cell(str(r.get("payee", "")).strip()),
            "currency": (r.get("currency") or currency),
        })

    if not cleaned:
        return {"error": "No valid rows after sanitization.", "to_import": 0, "imported": 0}

    # 2. Normalize + auto-categorize (same path as every other importer).
    normalized = normalize_transactions(cleaned, account_id, "llm", currency)

    # 3. Deduplicate across all years present in the file (year-boundary safe).
    years = set()
    for t in normalized:
        d = t.get("date", "")
        if len(d) >= 4:
            try:
                years.add(int(d[:4]))
            except ValueError:
                pass
    if not years:
        years = {datetime.now().year}
    existing: list = []
    for yr in years:
        existing.extend(get_transactions(account_id=account_id, year=yr))
    unique = deduplicate(normalized, existing)

    result = {
        "file": "llm-extracted",
        "format": "llm",
        "account_id": account_id,
        "currency": currency,
        "total_parsed": len(rows),
        "total_normalized": len(normalized),
        "duplicates_removed": len(normalized) - len(unique),
        "to_import": len(unique),
        "preview": unique[:10],
        "dry_run": dry_run,
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
                import_source=source_label,
            )
            imported += 1
        result["imported"] = imported
        result["dry_run"] = False

        log = load_json(get_import_log_path(), default={"imports": []})
        log["imports"].append({
            "timestamp": datetime.now().isoformat(),
            "file": "llm-extracted",
            "format": "llm",
            "account_id": account_id,
            "imported": imported,
        })
        save_json(get_import_log_path(), log)

    return result
