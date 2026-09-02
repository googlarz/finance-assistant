"""
Direct end-to-end tests for the file importers (mt940, ofx, csv, pdf).

test_import_system.py covers helpers and format detection; these tests feed
whole files through the top-level parse functions and assert the transaction
dicts that come out — including malformed-input robustness (a corrupt bank
file must never crash or silently import wrong amounts).
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from mt940_importer import parse_mt940
from ofx_importer import parse_ofx
from csv_importer import parse_csv
import pdf_importer


# ── MT940 ─────────────────────────────────────────────────────────────────────

_MT940_SAMPLE = """:20:STARTUMSE
:25:12345678/0000123456
:28C:00001/001
:60F:C240101EUR1000,00
:61:2401020102DR52,50NTRFNONREF
:86:105?00SEPA-LASTSCHRIFT?20EREF+123?21MREF+ABC?32NETFLIX INTERNATIONAL
:61:2401050105CR2500,00NTRFNONREF
:86:166?00GUTSCHRIFT?20LOHN GEHALT?32ACME GMBH
:62F:C240131EUR3447,50
"""


@pytest.fixture
def mt940_file(tmp_path):
    p = tmp_path / "statement.sta"
    p.write_text(_MT940_SAMPLE, encoding="utf-8")
    return str(p)


def test_mt940_parses_both_transactions(mt940_file):
    txns = parse_mt940(mt940_file)
    assert len(txns) == 2


def test_mt940_debit_is_negative_credit_is_positive(mt940_file):
    txns = parse_mt940(mt940_file)
    debit, credit = txns[0], txns[1]
    assert debit["amount"] == -52.50
    assert credit["amount"] == 2500.00


def test_mt940_dates_iso(mt940_file):
    txns = parse_mt940(mt940_file)
    assert txns[0]["date"] == "2024-01-02"
    assert txns[1]["date"] == "2024-01-05"


def test_mt940_currency_extracted(mt940_file):
    txns = parse_mt940(mt940_file)
    assert txns[0]["currency"] == "EUR"


def test_mt940_reversal_marks_not_dropped(tmp_path):
    """Regression: field 61's credit/debit mark can legitimately be RC/RD
    (storno/reversal), not just C/D — the old regex only matched [CD],
    silently dropping any reversal transaction from the imported statement
    with no error."""
    sample = (
        ":20:STARTUMSE\n"
        ":25:12345678/0000123456\n"
        ":28C:00001/001\n"
        ":60F:C240101EUR1000,00\n"
        ":61:240106RD75,00NTRFNONREF\n"  # reversal of a debit -> nets positive
        ":86:105?00STORNO\n"
        ":61:240107RC30,00NTRFNONREF\n"  # reversal of a credit -> nets negative
        ":86:105?00STORNO\n"
        ":62F:C240131EUR1045,00\n"
    )
    p = tmp_path / "reversal.sta"
    p.write_text(sample, encoding="utf-8")
    txns = parse_mt940(str(p))
    assert len(txns) == 2
    assert txns[0]["amount"] == 75.00
    assert txns[1]["amount"] == -30.00


def test_mt940_garbage_file_returns_empty(tmp_path):
    p = tmp_path / "garbage.sta"
    p.write_text("this is not an mt940 file at all\n\x00\x01binary junk", encoding="utf-8")
    assert parse_mt940(str(p)) == []


def test_mt940_empty_file_returns_empty(tmp_path):
    p = tmp_path / "empty.sta"
    p.write_text("", encoding="utf-8")
    assert parse_mt940(str(p)) == []


# ── OFX ───────────────────────────────────────────────────────────────────────

_OFX_SGML = """OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<CURDEF>USD
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20240115
<TRNAMT>-45.99
<FITID>202401151
<NAME>WHOLE FOODS
<MEMO>GROCERIES
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20240120120000
<TRNAMT>3200.00
<FITID>202401201
<NAME>EMPLOYER PAYROLL
</BANKTRANLIST>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


@pytest.fixture
def ofx_sgml_file(tmp_path):
    p = tmp_path / "statement.ofx"
    p.write_text(_OFX_SGML, encoding="utf-8")
    return str(p)


def test_ofx_sgml_parses_both_transactions(ofx_sgml_file):
    txns = parse_ofx(ofx_sgml_file)
    assert len(txns) == 2


def test_ofx_sgml_amounts_and_signs(ofx_sgml_file):
    txns = parse_ofx(ofx_sgml_file)
    assert txns[0]["amount"] == -45.99
    assert txns[1]["amount"] == 3200.00


