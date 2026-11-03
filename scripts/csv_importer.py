"""
CSV bank statement importer.

Supports auto-detection of common German and international bank formats.
Falls back to generic column-position-based parsing.
"""

from __future__ import annotations

import csv
import io
import os
import re
from datetime import datetime
from typing import Optional

try:
    from amount_parse import parse_amount
    from import_support import read_text
except ImportError:  # pragma: no cover
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from amount_parse import parse_amount
    from import_support import read_text


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
        "currency_col": "Currency",   # multi-currency statements: honor it per row
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
        "currency_col": "Currency",   # multi-currency statements: honor it per row
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

    # ── Germany (newer exports) ──────────────────────────────────────────────
    "dkb_2023": {  # DKB CSV since 2023: metadata block, then this header, UTF-8, 2-digit year
        "detect": ["Buchungsdatum", "Wertstellung", "Umsatztyp", "Betrag (€)"],
        "date": "Buchungsdatum",
        "amount": "Betrag (€)",
        "description": "Verwendungszweck",
        "payee": "Zahlungsempfänger*in",        # outgoing rows: the recipient
        "payee_credit": "Zahlungspflichtige*r",  # incoming rows: the payer
        "date_format": "%d.%m.%y",
        "delimiter": ";",
        "encoding": "utf-8",
        "decimal": ",",
    },
    "sparkasse_camt": {  # Sparkasse "CSV-CAMT" export
        "detect": ["Auftragskonto", "Buchungstag", "Valutadatum", "Waehrung"],
        "date": "Buchungstag",
        "amount": "Betrag",
        "description": "Verwendungszweck",
        "payee": "Beguenstigter/Zahlungspflichtiger",
        "date_format": "%d.%m.%y",
        "delimiter": ";",
        "encoding": "cp1252",
        "decimal": ",",
        "currency_col": "Waehrung",
    },

    # ── United Kingdom (dates are dd/mm/yyyy; many files are cp1252 for the £ sign) ──
    "monzo": {
        "detect": ["Transaction ID", "Local amount", "Notes and #tags"],
        "date": "Date",
        "amount": "Amount",
        "description": "Description",
        "payee": "Name",
        "date_format": "%d/%m/%Y",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ".",
        "currency_col": "Currency",
    },
    "starling": {
        "detect": ["Counter Party", "Amount (GBP)", "Spending Category"],
        "date": "Date",
        "amount": "Amount (GBP)",
        "description": "Reference",
        "payee": "Counter Party",
        "date_format": "%d/%m/%Y",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ".",
        "currency": "GBP",
    },
    "barclays": {  # unverified header
        "detect": ["Number", "Date", "Account", "Amount", "Subcategory", "Memo"],
        "date": "Date",
        "amount": "Amount",
        "description": "Memo",
        "payee": "Memo",
        "date_format": "%d/%m/%Y",
        "delimiter": ",",
        "encoding": "cp1252",
        "decimal": ".",
        "currency": "GBP",
    },
    "hsbc_uk": {  # unverified header
        "detect": ["Date", "Description", "Paid out", "Paid in", "Balance"],
        "date": "Date",
        "description": "Description",
        "payee": "Description",
        "date_format": "%d/%m/%Y",
        "delimiter": ",",
        "encoding": "cp1252",
        "decimal": ".",
        "amount_sign": "split_cols",
        "amount_debit": "Paid out",
        "amount_credit": "Paid in",
        "currency": "GBP",
    },
    "lloyds": {  # also Halifax / Bank of Scotland (same export)
        "detect": ["Transaction Date", "Sort Code", "Debit Amount", "Credit Amount"],
        "date": "Transaction Date",
        "description": "Transaction Description",
        "payee": "Transaction Description",
        "date_format": "%d/%m/%Y",
        "delimiter": ",",
        "encoding": "cp1252",
        "decimal": ".",
        "amount_sign": "split_cols",
        "amount_debit": "Debit Amount",
        "amount_credit": "Credit Amount",
        "currency": "GBP",
    },
    "santander_uk": {  # unverified header
        "detect": ["Date", "Description", "Money in", "Money out", "Balance"],
        "date": "Date",
        "description": "Description",
        "payee": "Description",
        "date_format": "%d/%m/%Y",
        "delimiter": ",",
        "encoding": "cp1252",
        "decimal": ".",
        "amount_sign": "split_cols",
        "amount_debit": "Money out",
        "amount_credit": "Money in",
        "currency": "GBP",
    },
    "nationwide": {  # a few "Account Name:" style metadata lines precede the header
        "detect": ["Date", "Transaction type", "Description", "Paid out", "Paid in", "Balance"],
        "date": "Date",
        "description": "Description",
        "payee": "Description",
        "date_format": "%d %b %Y",
        "delimiter": ",",
        "encoding": "cp1252",
        "decimal": ".",
        "amount_sign": "split_cols",
        "amount_debit": "Paid out",
        "amount_credit": "Paid in",
        "currency": "GBP",
    },

    # ── Ireland (Revolut IE uses the "revolut" format above) ─────────────────
    "aib": {  # unverified header
        "detect": ["Posted Transactions Date", "Description1", "Debit Amount", "Credit Amount"],
        "date": "Posted Transactions Date",
        "description": "Description1",
        "payee": "Description1",
        "date_format": "%d/%m/%Y",
        "delimiter": ",",
        "encoding": "cp1252",
        "decimal": ".",
        "amount_sign": "split_cols",
        "amount_debit": "Debit Amount",
        "amount_credit": "Credit Amount",
        "currency_col": "Posted Currency",
    },
    "bank_of_ireland": {  # unverified header
        "detect": ["Date", "Details", "Debit", "Credit", "Balance"],
        "date": "Date",
        "description": "Details",
        "payee": "Details",
        "date_format": "%d/%m/%Y",
        "delimiter": ",",
        "encoding": "cp1252",
        "decimal": ".",
        "amount_sign": "split_cols",
        "amount_debit": "Debit",
        "amount_credit": "Credit",
    },

    # ── Poland (exports are usually cp1250; detect strings are ASCII-only) ───
    "pko_bp": {  # unverified header
        "detect": ["Data operacji", "Data waluty", "Typ transakcji", "Kwota"],
        "date": "Data operacji",
        "amount": "Kwota",
        "description": "Opis transakcji",
        "payee": "Opis transakcji",
        "date_format": "%Y-%m-%d",
        "delimiter": ",",
        "encoding": "cp1250",
        "decimal": ",",
        "currency_col": "Waluta",
    },
    "mbank": {  # metadata block, then a "#"-prefixed header
        "detect": ["#Data operacji", "#Opis operacji", "#Kwota"],
        "date": "#Data operacji",
        "amount": "#Kwota",
        "description": "#Opis operacji",
        "payee": "#Opis operacji",
        "date_format": "%Y-%m-%d",
        "delimiter": ";",
        "encoding": "cp1250",
        "decimal": ",",
        "currency": "PLN",
    },
    "ing_pl": {  # unverified header
        "detect": ["Data transakcji", "Dane kontrahenta", "Nr rachunku"],
        "date": "Data transakcji",
        "amount": "Kwota transakcji (waluta rachunku)",
        "description": "Tytuł",
        "payee": "Dane kontrahenta",
        "date_format": "%Y-%m-%d",
        "delimiter": ";",
        "encoding": "cp1250",
        "decimal": ",",
        "currency_col": "Waluta rachunku",
    },
    "santander_pl": {  # unverified header
        "detect": ["Data operacji", "Opis operacji", "Nadawca/Odbiorca", "Saldo po operacji"],
        "date": "Data operacji",
        "amount": "Kwota",
        "description": "Opis operacji",
        "payee": "Nadawca/Odbiorca",
        "date_format": "%d-%m-%Y",
        "delimiter": ",",
        "encoding": "cp1250",
        "decimal": ",",
        "currency": "PLN",
    },

    # ── Netherlands ──────────────────────────────────────────────────────────
    "ing_nl": {  # separate "Af Bij" (debit/credit) indicator column; delimiter , or ;
        "detect": ["Naam / Omschrijving", "Af Bij", "Mutatiesoort"],
        "date": "Datum",
        "amount": "Bedrag (EUR)",
        "description": "Mededelingen",
        "payee": "Naam / Omschrijving",
        "date_format": "%Y%m%d",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ",",
        "amount_sign": "indicator",
        "indicator_col": "Af Bij",
        "indicator_debit": ["af"],
    },
    "abn_amro": {  # TXT/TAB export has NO header row: account, currency, date, start bal, end bal, amount, text
        "detect": [],
        "positional": True,
        "col_date": 2,
        "col_amount": 5,
        "col_description": 6,
        "col_currency": 1,
        "date_format": "%Y%m%d",
        "delimiter": "\t",
        "encoding": "cp1252",
        "decimal": ",",   # unverified layout
    },
    "rabobank": {  # unverified header
        "detect": ["IBAN/BBAN", "Naam tegenpartij", "Omschrijving-1"],
        "date": "Datum",
        "amount": "Bedrag",
        "description": "Omschrijving-1",
        "payee": "Naam tegenpartij",
        "date_format": "%Y-%m-%d",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": ",",
        "currency_col": "Munt",
    },
    "bunq": {  # unverified header; delimiter and decimal separator vary by export locale
        "detect": ["Interest Date", "Counterparty", "Name", "Amount"],
        "date": "Date",
        "amount": "Amount",
        "description": "Description",
        "payee": "Name",
        "date_format": "%Y-%m-%d",
        "delimiter": ",",
        "encoding": "utf-8",
        "decimal": "auto",   # "," when the file is ";"-delimited, else "."
    },

    # ── France (accented headers; exports are usually cp1252) ────────────────
    "bnp_paribas": {  # unverified header
        "detect": ["Date operation", "Libelle", "Montant"],
        "date": "Date operation",
        "amount": "Montant",
        "description": "Libelle",
        "payee": "Libelle",
        "date_format": "%d/%m/%Y",
        "delimiter": ";",
        "encoding": "cp1252",
        "decimal": ",",
    },
    "boursorama": {
        "detect": ["dateOp", "dateVal", "supplierFound", "accountNum"],
        "date": "dateOp",
        "amount": "amount",
        "description": "label",
        "payee": "supplierFound",
        "date_format": "%Y-%m-%d",
        "delimiter": ";",
        "encoding": "utf-8",
        "decimal": ",",
    },
    "credit_agricole": {  # unverified header; account metadata lines precede it
        "detect": ["Date", "Libellé", "Débit euros", "Crédit euros"],
        "date": "Date",
        "description": "Libellé",
        "payee": "Libellé",
        "date_format": "%d/%m/%Y",
        "delimiter": ";",
        "encoding": "cp1252",
        "decimal": ",",
        "amount_sign": "split_cols",
        "amount_debit": "Débit euros",
        "amount_credit": "Crédit euros",
    },
}


