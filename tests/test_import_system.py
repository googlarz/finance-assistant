"""Tests for the import system (csv_importer, mt940_importer, ofx_importer, import_router)."""
import os
import tempfile
from csv_importer import parse_csv, detect_bank_format, _parse_amount, _parse_date
from ofx_importer import parse_ofx, _extract_tag, _parse_ofx_date
from mt940_importer import _clean_mt940_details, _extract_currency
from import_router import detect_format
from transaction_normalizer import normalize_transactions, _is_tax_relevant


# ── CSV Importer ─────────────────────────────────────────────────────────────

def test_parse_amount_german():
    assert _parse_amount("1.234,56", ",") == 1234.56
    assert _parse_amount("-45,50", ",") == -45.50
    assert _parse_amount("0,00", ",") == 0.0


def test_parse_amount_us():
    assert _parse_amount("1,234.56", ".") == 1234.56
    assert _parse_amount("-45.50", ".") == -45.50


def test_parse_date_formats():
    assert _parse_date("01.04.2026", "%d.%m.%Y") == "2026-04-01"
    assert _parse_date("2026-04-01", "%Y-%m-%d") == "2026-04-01"
    assert _parse_date("01/04/2026", "%d/%m/%Y") == "2026-04-01"


def test_parse_generic_csv():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write("Date,Amount,Description\n")
        f.write("2026-04-01,-45.50,REWE Berlin\n")
        f.write("2026-04-02,3500.00,Gehalt April\n")
        f.name
    try:
        txns = parse_csv(f.name, currency="EUR")
        assert len(txns) == 2
        assert txns[0]["amount"] == -45.50
        assert txns[1]["amount"] == 3500.0
    finally:
        os.unlink(f.name)


def test_detect_bank_format_dkb():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="latin-1") as f:
        f.write('"Kontonummer:";"DE123456";\n\n')
        f.write('"Buchungsdatum";"Wertstellung";"Buchungstext";"Auftraggeber / Begünstigter";"Verwendungszweck";"Kontonummer";"BLZ";"Betrag (EUR)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"\n')
        f.write('"01.04.2026";"01.04.2026";"Lastschrift";"REWE";"REWE BERLIN";"";"";""-45,50";"";"";""\n')
    try:
        fmt = detect_bank_format(f.name)
        assert fmt == "dkb"
    finally:
        os.unlink(f.name)


# ── OFX Importer ────────────────────────────────────────────────────────────

def test_extract_tag():
    assert _extract_tag("<TRNAMT>-45.50", "TRNAMT") == "-45.50"
    assert _extract_tag("<NAME>REWE Berlin</NAME>", "NAME") == "REWE Berlin"
    assert _extract_tag("no tag here", "MISSING") is None


def test_parse_ofx_date():
    assert _parse_ofx_date("20260401") == "2026-04-01"
    assert _parse_ofx_date("20260401120000") == "2026-04-01"
    assert _parse_ofx_date("20260401120000[-5:EST]") == "2026-04-01"


