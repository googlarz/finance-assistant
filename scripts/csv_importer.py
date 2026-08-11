"""
CSV bank statement importer.

Supports auto-detection of common German and international bank formats.
Falls back to generic column-position-based parsing.
"""

from __future__ import annotations

import csv
import os
import re
from datetime import datetime
from typing import Optional


# ── Known bank formats ───────────────────────────────────────────────────────

KNOWN_FORMATS = {
    "dkb": {
        "detect": ["Buchungsdatum", "Wertstellung", "Betrag (EUR)"],
        "date": "Buchungsdatum",
        "amount": "Betrag (EUR)",
        "description": "Verwendungszweck",
        "payee": "Auftraggeber / Begünstigter",
        "date_format": "%d.%m.%Y",
        "delimiter": ";",
        "encoding": "latin-1",
        "decimal": ",",
    },
    "ing": {
        "detect": ["Buchung", "Valuta", "Betrag"],
        "date": "Buchung",
        "amount": "Betrag",
        "description": "Verwendungszweck",
        "payee": "Auftraggeber/Empfänger",
        "date_format": "%d.%m.%Y",
        "delimiter": ";",
        "encoding": "latin-1",
        "decimal": ",",
    },
    "sparkasse": {
        "detect": ["Buchungstag", "Wertstellung", "Betrag"],
        "date": "Buchungstag",
        "amount": "Betrag",
        "description": "Verwendungszweck",
        "payee": "Beguenstigter/Zahlungspflichtiger",
        "date_format": "%d.%m.%y",
        "delimiter": ";",
        "encoding": "latin-1",
        "decimal": ",",
    },
    "n26": {
        "detect": ["Date", "Payee", "Amount (EUR)"],
        "date": "Date",
        "amount": "Amount (EUR)",
        "description": "Payment reference",
        "payee": "Payee",
        "date_format": "%Y-%m-%d",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ".",
    },
    "wise": {
        "detect": ["TransferWise ID", "Date", "Amount"],
        "date": "Date",
        "amount": "Amount",
        "description": "Description",
        "payee": "Merchant",
        "date_format": "%d-%m-%Y",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ".",
    },
    "revolut": {
        "detect": ["Type", "Started Date", "Amount"],
        "date": "Started Date",
        "amount": "Amount",
        "description": "Description",
        "payee": "Description",
        "date_format": "%Y-%m-%d %H:%M:%S",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ".",
    },
    "commerzbank": {
        "detect": ["Buchungstag", "Wertstellung", "Umsatzart"],
        "date": "Buchungstag",
        "amount": "Betrag",
        "description": "Buchungstext",
        "payee": "Auftraggeber / Begünstigter",
        "date_format": "%d.%m.%Y",
        "delimiter": ";",
        "encoding": "latin-1",
        "decimal": ",",
    },
    "chase": {
        "detect": ["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo"],
        "date": "Transaction Date",
        "amount": "Amount",
        "description": "Description",
        "payee": "Description",
        "date_format": "%m/%d/%Y",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ".",
        "amount_sign": "as_is",   # Chase exports negatives for debits
    },
    "bofa": {  # Bank of America
        "detect": ["Date", "Description", "Amount", "Running Bal."],
        "date": "Date",
        "amount": "Amount",
        "description": "Description",
        "payee": "Description",
        "date_format": "%m/%d/%Y",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ".",
        "amount_sign": "as_is",
    },
    "wells_fargo": {
        "detect": [],   # Wells Fargo has no header row — positional
        "positional": True,
        "col_date": 0,
        "col_amount": 1,
        "col_description": 4,
        "date_format": "%m/%d/%Y",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ".",
        "amount_sign": "as_is",
    },
    "mint": {  # Mint (Intuit) — many users still have Mint export CSVs
        "detect": ["Date", "Description", "Original Description", "Amount", "Transaction Type", "Category", "Account Name", "Labels", "Notes"],
        "date": "Date",
        "amount": "Amount",
        "description": "Description",
        "payee": "Description",
        "date_format": "%m/%d/%Y",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ".",
        "amount_sign": "mint",   # Mint uses "debit"/"credit" in Transaction Type
        "type_col": "Transaction Type",
        "category_col": "Category",
    },
    "monarch": {  # Monarch Money
        "detect": ["Date", "Merchant", "Category", "Account", "Original Statement", "Notes", "Amount", "Tags"],
        "date": "Date",
        "amount": "Amount",
        "description": "Original Statement",
        "payee": "Merchant",
        "date_format": "%Y-%m-%d",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ".",
        "amount_sign": "monarch",  # Monarch: negative = expense, positive = income
        "category_col": "Category",
    },
    "ynab": {  # YNAB ("You Need A Budget") register export
        # YNAB export columns: Account, Flag, Date, Payee, Category Group/Category,
        # Category Group, Category, Memo, Outflow, Inflow, Cleared
        "detect": ["Account", "Flag", "Date", "Payee", "Memo", "Outflow", "Inflow"],
        "date": "Date",
        "description": "Memo",
        "payee": "Payee",
        "date_format": "%m/%d/%Y",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ".",
        "amount_sign": "split_cols",   # Outflow vs Inflow columns
        "amount_credit": "Inflow",
        "amount_debit": "Outflow",
    },
    "capital_one": {
        "detect": ["Transaction Date", "Posted Date", "Card No.", "Description", "Category", "Debit", "Credit"],
        "date": "Transaction Date",
        "amount_debit": "Debit",
        "amount_credit": "Credit",
        "description": "Description",
        "payee": "Description",
        "date_format": "%Y-%m-%d",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ".",
        "amount_sign": "split_cols",  # separate Debit/Credit columns
    },
}