def _most_specific(matches: list[str], line: str) -> str:
    """Several formats can share their detect columns (Commerzbank's header also
    satisfies Sparkasse's, Nationwide's satisfies HSBC UK's). Among the matches
    whose configured data columns are all present in this header, prefer the one
    with the most detect columns (the most specific), then the first declared;
    else the first match. Non-ASCII column names are not compared because the
    header was decoded before the bank's own encoding was known."""
    def readable(name: str) -> bool:
        fmt = KNOWN_FORMATS[name]
        cols = [fmt.get(k) for k in ("date", "amount", "description", "payee",
                                     "amount_debit", "amount_credit", "indicator_col")]
        return all(c in line for c in cols if c and c.isascii())
    readable_matches = [m for m in matches if readable(m)]
    if not readable_matches:
        return matches[0]
    return max(readable_matches, key=lambda m: len(KNOWN_FORMATS[m]["detect"]))


def detect_bank_format(file_path: str) -> Optional[str]:
    """Detect which bank format a CSV is from by checking headers."""
    try:
        text = read_text(file_path, limit=64 * 1024)
    except OSError:
        return None
    # Read first few lines, skip potential metadata rows
    lines = [ln.strip() for ln in text.splitlines()[:15]]

    # Check each line for header matches
    for line in lines:
        matches: list[str] = []
        for bank_name, fmt in KNOWN_FORMATS.items():
            detect_cols = fmt["detect"]
            if not detect_cols:
                continue  # positional formats handled separately
            if all(col in line for col in detect_cols):
                matches.append(bank_name)
        if matches:
            return _most_specific(matches, line)

    # Check positional formats (no header row): try to parse first line
    # as a date, float, ...
    first_line = lines[0] if lines else ""
    for bank_name, fmt in KNOWN_FORMATS.items():
        if not fmt.get("positional"):
            continue
        parts = first_line.split(fmt.get("delimiter", ","))
        if len(parts) > max(fmt.get("col_date", 0), fmt.get("col_amount", 1), fmt.get("col_description", 4)):
            try:
                datetime.strptime(parts[fmt["col_date"]].strip().strip('"'), fmt["date_format"])
                float(parts[fmt["col_amount"]].strip().strip('"').replace(",", ""))
                return bank_name
            except (ValueError, IndexError):
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

