"""v4.2.4 review findings: near-duplicate matcher, LLM/image date handling,
export signs, exports encryption, generic CSV amount column, doc claims."""
import csv
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import export_data  # noqa: E402
from import_support import descriptions_match  # noqa: E402
from transaction_logger import add_transaction, get_transactions  # noqa: E402

HDR = "Date,Payee,Account number,Transaction type,Payment reference,Amount (EUR)\n"


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


# ── 1. near-duplicate matcher ────────────────────────────────────────────────

def test_exact_match_consumes_ledger_row(tmp_path):
    from import_router import import_file
    first = HDR + "2024-04-03,BVG,DE00,Debit Card,Ticket REF123,-3.50\n"
    import_file(_write(tmp_path, "a.csv", first), account_id="acc", dry_run=False, keep_original=False)
    second = first + "2024-04-03,BVG,DE00,Debit Card,Ticket REF456,-3.50\n"
    r = import_file(_write(tmp_path, "b.csv", second), account_id="acc", dry_run=True, keep_original=False)
    assert r["to_import"] == 1
    assert r["duplicates_removed"] == 1 and r["near_duplicates_removed"] == 0


def test_different_merchants_same_day_amount_both_import(tmp_path):
    from import_router import import_file
    content = (HDR + "2024-04-03,,DE00,Debit Card,Kartenzahlung REWE,-12.50\n"
               "2024-04-03,,DE00,Debit Card,Kartenzahlung ALDI,-12.50\n")
    r = import_file(_write(tmp_path, "a.csv", content), account_id="acc", dry_run=False, keep_original=False)
    assert r["imported"] == 2


def test_descriptions_with_no_text_tokens_never_match():
    assert not descriptions_match("1234 5678", "9999")
    assert not descriptions_match("", "")
    assert not descriptions_match("Kartenzahlung REWE", "Kartenzahlung ALDI")


# ── 2. LLM / image dates ─────────────────────────────────────────────────────

def test_llm_ingest_bad_dates_counted_and_batch_survives(isolated_finance_dir):
    from llm_import import ingest_extracted
    rows = [
        {"date": "2024-13-45", "amount": -5, "description": "bad month"},
        {"date": "garbage-xx", "amount": -6, "description": "garbage"},
        {"date": "2024-05-01", "amount": -7, "description": "good one"},
    ]
    r = ingest_extracted(rows, "acc", "EUR", dry_run=False)
    assert r["skipped_bad_date"] == 2
    assert r["imported"] == 1


def test_llm_ingest_add_transaction_valueerror_does_not_half_fail(isolated_finance_dir, monkeypatch):
    import llm_import
    real = llm_import.add_transaction
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("boom")
        return real(**kw)
    monkeypatch.setattr(llm_import, "add_transaction", flaky)
    rows = [{"date": "2024-05-01", "amount": -7, "description": "one"},
            {"date": "2024-05-02", "amount": -8, "description": "two"}]
    r = llm_import.ingest_extracted(rows, "acc", "EUR", dry_run=False)
    assert r["imported"] == 1 and r["failed_rows"] == 1


def test_image_import_bad_ocr_date_returns_error(isolated_finance_dir, tmp_path, monkeypatch):
    import receipt_scanner
    from import_router import import_file
    img = tmp_path / "r.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    monkeypatch.setattr(receipt_scanner, "scan_to_transaction", lambda p, a: {
        "date": "31/02/xx", "type": "expense", "amount": -5.0, "description": "x",
        "currency": "EUR", "scan_result": {"confidence": "low"}})
    r = import_file(str(img), account_id="acc", format_hint="image", dry_run=False, keep_original=False)
    assert "error" in r


# ── 3. export signs ──────────────────────────────────────────────────────────

def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_export_amounts_signed_and_type_column(isolated_finance_dir):
    add_transaction(amount=50, description="Groceries", category="food", type="expense",
                    date="2024-03-02", account_id="default", currency="EUR")
    add_transaction(amount=1000, description="Salary", category="salary", type="income",
                    date="2024-03-03", account_id="default", currency="EUR")
    rows = {r["description"]: r for r in _read(export_data.export_transactions_csv()["path"])}
    assert float(rows["Groceries"]["amount"]) == -50 and rows["Groceries"]["type"] == "expense"
    assert float(rows["Salary"]["amount"]) == 1000 and rows["Salary"]["type"] == "income"


def test_export_formula_guard_covers_tab_and_cr():
    assert export_data._safe("\t=1+1").startswith("'")
    assert export_data._safe("\r=1+1").startswith("'")


# ── 4. exports encrypted ─────────────────────────────────────────────────────

def test_exports_are_encrypted_and_roundtrip(isolated_finance_dir):
    import data_safety as ds
    if not ds._CRYPTO_AVAILABLE:
        pytest.skip("cryptography missing")
    add_transaction(amount=-9, description="SecretCoffee", category="food", type="expense",
                    date="2024-03-02", account_id="default", currency="EUR")
    path = export_data.export_transactions_csv()["path"]
    assert ds.get_encryption_status()["plaintext_files"].count("exports/" + os.path.basename(path)) == 1
    pw = "correct horse battery 42"
    res = ds.encrypt_sensitive_files(pw)
    assert "exports/" + os.path.basename(path) in res["files"]
    assert b"SecretCoffee" not in open(path, "rb").read()
    ds.decrypt_sensitive_files(pw)
    assert "SecretCoffee" in open(path, encoding="utf-8-sig").read()


# ── 5. generic CSV ───────────────────────────────────────────────────────────

def test_generic_amount_never_picks_date_column(tmp_path):
    from csv_importer import _parse_generic
    p = _write(tmp_path, "g.csv", "Booking date;Value date;Text;Amount\n"
               "03.04.2024;04.04.2024;Coffee;-3,50\n")
    rows = _parse_generic(p, "EUR")
    assert [r["amount"] for r in rows] == [-3.5]
    # only a value-date column and no amount column -> nothing parsed, not a date as number
    p2 = _write(tmp_path, "g2.csv", "Booking date;Value date;Text\n03.04.2024;04.04.2024;Coffee\n")
    assert _parse_generic(p2, "EUR") == []


def test_generic_decimal_inferred_across_column(tmp_path):
    from csv_importer import _parse_generic
    p = _write(tmp_path, "g.csv", "Date;Text;Amount\n"
               "03.04.2024;A;1.234,56\n04.04.2024;B;-1.000\n05.04.2024;C;12,50\n")
    assert [r["amount"] for r in _parse_generic(p, "EUR")] == [1234.56, -1000.0, 12.5]
    p2 = _write(tmp_path, "g2.csv", "Date,Text,Amount\n"
                "2024-04-03,A,\"1,234.56\"\n2024-04-04,B,\"1,000\"\n2024-04-05,C,12.50\n")
    assert [r["amount"] for r in _parse_generic(p2, "EUR")] == [1234.56, 1000.0, 12.5]


# ── 6. docs ──────────────────────────────────────────────────────────────────

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _doc(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


def test_docs_match_code():
    assert "skill.py --decrypt" not in _doc("scripts", "finance_storage.py")
    assert "getpass" not in _doc("docs", "SECURITY.md").replace("no interactive `getpass`", "")
    skill = _doc("SKILL.md")
    assert "`encrypt_sensitive_files(passphrase)`" not in skill
    assert "FINANCE_PASSPHRASE" in skill
    assert "CC%20BY" not in _doc("README.md")