def detect_bank_format(file_path: str) -> Optional[str]:
    """Detect which bank format a CSV is from by checking headers."""
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                # Read first few lines, skip potential metadata rows
                lines = []
                for _ in range(15):
                    line = f.readline()
                    if line:
                        lines.append(line.strip())

            # Check each line for header matches
            for line in lines:
                for bank_name, fmt in KNOWN_FORMATS.items():
                    detect_cols = fmt["detect"]
                    if not detect_cols:
                        continue  # positional formats handled separately
                    if all(col in line for col in detect_cols):
                        return bank_name

            # Check positional formats (no header row): try to parse first line
            # as MM/DD/YYYY, float, ...
            for bank_name, fmt in KNOWN_FORMATS.items():
                if not fmt.get("positional"):
                    continue
                first_line = lines[0] if lines else ""
                parts = first_line.split(fmt.get("delimiter", ","))
                if len(parts) > max(fmt.get("col_date", 0), fmt.get("col_amount", 1), fmt.get("col_description", 4)):
                    try:
                        datetime.strptime(parts[fmt["col_date"]].strip().strip('"'), fmt["date_format"])
                        float(parts[fmt["col_amount"]].strip().strip('"').replace(",", ""))
                        return bank_name
                    except (ValueError, IndexError):
                        continue
        except (UnicodeDecodeError, IOError):
            continue
    return None


# Formats whose exports can span multiple user accounts, and the column that says which.
_ACCOUNT_COLUMNS = {"mint": "Account Name", "monarch": "Account", "ynab": "Account"}

# Source-format category strings that mean "moved between the user's own
# accounts" rather than income/spending (#7/#8). These are the row's OWN
# category as exported by the bank/aggregator, not Finance Assistant's
# internal category taxonomy — normalize_transactions() maps a row whose
# source_category is in this set to type="transfer".
#
# Monarch set verified against a real 2,742-row/106-account export (#8:
# "256 rows carry Monarch categories Transfer, Credit Card Payment, or
# Balance Adjustments"). Mint's category taxonomy is Intuit's own
# documented defaults (Mint is sunset; no way to re-verify against a live
# export) — same two transfer-ish categories, minus Balance Adjustments
# which Mint didn't distinguish as its own category.
TRANSFER_CATEGORIES = {
    "monarch": {"Transfer", "Credit Card Payment", "Balance Adjustments"},
    "mint": {"Transfer", "Credit Card Payment"},
}

# YNAB doesn't export a Category column for transfers — it clears the
# category entirely and writes "Transfer : <Account Name>" into Payee
# instead (YNAB's documented register convention, cited in #8).
_YNAB_TRANSFER_PAYEE_PREFIX = "Transfer : "