# Source-category -> internal taxonomy mapping (#6 item 1/3: keyword
# auto_categorize() alone left "well over half" of a real Monarch/Mint
# export's rows in other_expense/other_income). Built from each app's
# publicly documented default category set, NOT verified against a real
# export (no sample was available) — best-effort, covers the highest-
# frequency defaults; anything unmapped falls through to auto_categorize()
# unchanged. Internal taxonomy keys: see transaction_logger.EXPENSE_
# CATEGORIES / INCOME_CATEGORIES. Transfer-ish categories are intentionally
# absent here — those are handled by Tier 1 (TRANSFER_CATEGORIES above),
# which runs first and is never overridden by this map.
SOURCE_CATEGORY_MAP = {
    "monarch": {
        "Groceries": "food",
        "Restaurants & Bars": "dining",
        "Coffee Shops": "dining",
        "Auto Payment": "transport",
        "Auto Maintenance": "transport",
        "Gas": "transport",
        "Public Transit": "transport",
        "Parking & Tolls": "transport",
        "Taxi & Ride Shares": "transport",
        "Water": "housing",
        "Gas & Electric": "housing",
        "Mortgage": "housing",
        "Rent": "housing",
        "Home Improvement": "household",
        "Furniture & Housewares": "household",
        "Home Supplies": "household",
        "Lawn & Garden": "household",
        "Internet & Cable": "telecom",
        "Phone": "telecom",
        "Software Subscriptions": "subscriptions",
        "Streaming Services": "subscriptions",
        "Doctor": "healthcare",
        "Dentist": "healthcare",
        "Pharmacy": "healthcare",
        "Health Insurance": "healthcare",
        "Fitness": "healthcare",
        "Personal Care": "personal_care",
        "Life Insurance": "insurance",
        "Home Insurance": "insurance",
        "Auto Insurance": "insurance",
        "Child Care": "childcare",
        "Child Activities": "childcare",
        "Tuition": "education",
        "Books & Supplies": "education",
        "Student Loans": "debt_payment",
        "Personal Loans": "debt_payment",
        "Movies & DVDs": "entertainment",
        "Music": "entertainment",
        "Video Games": "entertainment",
        "Amusement": "entertainment",
        "Arts": "entertainment",
        "Newspapers & Magazines": "entertainment",
        "Financial & Legal Services": "fees",
        "Financial Fees": "fees",
        "Cash & ATM": "fees",
        "Clothing": "clothing",
        "Electronics": "equipment",
        "Hobbies": "equipment",
        "Gifts": "gifts",
        "Charity": "gifts",
        "Pet Food & Supplies": "pets",
        "Pet Grooming": "pets",
        "Veterinary": "pets",
        "Federal Tax": "taxes",
        "State Tax": "taxes",
        "Property Tax": "taxes",
        "Air Travel": "travel",
        "Hotel": "travel",
        "Rental Car & Taxi": "travel",
        "Paycheck": "salary",
        "Business Income": "business",
        "Interest": "investment",
        "Investment Income": "investment",
    },
    "mint": {
        "Groceries": "food",
        "Fast Food": "dining",
        "Restaurants": "dining",
        "Alcohol & Bars": "dining",
        "Coffee Shops": "dining",
        "Auto Insurance": "insurance",
        "Gas & Fuel": "transport",
        "Parking": "transport",
        "Public Transportation": "transport",
        "Ride Share": "transport",
        "Service & Parts": "transport",
        "Mortgage & Rent": "housing",
        "Home Insurance": "insurance",
        "Home Services": "household",
        "Home Supplies": "household",
        "Furnishings": "household",
        "Home Improvement": "household",
        "Lawn & Garden": "household",
        "Home Phone": "telecom",
        "Mobile Phone": "telecom",
        "Television": "telecom",
        "Internet": "telecom",
        "Utilities": "housing",
        "Books & Supplies": "education",
        "Student Loan": "debt_payment",
        "Tuition": "education",
        "Amusement": "entertainment",
        "Arts": "entertainment",
        "Movies & DVDs": "entertainment",
        "Music": "entertainment",
        "Newspapers & Magazines": "entertainment",
        "Bank Fee": "fees",
        "Finance Charge": "fees",
        "Late Fee": "fees",
        "Service Fee": "fees",
        "Trade Commissions": "fees",
        "Life Insurance": "insurance",
        "Dentist": "healthcare",
        "Doctor": "healthcare",
        "Eyecare": "healthcare",
        "Gym": "healthcare",
        "Health Insurance": "healthcare",
        "Pharmacy": "healthcare",
        "Sports": "healthcare",
        "Charity": "gifts",
        "Gift": "gifts",
        "Allowance": "childcare",
        "Baby Supplies": "childcare",
        "Babysitter & Daycare": "childcare",
        "Child Support": "childcare",
        "Kids Activities": "childcare",
        "Toys": "childcare",
        "Loan Fees and Charges": "debt_payment",
        "Loan Insurance": "debt_payment",
        "Loan Interest": "debt_payment",
        "Loan Payment": "debt_payment",
        "Loan Principal": "debt_payment",
        "Cash & ATM": "fees",
        "Check": "fees",
        "Hair": "personal_care",
        "Laundry": "personal_care",
        "Spa & Massage": "personal_care",
        "Pet Food & Supplies": "pets",
        "Pet Grooming": "pets",
        "Veterinary": "pets",
        "Books": "equipment",
        "Clothing": "clothing",
        "Electronics & Software": "equipment",
        "Hobbies": "equipment",
        "Sporting Goods": "equipment",
        "Federal Tax": "taxes",
        "Local Tax": "taxes",
        "Property Tax": "taxes",
        "Sales Tax": "taxes",
        "State Tax": "taxes",
        "Air Travel": "travel",
        "Hotel": "travel",
        "Rental Car & Taxi": "travel",
        "Vacation": "travel",
        "Paycheck": "salary",
        "Bonus": "salary",
        "Interest Income": "investment",
        "Reimbursement": "other_income",
        "Rental Income": "rental",
    },
}


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
        text = read_text(file_path, fmt.get("encoding"))
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=fmt.get("delimiter", ","))
        return sorted({(row.get(col) or "").strip() for row in reader} - {""})
    except Exception:
        return []