def test_parse_ofx_file():
    content = """OFXHEADER:100
<OFX>
<BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>EUR
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260401
<TRNAMT>-45.50
<FITID>2026040100001
<NAME>REWE Berlin
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260401
<TRNAMT>3500.00
<FITID>2026040100002
<NAME>Gehalt
</STMTTRN>
</BANKTRANLIST>
</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ofx", delete=False) as f:
        f.write(content)
    try:
        txns = parse_ofx(f.name)
        assert len(txns) == 2
        assert txns[0]["amount"] == -45.50
        assert txns[1]["amount"] == 3500.0
    finally:
        os.unlink(f.name)


# ── MT940 helpers ────────────────────────────────────────────────────────────

def test_clean_mt940_details():
    raw = "?20REWE?21Berlin?22Lebensmittel"
    cleaned = _clean_mt940_details(raw)
    assert "REWE" in cleaned
    assert "Berlin" in cleaned


def test_extract_currency_mt940():
    assert _extract_currency(":60F:C260401EUR123456,78") == "EUR"


# ── Format detection ─────────────────────────────────────────────────────────

def test_detect_csv():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        f.write(b"a,b,c\n1,2,3\n")
    try:
        assert detect_format(f.name) == "csv"
    finally:
        os.unlink(f.name)


def test_detect_ofx():
    with tempfile.NamedTemporaryFile(suffix=".ofx", delete=False) as f:
        f.write(b"OFXHEADER:100\n<OFX>")
    try:
        assert detect_format(f.name) == "ofx"
    finally:
        os.unlink(f.name)


# ── Normalizer ───────────────────────────────────────────────────────────────

def test_normalize_transactions():
    raw = [
        {"date": "2026-04-01", "amount": -45.50, "description": "REWE Berlin", "payee": "REWE"},
        {"date": "2026-04-01", "amount": 3500, "description": "Gehalt", "payee": "Arbeitgeber"},
    ]
    normalized = normalize_transactions(raw, "checking", "csv", "EUR")
    assert len(normalized) == 2
    assert normalized[0]["category"] == "food"
    assert normalized[1]["category"] == "salary"
    assert normalized[0]["type"] == "expense"
    assert normalized[1]["type"] == "income"


def test_is_tax_relevant():
    assert _is_tax_relevant("education") is True
    assert _is_tax_relevant("entertainment") is False


# ── US bank format detection ──────────────────────────────────────────────────

def test_detect_chase():
    csv_content = (
        "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
        "01/15/2024,01/17/2024,STARBUCKS,Food & Drink,Sale,-42.50,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        fmt = detect_bank_format(f.name)
        assert fmt == "chase"
        txns = parse_csv(f.name)
        assert len(txns) == 1
        assert txns[0]["amount"] == -42.50
    finally:
        os.unlink(f.name)


def test_detect_bofa():
    csv_content = (
        "Date,Description,Amount,Running Bal.\n"
        "01/15/2024,Starbucks,-5.75,1234.50\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        fmt = detect_bank_format(f.name)
        assert fmt == "bofa"
    finally:
        os.unlink(f.name)


def test_detect_mint():
    csv_content = (
        "Date,Description,Original Description,Amount,Transaction Type,Category,Account Name,Labels,Notes\n"
        "01/15/2024,Amazon,AMAZON.COM,42.50,debit,Shopping,Checking,,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        fmt = detect_bank_format(f.name)
        assert fmt == "mint"
        txns = parse_csv(f.name)
        assert len(txns) == 1
        # Mint debit rows are negated
        assert txns[0]["amount"] < 0
    finally:
        os.unlink(f.name)


def test_detect_monarch():
    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2024-01-15,Whole Foods,Groceries,Checking,WHOLEFDS,,-38.20,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        fmt = detect_bank_format(f.name)
        assert fmt == "monarch"
    finally:
        os.unlink(f.name)


def test_detect_capital_one():
    csv_content = (
        "Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit\n"
        "2024-01-15,2024-01-16,1234,Coffee Shop,Food & Drink,5.50,\n"
        "2024-01-20,2024-01-21,1234,Refund,Merchandise,,25.00\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        fmt = detect_bank_format(f.name)
        assert fmt == "capital_one"
        txns = parse_csv(f.name)
        assert len(txns) == 2
        # Debit column → negative amount
        assert txns[0]["amount"] == -5.50
        # Credit column → positive amount
        assert txns[1]["amount"] == 25.00
    finally:
        os.unlink(f.name)


def test_detect_ynab():
    csv_content = (
        '"Account","Flag","Date","Payee","Category Group/Category","Category Group","Category","Memo","Outflow","Inflow","Cleared"\n'
        '"Checking","","04/01/2026","Coffee Shop","Food: Dining","Food","Dining","Latte","$4.50","$0.00","Cleared"\n'
        '"Checking","","04/02/2026","Payroll","Income: Salary","Income","Salary","","$0.00","$2,500.00","Cleared"\n'
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        fmt = detect_bank_format(f.name)
        assert fmt == "ynab"
        txns = parse_csv(f.name, bank_format="ynab")
        assert len(txns) == 2
        # First row: outflow $4.50 → -4.50
        assert txns[0]["amount"] == -4.50
        # Second row: inflow $2,500 → +2500
        assert txns[1]["amount"] == 2500.0
        assert txns[1]["payee"] == "Payroll"
    finally:
        os.unlink(f.name)


def test_parse_amount_strips_currency():
    assert _parse_amount("$1,234.56", ".") == 1234.56
    assert _parse_amount("€45,00", ",") == 45.0
    assert _parse_amount("£99.99", ".") == 99.99


def test_detect_wells_fargo():
    # Wells Fargo has no header row — positional columns
    csv_content = '"01/15/2024","-42.50","*","","Coffee Shop"\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        fmt = detect_bank_format(f.name)
        assert fmt == "wells_fargo"
    finally:
        os.unlink(f.name)


# ── Year-boundary dedup (R3) ─────────────────────────────────────────────────

def test_dedup_loads_all_years_in_file(isolated_finance_dir):
    """A CSV that spans Dec→Jan must dedup against BOTH years, not just one."""
    from import_router import import_file
    from transaction_logger import add_transaction

    # Seed: a January 2024 transaction already in storage
    add_transaction(
        date="2024-01-05",
        type="expense",
        amount=-42.50,
        category="dining",
        description="Coffee Shop",
        account_id="checking",
    )

    # CSV with a Dec 2023 + Jan 2024 entry — first row is Dec, so pre-fix code
    # would load only year 2023 transactions and miss the Jan 2024 duplicate.
    csv_content = (
        '"Date","Description","Amount","Running Bal."\n'
        '"12/28/2023","Old Charge","-15.00","100.00"\n'
        '"01/05/2024","Coffee Shop","-42.50","57.50"\n'
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        result = import_file(f.name, account_id="checking", dry_run=True, keep_original=False)
        # The Jan 5 row matches the seeded transaction → should be a duplicate
        assert result["duplicates_removed"] >= 1, (
            f"Expected the Jan 2024 row to be flagged as duplicate. "
            f"Got result: {result}"
        )
    finally:
        os.unlink(f.name)


def test_bulk_csv_import_preserves_payee(isolated_finance_dir):
    """Committed CSV imports must store payee and tags.

    The bulk import loop in import_router used to omit the payee/tags kwargs
    that the single-receipt path passes, so every CSV-imported transaction was
    stored with payee=None — silently breaking subscription detection and any
    merchant-level analysis downstream.
    """
    from import_router import import_file
    from transaction_logger import get_transactions

    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2024-03-01,Spotify,Subscriptions,Checking,SPOTIFY P0123,,-9.99,\n"
        "2024-03-02,Acme Corp,Paycheck,Checking,ACME PAYROLL 0302,,2500.00,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        result = import_file(
            f.name, account_id="checking", currency="USD",
            dry_run=False, keep_original=False,
        )
        assert result["imported"] == 2, f"Expected 2 imported, got: {result}"

        stored = get_transactions(account_id="checking", year=2024)
        payees = {t.get("payee") for t in stored}
        assert "Spotify" in payees, f"payee lost in bulk import; stored payees: {payees}"
        assert "Acme Corp" in payees, f"payee lost in bulk import; stored payees: {payees}"
    finally:
        os.unlink(f.name)


def test_detect_source_accounts_multi_account_monarch():
    """Monarch export spanning several accounts → all distinct names returned."""
    from csv_importer import detect_source_accounts
    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2024-03-01,Spotify,Subscriptions,Checking,SPOTIFY,,-9.99,\n"
        "2024-03-02,Transfer,Transfer,Savings,TRANSFER TO CHECKING,,-500.00,\n"
        "2024-03-02,Transfer,Transfer,Checking,TRANSFER FROM SAVINGS,,500.00,\n"
        "2024-03-03,Employer,Paycheck,Checking,PAYROLL,,2500.00,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        assert detect_source_accounts(f.name) == ["Checking", "Savings"]
    finally:
        os.unlink(f.name)


def test_detect_source_accounts_single_account_returns_one():
    from csv_importer import detect_source_accounts
    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2024-03-01,Spotify,Subscriptions,Checking,SPOTIFY,,-9.99,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        assert detect_source_accounts(f.name) == ["Checking"]
    finally:
        os.unlink(f.name)


def test_detect_source_accounts_non_multi_format_returns_empty():
    """A DKB-style (single-account bank) CSV has no account column → []."""
    from csv_importer import detect_source_accounts
    csv_content = (
        '"Buchungsdatum";"Wertstellung";"Betrag (EUR)"\n'
        '"02.01.2024";"02.01.2024";"-12,99"\n'
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        assert detect_source_accounts(f.name) == []
    finally:
        os.unlink(f.name)


def test_import_file_warns_on_multi_account_file(isolated_finance_dir):
    """Dry-run preview of a multi-account Monarch file must carry multi_account_warning."""
    from import_router import import_file
    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2024-03-01,Spotify,Subscriptions,Checking,SPOTIFY,,-9.99,\n"
        "2024-03-02,Transfer,Transfer,Savings,TRANSFER,,-500.00,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        result = import_file(f.name, account_id="checking", currency="USD",
                             dry_run=True, keep_original=False)
        warning = result.get("multi_account_warning")
        assert warning is not None, f"Expected multi_account_warning, got keys: {list(result)}"
        assert warning["source_accounts"] == ["Checking", "Savings"]
        assert "checking" in warning["message"]  # names the target account_id
    finally:
        os.unlink(f.name)


def test_import_file_no_warning_on_single_account_file(isolated_finance_dir):
    from import_router import import_file
    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2024-03-01,Spotify,Subscriptions,Checking,SPOTIFY,,-9.99,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        result = import_file(f.name, account_id="checking", currency="USD",
                             dry_run=True, keep_original=False)
        assert "multi_account_warning" not in result
    finally:
        os.unlink(f.name)
