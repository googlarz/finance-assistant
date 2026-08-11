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


# ── Tier 1 transfer detection (#8) ──────────────────────────────────────────

def test_monarch_transfer_category_extracted_as_source_category():
    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2026-04-01,Internal Transfer,Transfer,Checking,XFER TO SAVINGS,,-1000.00,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        txns = parse_csv(f.name, bank_format="monarch")
        assert txns[0]["source_category"] == "Transfer"
        assert txns[0]["source_account"] == "Checking"
    finally:
        os.unlink(f.name)


def test_monarch_transfer_category_becomes_transfer_type():
    raw = [
        {"date": "2026-04-01", "amount": -1000.0, "description": "XFER TO SAVINGS",
         "payee": "Internal Transfer", "source_category": "Transfer"},
        {"date": "2026-04-02", "amount": -500.0, "description": "PAYMENT CHASE CARD",
         "payee": "Chase Credit Card", "source_category": "Credit Card Payment"},
        {"date": "2026-04-03", "amount": -85.32, "description": "WHOLE FOODS MKT",
         "payee": "Whole Foods", "source_category": "Groceries"},
    ]
    normalized = normalize_transactions(raw, "checking", "monarch", "USD")
    assert normalized[0]["type"] == "transfer"
    assert normalized[1]["type"] == "transfer"
    assert normalized[1]["subcategory"] == "Credit Card Payment"  # for Tier 2's window choice
    assert normalized[2]["type"] == "expense"  # ordinary category untouched


def test_mint_transfer_category_becomes_transfer_type():
    raw = [{"date": "2026-04-01", "amount": -200.0, "description": "",
            "payee": "", "source_category": "Transfer"}]
    normalized = normalize_transactions(raw, "checking", "mint", "USD")
    assert normalized[0]["type"] == "transfer"


def test_ynab_transfer_payee_becomes_transfer_type():
    raw = [
        {"date": "2026-04-01", "amount": -200.0, "description": "", "payee": "Transfer : Savings Account"},
        {"date": "2026-04-02", "amount": -12.50, "description": "", "payee": "Coffee Shop"},
    ]
    normalized = normalize_transactions(raw, "checking", "ynab", "USD")
    assert normalized[0]["type"] == "transfer"
    assert normalized[1]["type"] == "expense"


def test_transfer_category_from_wrong_format_not_matched():
    """A category string that means 'transfer' for Monarch must not leak into
    a format where it wasn't verified (e.g. a DKB CSV that happens to have a
    German Verwendungszweck containing the word)."""
    raw = [{"date": "2026-04-01", "amount": -500.0, "description": "some text",
            "payee": "", "source_category": "Transfer"}]
    normalized = normalize_transactions(raw, "checking", "dkb", "EUR")
    assert normalized[0]["type"] == "expense"  # dkb isn't in TRANSFER_CATEGORIES


def test_explicit_type_not_overridden_by_transfer_signal():
    """If a parser already set an explicit type, Tier 1 must not override it."""
    raw = [{"date": "2026-04-01", "amount": -500.0, "description": "", "payee": "",
            "source_category": "Transfer", "type": "expense"}]
    normalized = normalize_transactions(raw, "checking", "monarch", "USD")
    assert normalized[0]["type"] == "expense"


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


# ── Per-row account routing (#8) ────────────────────────────────────────────

def test_route_by_account_resolves_known_names(isolated_finance_dir):
    from import_router import import_file
    from account_manager import add_account

    add_account({"id": "chk", "name": "Checking", "type": "checking"})
    add_account({"id": "sav", "name": "Savings", "type": "savings"})

    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2024-03-01,Spotify,Subscriptions,Checking,SPOTIFY,,-9.99,\n"
        "2024-03-02,Payroll,Paycheck,Savings,DEPOSIT,,1000.00,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        result = import_file(f.name, account_id="chk", currency="USD",
                             dry_run=True, keep_original=False, route_by_account=True)
        assert result["routed_by_account"] is True
        assert "unmapped_accounts" not in result
        by_desc = {t["description"]: t["account_id"] for t in result["preview"]}
        assert by_desc["SPOTIFY"] == "chk"
        assert by_desc["DEPOSIT"] == "sav"
    finally:
        os.unlink(f.name)