_CURRENCY_SYMBOLS = re.compile(r"[€$£¥₹₽\s]")


def _parse_amount(value: str, decimal: str = ",") -> float:
    """Parse a potentially German-formatted number.

    Strips currency symbols ($, €, £, ¥, ₹, ₽) and whitespace so YNAB-style
    "$1,234.56" and "€45,00" round-trip cleanly.
    """
    try:
        return parse_amount(_CURRENCY_SYMBOLS.sub("", (value or "").strip().strip('"')), decimal)
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


_NUMERIC_DATE = re.compile(r"^\s*(\d{1,2})([/.\-])(\d{1,2})\2(\d{4}|\d{2})(?!\d)")
_DEFAULT_DATE_RE = re.compile(r"^%([dm])([/\-])%([dm])\2%[Yy](.*)$")


def infer_date_format(values: list[str], default_fmt: str) -> str:
    """Pick one day/month order for the whole file.

    Only slash/dash numeric formats are ambiguous (03/04/2024). Every value is
    scanned: a first field above 12 proves day-first, a second field above 12
    proves month-first. With no proof, or contradicting proof, the format's own
    (locale) order is kept. The result is applied to every row, so one file is
    never read with two different orders."""
    m = _DEFAULT_DATE_RE.match(default_fmt or "")
    if not m:
        return default_fmt
    default_dayfirst = m.group(1) == "d"
    suffix = m.group(4)

    day_first_proof = month_first_proof = False
    seps: dict[str, int] = {}
    year_lens: set[int] = set()
    for value in values:
        dm = _NUMERIC_DATE.match(value or "")
        if not dm or dm.group(2) == ".":
            continue
        first, second = int(dm.group(1)), int(dm.group(3))
        day_first_proof |= first > 12
        month_first_proof |= second > 12
        seps[dm.group(2)] = seps.get(dm.group(2), 0) + 1
        year_lens.add(len(dm.group(4)))
    if not seps:
        return default_fmt

    if day_first_proof and not month_first_proof:
        dayfirst = True
    elif month_first_proof and not day_first_proof:
        dayfirst = False
    else:
        dayfirst = default_dayfirst  # no proof, or contradictory proof
    sep = max(seps, key=seps.get)
    year = "%y" if year_lens == {2} else "%Y"
    order = ("%d", "%m") if dayfirst else ("%m", "%d")
    return f"{order[0]}{sep}{order[1]}{sep}{year}{suffix}"