def detect_source_accounts(file_path: str, bank_format: Optional[str] = None) -> list[str]:
    """Distinct account names in a multi-account-capable export (Mint/Monarch/YNAB).

    Returns [] for single-account formats, unreadable files, or when the account
    column is missing. By default the import pipeline still stamps every row
    with ONE account_id — callers use this to warn when a file spans several
    accounts instead of importing it silently. Pass `route_by_account=True` to
    `import_file()` for per-row resolution instead (see docs/ARCHITECTURE.md
    "Import Assumptions").
    """
    bank_format = bank_format or detect_bank_format(file_path)
    col = _ACCOUNT_COLUMNS.get(bank_format or "")
    if not col:
        return []
    fmt = KNOWN_FORMATS[bank_format]
    try:
        with open(file_path, "r", encoding=fmt.get("encoding", "utf-8"), errors="replace") as f:
            reader = csv.DictReader(f, delimiter=fmt.get("delimiter", ","))
            return sorted({(row.get(col) or "").strip() for row in reader} - {""})
    except Exception:
        return []


_CURRENCY_SYMBOLS = re.compile(r"[€$£¥₹₽\s]")


def _parse_amount(value: str, decimal: str = ",") -> float:
    """Parse a potentially German-formatted number.

    Strips currency symbols ($, €, £, ¥, ₹, ₽) and whitespace so YNAB-style
    "$1,234.56" and "€45,00" round-trip cleanly.
    """
    if not value:
        return 0.0
    value = value.strip().strip('"')
    value = _CURRENCY_SYMBOLS.sub("", value)
    if decimal == ",":
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", "")
    try:
        return float(value)
    except ValueError:
        return 0.0


def _sanitize_cell(value: str) -> str:
    """Strip CSV formula injection prefixes (=, +, -, @, tab, newline at start)."""
    if not value:
        return value
    stripped = value.strip()
    if stripped and stripped[0] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        return "'" + stripped  # prefix with apostrophe to neutralize
    return stripped


def _parse_date(value: str, fmt: str = "%d.%m.%Y") -> str:
    """Parse date string to ISO format."""
    value = value.strip().strip('"')
    try:
        dt = datetime.strptime(value, fmt)
        return dt.date().isoformat()
    except ValueError:
        # Try common alternatives
        for alt_fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(value[:10], alt_fmt)
                return dt.date().isoformat()
            except ValueError:
                continue
    return value[:10]  # Best effort


MAX_IMPORT_BYTES = 50 * 1024 * 1024  # 50 MB


def parse_csv(
    file_path: str,
    bank_format: Optional[str] = None,
    currency: str = "EUR",
    date_format: Optional[str] = None,
) -> list[dict]:
    """Parse a bank CSV file. Returns list of raw transaction dicts."""
    try:
        file_size = os.path.getsize(file_path)
        if file_size > MAX_IMPORT_BYTES:
            raise ValueError(
                f"File too large ({file_size / 1024 / 1024:.1f} MB). Maximum is 50 MB."
            )
    except OSError as exc:
        raise ValueError(f"Cannot access file: {exc}") from exc

    bank_format = bank_format or detect_bank_format(file_path)

    if bank_format and bank_format in KNOWN_FORMATS:
        return _parse_known_format(file_path, KNOWN_FORMATS[bank_format], currency, bank_format)

    return _parse_generic(file_path, currency, date_format)