def test_ofx_comma_decimal_not_inflated_100x(tmp_path):
    """Regression: OFX spec mandates '.' as the decimal separator, but some
    non-compliant European exports use ',' instead. Stripping every comma
    as a thousands separator silently inflated those amounts 100x —
    "45,60" (meaning 45.60) became 4560.0."""
    sample = _OFX_SGML.replace("<TRNAMT>-45.99", "<TRNAMT>-45,60")
    p = tmp_path / "comma.ofx"
    p.write_text(sample, encoding="utf-8")
    txns = parse_ofx(str(p))
    assert txns[0]["amount"] == -45.60


def test_ofx_us_thousands_separator_still_works(tmp_path):
    """US-style '1,234.56' (comma=thousands, dot=decimal) must still parse
    correctly — the fix must not regress the common case."""
    sample = _OFX_SGML.replace("<TRNAMT>3200.00", "<TRNAMT>1,234.56")
    p = tmp_path / "thousands.ofx"
    p.write_text(sample, encoding="utf-8")
    txns = parse_ofx(str(p))
    assert txns[1]["amount"] == 1234.56


def test_ofx_sgml_dates_with_and_without_time(ofx_sgml_file):
    txns = parse_ofx(ofx_sgml_file)
    assert txns[0]["date"] == "2024-01-15"
    assert txns[1]["date"] == "2024-01-20"


def test_ofx_currency_and_import_ref(ofx_sgml_file):
    txns = parse_ofx(ofx_sgml_file)
    assert txns[0]["currency"] == "USD"
    assert txns[0]["import_ref"] == "ofx:202401151"


def test_ofx_garbage_file_returns_empty(tmp_path):
    p = tmp_path / "garbage.ofx"
    p.write_text("<html><body>Not an OFX file</body></html>", encoding="utf-8")
    assert parse_ofx(str(p)) == []


# ── CSV ───────────────────────────────────────────────────────────────────────

_DKB_CSV = '''"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"
"02.01.24";"02.01.24";"Gebucht";"Max Mustermann";"NETFLIX";"Netflix Abo";"Ausgang";"DE00000000000000000000";"-12,99";"";"";""
"05.01.24";"05.01.24";"Gebucht";"ACME GmbH";"Max Mustermann";"Gehalt Januar";"Eingang";"DE00000000000000000000";"2.500,00";"";"";""
'''


def test_csv_generic_fallback_parses(tmp_path):
    p = tmp_path / "generic.csv"
    p.write_text("Date,Description,Amount\n2024-01-02,Netflix,-12.99\n2024-01-05,Salary,2500.00\n",
                 encoding="utf-8")
    txns = parse_csv(str(p))
    assert len(txns) == 2
    assert txns[0]["amount"] == -12.99
    assert txns[1]["amount"] == 2500.00


def test_csv_empty_file_returns_empty(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    assert parse_csv(str(p)) == []


def test_csv_headers_only_returns_empty(tmp_path):
    p = tmp_path / "headers.csv"
    p.write_text("Date,Description,Amount\n", encoding="utf-8")
    assert parse_csv(str(p)) == []


def test_csv_formula_injection_neutralized(tmp_path):
    """Merchant cells starting with = must not survive as live formulas."""
    p = tmp_path / "inject.csv"
    p.write_text('Date,Description,Amount\n2024-01-02,"=cmd|calc",-1.00\n', encoding="utf-8")
    txns = parse_csv(str(p))
    assert len(txns) == 1
    assert not txns[0]["description"].startswith("="), (
        f"Formula injection survived: {txns[0]['description']!r}"
    )


# ── PDF ───────────────────────────────────────────────────────────────────────

def test_pdf_detect_bank_dkb():
    assert pdf_importer.detect_pdf_bank("DKB - Deutsche Kreditbank AG Kontoauszug") == "dkb"


def test_pdf_detect_bank_generic():
    assert pdf_importer.detect_pdf_bank("Some Unknown Bank Statement") == "generic"


def test_pdf_parse_german_amount():
    assert pdf_importer._parse_german_amount("1.234,56") == 1234.56
    assert pdf_importer._parse_german_amount("-52,50") == -52.50
    assert pdf_importer._parse_german_amount("not a number") is None


def test_pdf_parse_date():
    assert pdf_importer._parse_date("02.01.2024") == "2024-01-02"
    assert pdf_importer._parse_date("garbage") is None


def test_pdf_missing_dependency_raises_clear_error(tmp_path, monkeypatch):
    """Without pdfplumber, parse_pdf must raise a clear ImportError, not crash obscurely."""
    monkeypatch.setattr(pdf_importer, "_PDFPLUMBER_AVAILABLE", False)
    p = tmp_path / "statement.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(ImportError, match="pdfplumber"):
        pdf_importer.parse_pdf(str(p))