def _same_order_alternatives(fmt: str) -> tuple[str, ...]:
    """Formats with the same day/month order as `fmt` but another separator or
    year width: safe fallbacks that cannot flip the file's order."""
    m = _DEFAULT_DATE_RE.match(fmt or "")
    if not m:
        return ()
    a, b = ("%d", "%m") if m.group(1) == "d" else ("%m", "%d")
    return tuple(f"{a}{sep}{b}{sep}{y}" for sep in ("/", "-") for y in ("%Y", "%y"))


def _parse_date(value: str, fmt: str = "%d.%m.%Y") -> str:
    """Parse date string to ISO format."""
    value = value.strip().strip('"')
    try:
        dt = datetime.strptime(value, fmt)
        return dt.date().isoformat()
    except ValueError:
        if _DEFAULT_DATE_RE.match(fmt or ""):
            # Ambiguous numeric format: never re-guess day vs month per row.
            alts = _same_order_alternatives(fmt) + ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y")
        else:
            alts = ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y")
        for alt_fmt in alts:
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


def _resolve_delimiter(header_line: str, fmt: dict) -> str:
    """The format's own delimiter unless the header only splits into the
    expected columns with another one (ING NL, bunq: "," or ";" by export)."""
    declared = fmt.get("delimiter", ",")
    for delim in (declared, ";", ",", "\t"):
        cells = [c.strip().strip('"') for c in header_line.split(delim)]
        if len(cells) > 1 and all(any(col in cell for cell in cells) for col in fmt["detect"]):
            return delim
    return declared