def test_route_by_account_flags_unmapped_names(isolated_finance_dir):
    """An account name with no matching FA account falls back to the default
    and is listed for the caller to resolve (create/map/import-anyway)."""
    from import_router import import_file
    from account_manager import add_account

    add_account({"id": "chk", "name": "Checking", "type": "checking"})

    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2024-03-01,Spotify,Subscriptions,Checking,SPOTIFY,,-9.99,\n"
        "2024-03-02,Payroll,Paycheck,Unknown Credit Union,DEPOSIT,,1000.00,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        result = import_file(f.name, account_id="chk", currency="USD",
                             dry_run=True, keep_original=False, route_by_account=True)
        assert result["unmapped_accounts"] == ["Unknown Credit Union"]
        by_desc = {t["description"]: t["account_id"] for t in result["preview"]}
        assert by_desc["SPOTIFY"] == "chk"
        assert by_desc["DEPOSIT"] == "chk"  # unresolved falls back to default
    finally:
        os.unlink(f.name)


def test_route_by_account_writes_to_resolved_accounts(isolated_finance_dir):
    from import_router import import_file
    from account_manager import add_account
    from transaction_logger import get_transactions

    add_account({"id": "chk", "name": "Checking", "type": "checking"})
    add_account({"id": "sav", "name": "Savings", "type": "savings"})

    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2024-03-01,Spotify,Subscriptions,Checking,SPOTIFY,,-9.99,\n"
        "2024-03-02,Payroll,Paycheck,Savings,DEPOSIT,,1000.00,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        result = import_file(f.name, account_id="chk", currency="USD",
                             dry_run=False, keep_original=False, route_by_account=True)
        assert result["imported"] == 2

        chk_txns = get_transactions(account_id="chk", year=2024)
        sav_txns = get_transactions(account_id="sav", year=2024)
        assert {t["description"] for t in chk_txns} == {"SPOTIFY"}
        assert {t["description"] for t in sav_txns} == {"DEPOSIT"}
    finally:
        os.unlink(f.name)


def test_multi_account_warning_message_reflects_routing(isolated_finance_dir):
    """The warning text must not claim rows land in one account once
    route_by_account has actually routed them elsewhere."""
    from import_router import import_file
    from account_manager import add_account

    add_account({"id": "chk", "name": "Checking", "type": "checking"})
    add_account({"id": "sav", "name": "Savings", "type": "savings"})

    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2024-03-01,Spotify,Subscriptions,Checking,SPOTIFY,,-9.99,\n"
        "2024-03-02,Payroll,Paycheck,Savings,DEPOSIT,,1000.00,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        unrouted = import_file(f.name, account_id="chk", currency="USD",
                               dry_run=True, keep_original=False)
        routed = import_file(f.name, account_id="chk", currency="USD",
                             dry_run=True, keep_original=False, route_by_account=True)
        assert "ALL rows will be imported into" in unrouted["multi_account_warning"]["message"]
        assert "ALL rows will be imported into" not in routed["multi_account_warning"]["message"]
    finally:
        os.unlink(f.name)


def test_import_file_applies_tier1_transfer_detection(isolated_finance_dir):
    """Integration regression: import_router.py must pass the SPECIFIC bank
    format (e.g. "monarch") to normalize_transactions, not the generic
    container format ("csv") — otherwise Tier 1 (#8) never matches
    TRANSFER_CATEGORIES and every transfer row silently stays
    income/expense, even though parse_csv() extracted source_category
    correctly."""
    from import_router import import_file

    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2024-03-01,Whole Foods,Groceries,Checking,WHOLE FOODS,,-85.32,\n"
        "2024-03-02,Internal Transfer,Transfer,Checking,XFER TO SAVINGS,,-1000.00,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        result = import_file(f.name, account_id="checking", currency="USD",
                             dry_run=True, keep_original=False)
        by_desc = {t["description"]: t["type"] for t in result["preview"]}
        assert by_desc["WHOLE FOODS"] == "expense"
        assert by_desc["XFER TO SAVINGS"] == "transfer"
    finally:
        os.unlink(f.name)


def test_route_by_account_off_by_default(isolated_finance_dir):
    """Without opting in, every row still lands on the passed-in account_id —
    existing single-account behavior is unchanged."""
    from import_router import import_file
    from account_manager import add_account

    add_account({"id": "chk", "name": "Checking", "type": "checking"})
    add_account({"id": "sav", "name": "Savings", "type": "savings"})

    csv_content = (
        "Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags\n"
        "2024-03-01,Spotify,Subscriptions,Checking,SPOTIFY,,-9.99,\n"
        "2024-03-02,Payroll,Paycheck,Savings,DEPOSIT,,1000.00,\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        result = import_file(f.name, account_id="chk", currency="USD",
                             dry_run=True, keep_original=False)
        assert "routed_by_account" not in result
        assert all(t["account_id"] == "chk" for t in result["preview"])
    finally:
        os.unlink(f.name)
