"""
MT940 bank statement importer.

MT940 (SWIFT) is the standard electronic bank statement format used by most
European banks. This parser handles the core fields without external dependencies.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional


def parse_mt940(file_path: str) -> list[dict]:
    """Parse an MT940 file. Returns list of raw transaction dicts."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    transactions = []

    # Split into statements
    statements = re.split(r"(?=:20:)", content)

    for statement in statements:
        # Extract transactions (:61: lines followed by :86: details)
        # SWIFT credit/debit mark (field 61, subfield 2a) is C, D, or the
        # reversal/storno marks RC, RD — the [CD] literal previously matched
        # only C/D, so any reversal row failed to match at all and was
        # silently dropped from the imported statement with no error.
        txn_pattern = re.compile(
            r":61:(\d{6})(\d{4})?([CD]|RC|RD)(\D?)(\d+[,.]?\d*)"
            r"(.*?)(?::86:(.*?))?(?=:6[12]:|:62[FM]:|$)",
            re.DOTALL,
        )

        for match in txn_pattern.finditer(statement):
            date_str = match.group(1)
            credit_debit = match.group(3)
            amount_str = match.group(5)
            ref_line = (match.group(6) or "").strip()
            details = (match.group(7) or "").strip()

            # Parse date (YYMMDD)
            try:
                dt = datetime.strptime(date_str, "%y%m%d")
                iso_date = dt.date().isoformat()
            except ValueError:
                iso_date = date_str

            # Parse amount
            amount_str = amount_str.replace(",", ".")
            try:
                amount = float(amount_str)
            except ValueError:
                amount = 0.0

            # RD = reversal of a debit (nets like a credit); RC = reversal
            # of a credit (nets like a debit).
            if credit_debit in ("D", "RC"):
                amount = -abs(amount)
            else:
                amount = abs(amount)

            # Extract description from :86: field
            description = _clean_mt940_details(details) if details else ref_line

            transactions.append({
                "date": iso_date,
                "amount": round(amount, 2),
                "description": description,
                "payee": _extract_payee(details),
                "currency": _extract_currency(statement),
                "import_ref": f"mt940:{date_str}:{amount_str}",
            })

    return transactions


def _clean_mt940_details(details: str) -> str:
    """Clean MT940 :86: structured details into readable text."""
    # Remove SWIFT subfield tags (?20, ?21, etc.)
    text = re.sub(r"\?2[0-9]", " ", details)
    text = re.sub(r"\?3[0-9]", " ", text)
    text = re.sub(r"\?\d{2}", " ", text)
    # Clean up whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Remove newlines within description
    text = text.replace("\n", " ").replace("\r", "")
    return text[:200]


def _extract_payee(details: str) -> str:
    """Try to extract payee name from MT940 :86: details."""
    # Common patterns: ?32 and ?33 often contain the name
    name_match = re.search(r"\?32(.*?)(?:\?|$)", details)
    if name_match:
        name = name_match.group(1).strip()
        # Also check ?33 for continuation
        name2_match = re.search(r"\?33(.*?)(?:\?|$)", details)
        if name2_match:
            name += " " + name2_match.group(1).strip()
        return name.strip()
    return ""


def _extract_currency(statement: str) -> str:
    """Extract currency from the statement (usually in :60F: or :62F:)."""
    match = re.search(r":60[FM]:([CD])(\d{6})([A-Z]{3})", statement)
    if match:
        return match.group(3)
    return "EUR"