def _load_known(file_path: str, fmt: dict) -> tuple[list[dict], str]:
    """Rows of a header-based known-format file as dicts, plus the delimiter.

    Skips metadata lines above the header, strips BOMs and header whitespace,
    and keeps quoted multi-line cells together."""
    text = read_text(file_path, fmt.get("encoding"))
    lines = text.split("\n")
    header_idx = None
    for i, line in enumerate(lines):
        if all(col in line for col in fmt["detect"]):
            header_idx = i
            break
    if header_idx is None:
        return [], fmt.get("delimiter", ",")
    delimiter = _resolve_delimiter(lines[header_idx], fmt)
    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:]), newline=""), delimiter=delimiter)
    header = [h.strip() for h in next(reader, [])]
    rows = []
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        rows.append(dict(zip(header, cells)))
    return rows, delimiter


def count_data_rows(file_path: str, bank_format: Optional[str] = None) -> int:
    """Count data rows in the file's data section — for import-loss
    accounting (import_router surfaces skipped = count_data_rows(...) -
    len(parsed)). Rows the parser's own validation would reject (bad
    dates, short rows, etc.) still count here, since this counts what the
    file offered, not what parse_csv() accepted.
    """
    bank_format = bank_format or detect_bank_format(file_path)
    fmt = KNOWN_FORMATS.get(bank_format) if bank_format else None

    try:
        text = read_text(file_path, (fmt or {}).get("encoding"))
    except OSError:
        return 0
    lines = text.split("\n")

    delimiter = (fmt or {}).get("delimiter", ",")

    if fmt and fmt.get("positional"):
        return sum(1 for row in csv.reader(lines, delimiter=delimiter) if any(c.strip() for c in row))

    if fmt:
        return len(_load_known(file_path, fmt)[0])

    # Generic path: best-effort — non-empty lines minus one header row.
    non_empty = [ln for ln in lines if ln.strip()]
    return max(0, len(non_empty) - 1)


def _file_currency(fmt: dict, currency: str) -> str:
    """A format that implies a currency (UK banks -> GBP) overrides the
    router's default "EUR"; an explicit non-EUR caller currency wins."""
    return fmt["currency"] if fmt.get("currency") and currency == "EUR" else currency


def _row_currency(row: dict, fmt: dict, default: str) -> str:
    """Per-row ISO code from the format's currency column (Revolut, Wise, ...)."""
    col = fmt.get("currency_col")
    code = (row.get(col) or "").strip().upper() if col else ""
    return code if re.fullmatch(r"[A-Z]{3}", code) else default


