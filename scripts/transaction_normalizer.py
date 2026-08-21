"""
Transaction normalizer — transforms raw imported transactions into the
standard Finance Assistant transaction schema with auto-categorization.
"""

from __future__ import annotations

from typing import Optional

try:
    from transaction_logger import auto_categorize, TRANSACTION_SCHEMA, ALL_CATEGORIES
    from csv_importer import TRANSFER_CATEGORIES, _YNAB_TRANSFER_PAYEE_PREFIX, SOURCE_CATEGORY_MAP
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from transaction_logger import auto_categorize, TRANSACTION_SCHEMA, ALL_CATEGORIES
    from csv_importer import TRANSFER_CATEGORIES, _YNAB_TRANSFER_PAYEE_PREFIX, SOURCE_CATEGORY_MAP


def _detect_transfer_type(raw: dict, source_format: str) -> Optional[str]:
    """Tier 1 transfer detection (#8): a structural/category signal in the
    source file, not a guess from amount/date. Returns "transfer" or None —
    never overrides a type the parser already set explicitly.

    Verified signals only (see csv_importer.TRANSFER_CATEGORIES for
    provenance): Monarch/Mint category strings, YNAB's "Transfer : Account"
    payee convention.
    """
    source_category = (raw.get("source_category") or "").strip()
    if source_category and source_category in TRANSFER_CATEGORIES.get(source_format, ()):
        return "transfer"

    if source_format == "ynab":
        payee = (raw.get("payee") or "")
        if payee.startswith(_YNAB_TRANSFER_PAYEE_PREFIX):
            return "transfer"

    return None


def _map_source_category(raw: dict, source_format: str) -> Optional[str]:
    """Map the source bank's own category string to the internal taxonomy
    (#6 items 1/3). Only for non-transfer rows — Tier 1 transfer detection
    (above) and its subcategory preservation already handle transfer rows.
    Returns an internal category key, or None if there's no mapping (falls
    through to auto_categorize())."""
    source_category = (raw.get("source_category") or "").strip()
    if not source_category:
        return None
    mapped = SOURCE_CATEGORY_MAP.get(source_format, {}).get(source_category)
    if mapped and mapped in ALL_CATEGORIES:
        return mapped
    return None


def normalize_transactions(
    raw_transactions: list[dict],
    account_id: str,
    source_format: str,
    currency: str = "EUR",
) -> list[dict]:
    """
    Normalize raw imported transactions into the standard schema.
    Auto-categorizes based on description keywords.
    """
    normalized = []

    for raw in raw_transactions:
        amount = float(raw.get("amount", 0))
        description = raw.get("description", "")
        payee = raw.get("payee", "")

        # Determine type: explicit parser type > Tier 1 structural signal > sign fallback.
        txn_type = raw.get("type")
        source_category = (raw.get("source_category") or "").strip()
        if not txn_type:
            txn_type = _detect_transfer_type(raw, source_format)
        if not txn_type:
            txn_type = "income" if amount > 0 else "expense"

        if txn_type == "transfer" and source_category:
            # Preserve the bank's own transfer-ish category (e.g. "Credit Card
            # Payment") in subcategory — Tier 2 pairing uses it to pick the
            # settlement window without needing to re-parse the source file.
            category, subcategory = auto_categorize(f"{payee} {description}", amount)
            subcategory = source_category
        else:
            # #6 items 1/3: try the source bank's own category first (Monarch/
            # Mint's Category column) — auto_categorize()'s keyword guessing
            # alone left "well over half" of a real export's rows in
            # other_expense/other_income. Falls through unchanged when
            # there's no mapping for this source_format/category.
            mapped_category = _map_source_category(raw, source_format)
            if mapped_category:
                category, subcategory = mapped_category, None
            else:
                category, subcategory = auto_categorize(f"{payee} {description}", amount)

        txn = {
            "date": raw.get("date", ""),
            "account_id": account_id,
            "type": txn_type,
            "amount": round(amount, 2),
            "currency": raw.get("currency", currency),
            "category": category,
            "subcategory": subcategory,
            "description": description.strip(),
            "payee": payee.strip(),
            "import_source": source_format,
            "import_ref": raw.get("import_ref"),
            "is_recurring": False,
            "tags": [],
            "tax_relevant": _is_tax_relevant(category),
        }
        if raw.get("source_account"):
            txn["source_account"] = raw["source_account"]
        normalized.append(txn)

    return normalized


def _is_tax_relevant(category: str) -> bool:
    """Check if a category is typically tax-relevant."""
    tax_categories = {
        "equipment", "education", "childcare", "healthcare",
        "insurance", "gifts", "salary", "freelance", "business",
        "investment", "rental", "pension",
    }
    return category in tax_categories
