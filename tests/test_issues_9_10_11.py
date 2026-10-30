"""Regression tests for issues #9, #10, #11 (reported by @mattabate)."""
import csv_importer
from amount_parse import parse_amount
from csv_importer import KNOWN_FORMATS, detect_bank_format, parse_csv
from ofx_importer import _map_trntype, parse_ofx


# ── #10: German thousands separators ─────────────────────────────────────────

def test_parse_amount_last_separator_is_the_decimal():
    assert parse_amount("1.234,56") == 1234.56
    assert parse_amount("1,234.56") == 1234.56
    assert parse_amount("-1.234.567,89") == -1234567.89
    assert parse_amount("45,60") == 45.60
    assert parse_amount("€ 1.000,00") == 1000.0


def test_generic_csv_german_thousands(tmp_path):
    f = tmp_path / "g.csv"
    f.write_text('Date,Amount,Description\n01.10.2026,"1.234,56",Rent\n02.10.2026,"1,234.56",Pay\n')
    assert [t["amount"] for t in parse_csv(str(f))] == [1234.56, 1234.56]


def _ofx_file(tmp_path, trntype, amount):
    f = tmp_path / "a.ofx"
    f.write_text(
        "OFXHEADER:100\n<OFX><BANKTRANLIST><STMTTRN><TRNTYPE>%s<DTPOSTED>20261001"
        "<TRNAMT>%s<FITID>1<NAME>X</STMTTRN></BANKTRANLIST></OFX>" % (trntype, amount)
    )
    return parse_ofx(str(f))[0]


def test_ofx_german_thousands(tmp_path):
    assert _ofx_file(tmp_path, "DEBIT", "-1.234,56")["amount"] == -1234.56
    assert _ofx_file(tmp_path, "CREDIT", "45,60")["amount"] == 45.60


# ── #11: OFX refunds and transfers ───────────────────────────────────────────

def test_ofx_positive_pos_is_income_and_negative_is_expense():
    assert _map_trntype("POS", 50.0) == "income"
    assert _map_trntype("POS", -50.0) == "expense"
    assert _map_trntype("OTHER", 12.0) == "income"


def test_ofx_xfer_is_transfer_whatever_the_sign():
    assert _map_trntype("XFER", 50.0) == "transfer"
    assert _map_trntype("XFER", -50.0) == "transfer"


def test_ofx_rows_carry_the_new_types(tmp_path):
    assert _ofx_file(tmp_path, "POS", "50.00")["type"] == "income"
    assert _ofx_file(tmp_path, "XFER", "50.00")["type"] == "transfer"
    assert _ofx_file(tmp_path, "CREDIT", "50.00")["type"] == "income"


def test_ofx_refund_reduces_nothing_it_is_not_spending(tmp_path):
    import transaction_logger as tl
    row = _ofx_file(tmp_path, "POS", "50.00")
    assert tl.is_expense_flow(row) is False


# ── #9: Commerzbank shadowed by Sparkasse ────────────────────────────────────

def _header(fmt):
    cols = list(dict.fromkeys(fmt["detect"] + [fmt[k] for k in ("date", "amount", "description", "payee") if fmt.get(k)]))
    return fmt.get("delimiter", ",").join(cols)


def test_commerzbank_header_detects_as_commerzbank(tmp_path):
    f = tmp_path / "c.csv"
    f.write_text("Buchungstag;Wertstellung;Umsatzart;Buchungstext;Betrag;Auftraggeber / Begünstigter\n"
                 "01.10.2026;01.10.2026;Lastschrift;Miete;-1.200,00;Vermieter\n", encoding="latin-1")
    assert detect_bank_format(str(f)) == "commerzbank"
    row = parse_csv(str(f), bank_format="commerzbank")[0]
    assert row["description"] and row["payee"] == "Vermieter"


def test_sparkasse_still_detects_as_sparkasse(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("Buchungstag;Wertstellung;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Betrag\n"
                 "01.10.26;01.10.26;Miete;Vermieter;-1.200,00\n", encoding="latin-1")
    assert detect_bank_format(str(f)) == "sparkasse"


def test_every_header_format_detects_as_itself(tmp_path):
    """Catches the whole class: one format's detect columns shadowing another's."""
    wrong = {}
    for name, fmt in KNOWN_FORMATS.items():
        if not fmt["detect"]:
            continue  # positional formats
        f = tmp_path / f"{name}.csv"
        f.write_text(_header(fmt) + "\n", encoding=fmt.get("encoding", "utf-8"))
        got = detect_bank_format(str(f))
        if got != name:
            wrong[name] = got
    assert not wrong, wrong


def test_repeated_single_separator_is_thousands_not_decimal():
    assert parse_amount("1,234,567") == 1234567.0
    assert parse_amount("1.234.567") == 1234567.0
    assert parse_amount("45,60") == 45.60  # one comma still a decimal comma


def test_accounting_negatives():
    assert parse_amount("(1.234,56)") == -1234.56
    assert parse_amount("(45.60)") == -45.60
    assert parse_amount("1.234,56-") == -1234.56
    assert parse_amount("−5,00") == -5.0
    assert parse_amount("-5,00") == -5.0


def test_ofx_without_curdef_uses_the_callers_currency(tmp_path):
    f = tmp_path / "a.ofx"
    f.write_text("OFXHEADER:100\n<OFX><BANKTRANLIST><STMTTRN><TRNTYPE>POS<DTPOSTED>20261001"
                 "<TRNAMT>5.00<FITID>1<NAME>X</STMTTRN></BANKTRANLIST></OFX>")
    assert parse_ofx(str(f), currency="EUR")[0]["currency"] == "EUR"
    assert parse_ofx(str(f))[0]["currency"] == "USD"