def _split_amount(row: dict, fmt: dict, decimal: str) -> Optional[float]:
    """Signed amount from separate debit/credit columns; None if both empty."""
    credit_val = (row.get(fmt.get("amount_credit", "Credit")) or "").strip()
    debit_val = (row.get(fmt.get("amount_debit", "Debit")) or "").strip()
    credit_amt = abs(_parse_amount(credit_val, decimal)) if credit_val else 0.0
    debit_amt = abs(_parse_amount(debit_val, decimal)) if debit_val else 0.0
    # YNAB writes "$0.00" in both columns by default — check parsed values,
    # not string presence. Debit columns may hold positive or negative numbers.
    if credit_amt == 0 and debit_amt == 0:
        return None
    return credit_amt - debit_amt


def _parse_known_format(file_path: str, fmt: dict, currency: str, bank_format: str = "") -> list[dict]:
    """Parse using a known bank format definition."""
    delimiter = fmt.get("delimiter", ",")
    decimal = fmt.get("decimal", ".")
    dfmt = fmt.get("date_format", "%Y-%m-%d")
    amount_sign = fmt.get("amount_sign", "as_is")
    currency = _file_currency(fmt, currency)

    transactions = []

    # Positional format (e.g. Wells Fargo — no header row)
    if fmt.get("positional"):
        col_date = fmt["col_date"]
        col_amount = fmt["col_amount"]
        col_desc = fmt["col_description"]
        text = read_text(file_path, fmt.get("encoding"))
        rows = [r for r in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
                if len(r) > max(col_date, col_amount, col_desc)]
        dfmt = infer_date_format([r[col_date].strip().strip('"') for r in rows], dfmt)
        for row in rows:
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
            col_cur = fmt.get("col_currency")
            code = row[col_cur].strip().upper() if col_cur is not None and col_cur < len(row) else ""
            transactions.append({
                "date": _parse_date(date_val, dfmt),
                "amount": round(amount, 2),
                "description": _sanitize_cell(desc_val),
                "payee": "",
                "currency": code if re.fullmatch(r"[A-Z]{3}", code) else currency,
                "raw": {"_row": row},
            })
        return transactions

    rows, used_delimiter = _load_known(file_path, fmt)
    if decimal == "auto":
        decimal = "," if used_delimiter == ";" else "."

    # One day/month order for the whole file (scans every row).
    dfmt = infer_date_format([r.get(fmt["date"], "") for r in rows], dfmt)

    for row in rows:
        date_val = row.get(fmt["date"], "")
        desc_val = row.get(fmt.get("description", ""), "")
        payee_val = row.get(fmt.get("payee", ""), "")

        # Resolve amount based on amount_sign mode
        if amount_sign == "split_cols":
            amount = _split_amount(row, fmt, decimal)
            if amount is None:
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
            elif amount_sign == "indicator":
                flag = (row.get(fmt["indicator_col"]) or "").strip().lower()
                amount = -abs(amount) if flag in fmt["indicator_debit"] else abs(amount)
            # "as_is" and "monarch" use the value as parsed

        if not date_val:
            continue

        if amount > 0 and fmt.get("payee_credit"):
            payee_val = row.get(fmt["payee_credit"], "") or payee_val

        txn = {
            "date": _parse_date(date_val, dfmt),
            "amount": round(amount, 2),
            "description": _sanitize_cell((desc_val or "").strip()),
            "payee": _sanitize_cell((payee_val or "").strip()),
            "currency": _row_currency(row, fmt, currency),
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


_DEBIT_HEADERS = {
    "paid out", "money out", "debit", "debit amount", "debits", "withdrawal", "withdrawals",
    "outflow", "soll", "belastung", "débit", "débit euros", "debit euros",
    "wypłata", "wyplata", "obciążenia", "obciazenia", "uitgaven", "af",
}
_CREDIT_HEADERS = {
    "paid in", "money in", "credit", "credit amount", "credits", "deposit", "deposits",
    "inflow", "haben", "gutschrift", "crédit", "crédit euros", "credit euros",
    "wpłata", "wplata", "uznania", "inkomsten", "bij",
}
_CURRENCY_HEADERS = {"currency", "währung", "waehrung", "waluta", "munt", "devise", "ccy"}


def _find_exact_col(headers: list[str], names: set) -> Optional[int]:
    """Header index whose name (ignoring a trailing "(£)"/"(EUR)" unit) is one of `names`."""
    for i, h in enumerate(headers):
        if re.sub(r"\s*\(.*?\)\s*$", "", h).strip() in names:
            return i
    return None


def _parse_generic(file_path: str, currency: str, date_format: Optional[str] = None) -> list[dict]:
    """Fallback: parse a generic CSV by guessing columns."""
    transactions = []

    text = read_text(file_path)
    # Try both comma and semicolon (tab for Excel/UTF-16 text exports)
    sample = text[:4000]
    delimiter = max((";", ",", "\t"), key=lambda d: (sample.count(d), d == ","))
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))

    if len(rows) < 2:
        return []

    headers = [h.strip().lower() for h in rows[0]]

    # Guess column indices
    date_col = _find_col(headers, ["date", "datum", "buchungsdatum", "buchung", "buchungstag", "started date",
                                   "data", "dateop"])
    amount_col = _find_col(headers, ["amount", "betrag", "betrag (eur)", "amount (eur)", "value",
                                     "kwota", "montant", "bedrag"])
    desc_col = _find_col(headers, ["description", "verwendungszweck", "buchungstext", "payment reference", "memo",
                                   "opis", "tytuł", "omschrijving", "libell", "details", "reference"])
    payee_col = _find_col(headers, ["payee", "auftraggeber", "empfänger", "begünstigter", "merchant", "name",
                                    "kontrahent", "counter party", "counterparty", "nadawca"])
    currency_col = _find_exact_col(headers, _CURRENCY_HEADERS)

    # Separate debit/credit columns instead of one signed amount
    debit_col = credit_col = None
    if amount_col is None:
        debit_col = _find_exact_col(headers, _DEBIT_HEADERS)
        credit_col = _find_exact_col(headers, _CREDIT_HEADERS)

    if date_col is None or (amount_col is None and debit_col is None and credit_col is None):
        return []

    data_rows = [r for r in rows[1:] if len(r) > date_col and r[date_col].strip()]
    dfmt = date_format or infer_date_format([r[date_col].strip() for r in data_rows], "%d.%m.%Y")
    dfmt = date_format or _generic_date_format(dfmt, data_rows, date_col)

    def cell(row: list[str], col: Optional[int]) -> str:
        return row[col].strip() if col is not None and col < len(row) else ""

    for row in rows[1:]:
        if len(row) <= date_col:
            continue
        date_val = row[date_col].strip()
        if not date_val:
            continue

        if amount_col is not None:
            amount_val = cell(row, amount_col)
            if not amount_val:
                continue
            # Guess decimal format
            decimal = "," if "," in amount_val and "." not in amount_val else "."
            amount = _parse_amount(amount_val, decimal)
        else:
            debit_val, credit_val = cell(row, debit_col), cell(row, credit_col)
            if not debit_val and not credit_val:
                continue
            amounts = []
            for v in (credit_val, debit_val):
                decimal = "," if "," in v and "." not in v else "."
                amounts.append(abs(_parse_amount(v, decimal)) if v else 0.0)
            amount = amounts[0] - amounts[1]

        code = cell(row, currency_col).upper()
        transactions.append({
            "date": _parse_date(date_val, dfmt),
            "amount": round(amount, 2),
            "description": _sanitize_cell(cell(row, desc_col)),
            "payee": _sanitize_cell(cell(row, payee_col)),
            "currency": code if re.fullmatch(r"[A-Z]{3}", code) else currency,
        })

    return transactions


def _generic_date_format(dfmt: str, data_rows: list[list[str]], date_col: int) -> str:
    """The generic parser has no declared locale: when the dates are slash/dash
    numerics, settle one order for the file (day-first unless a value proves
    month-first) instead of the dotted default that would fail every row."""
    values = [r[date_col].strip() for r in data_rows]
    if any(_NUMERIC_DATE.match(v) and not re.match(r"^\s*\d{1,2}\.", v) for v in values):
        return infer_date_format(values, "%d/%m/%Y")
    return dfmt


def _find_col(headers: list[str], candidates: list[str]) -> Optional[int]:
    for i, h in enumerate(headers):
        for c in candidates:
            if c in h:
                return i
    return None