def _parse_known_format(file_path: str, fmt: dict, currency: str, bank_format: str = "") -> list[dict]:
    """Parse using a known bank format definition."""
    encoding = fmt.get("encoding", "utf-8")
    delimiter = fmt.get("delimiter", ",")
    decimal = fmt.get("decimal", ".")
    dfmt = fmt.get("date_format", "%Y-%m-%d")
    amount_sign = fmt.get("amount_sign", "as_is")

    transactions = []

    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        content = f.read()

    lines = content.split("\n")

    # Positional format (e.g. Wells Fargo — no header row)
    if fmt.get("positional"):
        col_date = fmt["col_date"]
        col_amount = fmt["col_amount"]
        col_desc = fmt["col_description"]
        reader = csv.reader(lines, delimiter=delimiter)
        for row in reader:
            if len(row) <= max(col_date, col_amount, col_desc):
                continue
            date_val = row[col_date].strip().strip('"')
            amount_val = row[col_amount].strip().strip('"')
            desc_val = row[col_desc].strip().strip('"') if col_desc < len(row) else ""
            if not date_val or not amount_val:
                continue
            try:
                datetime.strptime(date_val, dfmt)
            except ValueError:
                continue  # skip non-data rows
            amount = _parse_amount(amount_val, decimal)
            transactions.append({
                "date": _parse_date(date_val, dfmt),
                "amount": round(amount, 2),
                "description": _sanitize_cell(desc_val),
                "payee": "",
                "currency": currency,
                "raw": {"_row": row},
            })
        return transactions

    # Find the header row
    header_idx = None
    for i, line in enumerate(lines):
        if fmt["detect"][0] in line:
            header_idx = i
            break

    if header_idx is None:
        return []

    # Parse from header row onwards
    csv_lines = "\n".join(lines[header_idx:])
    reader = csv.DictReader(csv_lines.splitlines(), delimiter=delimiter)

    for row in reader:
        date_val = row.get(fmt["date"], "")
        desc_val = row.get(fmt.get("description", ""), "")
        payee_val = row.get(fmt.get("payee", ""), "")

        # Resolve amount based on amount_sign mode
        if amount_sign == "split_cols":
            credit_val = row.get(fmt.get("amount_credit", "Credit"), "").strip()
            debit_val = row.get(fmt.get("amount_debit", "Debit"), "").strip()
            credit_amt = _parse_amount(credit_val, decimal) if credit_val else 0.0
            debit_amt = _parse_amount(debit_val, decimal) if debit_val else 0.0
            # YNAB writes "$0.00" in both columns by default — check parsed value,
            # not string presence.
            if credit_amt > 0:
                amount = credit_amt
            elif debit_amt > 0:
                amount = -debit_amt
            else:
                continue
        else:
            amount_val = row.get(fmt.get("amount", ""), "")
            if not amount_val:
                continue
            amount = _parse_amount(amount_val, decimal)
            if amount_sign == "mint":
                type_val = row.get(fmt.get("type_col", "Transaction Type"), "").strip().lower()
                if type_val == "debit":
                    amount = -abs(amount)
            # "as_is" and "monarch" use the value as parsed

        if not date_val:
            continue

        txn = {
            "date": _parse_date(date_val, dfmt),
            "amount": round(amount, 2),
            "description": _sanitize_cell((desc_val or "").strip()),
            "payee": _sanitize_cell((payee_val or "").strip()),
            "currency": currency,
            "raw": dict(row),
        }

        category_col = fmt.get("category_col")
        if category_col:
            txn["source_category"] = (row.get(category_col) or "").strip()

        account_col = _ACCOUNT_COLUMNS.get(bank_format)
        if account_col:
            txn["source_account"] = (row.get(account_col) or "").strip()

        transactions.append(txn)

    return transactions


def _parse_generic(file_path: str, currency: str, date_format: Optional[str] = None) -> list[dict]:
    """Fallback: parse a generic CSV by guessing columns."""
    transactions = []

    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                # Try both comma and semicolon
                sample = f.read(4000)
                delimiter = ";" if sample.count(";") > sample.count(",") else ","
                f.seek(0)
                reader = csv.reader(f, delimiter=delimiter)
                rows = list(reader)
            break
        except UnicodeDecodeError:
            continue
    else:
        return []

    if len(rows) < 2:
        return []

    headers = [h.strip().lower() for h in rows[0]]

    # Guess column indices
    date_col = _find_col(headers, ["date", "datum", "buchungsdatum", "buchung", "buchungstag", "started date"])
    amount_col = _find_col(headers, ["amount", "betrag", "betrag (eur)", "amount (eur)", "value"])
    desc_col = _find_col(headers, ["description", "verwendungszweck", "buchungstext", "payment reference", "memo"])
    payee_col = _find_col(headers, ["payee", "auftraggeber", "empfänger", "begünstigter", "merchant", "name"])

    if date_col is None or amount_col is None:
        return []

    dfmt = date_format or "%d.%m.%Y"

    for row in rows[1:]:
        if len(row) <= max(date_col, amount_col):
            continue
        date_val = row[date_col].strip()
        amount_val = row[amount_col].strip()
        if not date_val or not amount_val:
            continue

        # Guess decimal format
        decimal = "," if "," in amount_val and "." not in amount_val else "."
        amount = _parse_amount(amount_val, decimal)

        desc = row[desc_col].strip() if desc_col is not None and desc_col < len(row) else ""
        payee = row[payee_col].strip() if payee_col is not None and payee_col < len(row) else ""

        transactions.append({
            "date": _parse_date(date_val, dfmt),
            "amount": round(amount, 2),
            "description": _sanitize_cell(desc),
            "payee": _sanitize_cell(payee),
            "currency": currency,
        })

    return transactions


def _find_col(headers: list[str], candidates: list[str]) -> Optional[int]:
    for i, h in enumerate(headers):
        for c in candidates:
            if c in h:
                return i
    return None
