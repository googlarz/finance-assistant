"""v4.2.4 final: no writes while the data dir is encrypted; unparseable amounts are skipped, not 0.00."""

import asyncio

import pytest

from scripts import data_safety as ds
from scripts.finance_storage import ensure_subdir, get_finance_dir, get_transactions_path, save_json

PASS = "Corr3ct-Horse-Battery!"
needs_crypto = pytest.mark.skipif(not ds._CRYPTO_AVAILABLE, reason="cryptography missing")


def _encrypt():
    save_json(ensure_subdir("accounts") / "accounts.json", {"a": 1})
    ds.encrypt_sensitive_files(PASS)
    assert ds.get_encryption_status()["encrypted"] > 0


@needs_crypto
def test_save_json_refuses_new_paths_while_encrypted():
    _encrypt()
    new_path = get_transactions_path("brand_new_account", 2031)
    with pytest.raises(RuntimeError, match="encrypted"):
        save_json(new_path, {"transactions": []})
    with pytest.raises(RuntimeError, match="encrypted"):
        save_json(get_finance_dir() / "fresh_top_level.json", {"x": 1})
    assert not new_path.exists() and not (get_finance_dir() / "fresh_top_level.json").exists()
    ds.decrypt_sensitive_files(PASS)
    save_json(new_path, {"transactions": []})  # writable again
    assert new_path.exists()


@needs_crypto
def test_add_transaction_refused_while_encrypted_and_touches_nothing(isolated_finance_dir_db):
    from transaction_logger import add_transaction
    save_json(ensure_subdir("accounts") / "accounts.json", {"a": 1})
    ds.encrypt_sensitive_files(PASS)
    db = get_finance_dir() / "finance.db"
    before = db.read_bytes()
    with pytest.raises(RuntimeError, match="encrypted"):
        add_transaction("2031-05-01", "expense", -5.0, "food", "coffee", account_id="newacc")
    assert db.read_bytes() == before
    assert not get_transactions_path("newacc", 2031).exists()


@needs_crypto
def test_mcp_write_tools_return_clear_error_while_encrypted():
    pytest.importorskip("mcp")
    import mcp_server
    _encrypt()

    def call(name, args):
        return asyncio.run(mcp_server.mcp.call_tool(name, args))

    for name, args in [
        ("add_transaction", {"date": "2031-05-01", "amount": -5.0, "description": "coffee"}),
        ("add_account", {"name": "New"}),
        ("assert_balance", {"account_id": "default", "balance": 1.0}),
        ("commit_import", {"file_path": "x.csv", "expected_to_import": 1}),
        ("onboard_step", {"step": "basics", "answer": "hi"}),
    ]:
        text = call(name, args).content[0].text
        assert "encrypted" in text and "decrypt" in text, name
    assert not get_transactions_path("default", 2031).exists()


def test_unparseable_amount_is_skipped_and_counted_zero_is_kept(tmp_path):
    from csv_importer import parse_csv
    f = tmp_path / "bank.csv"
    f.write_text(
        "Date,Description,Amount\n"
        "2024-03-01,Rent,-100.00\n"
        "2024-03-02,Garbled,12x4\n"
        "2024-03-03,Fee waived,0.00\n"
        '2024-03-04,Refund,"0,00"\n',
        encoding="utf-8",
    )
    rows = parse_csv(str(f))
    assert [(r["description"], r["amount"]) for r in rows] == [
        ("Rent", -100.0), ("Fee waived", 0.0), ("Refund", 0.0),
    ]
    assert rows.skipped_bad_amount == 1


def test_bad_amount_skipped_in_split_columns_and_semicolon_file(tmp_path):
    from csv_importer import parse_csv
    split = tmp_path / "split.csv"
    split.write_text("Date,Description,Debit,Credit\n2024-03-01,Ok,10.00,\n2024-03-02,Bad,oops,\n", encoding="utf-8")
    rows = parse_csv(str(split))
    assert [r["description"] for r in rows] == ["Ok"] and rows.skipped_bad_amount == 1

    semi = tmp_path / "semi.csv"
    semi.write_text("Datum;Verwendungszweck;Betrag\n01.03.2024;Miete;-1.000,50\n02.03.2024;Kaputt;n/a\n03.03.2024;Null;0,00\n", encoding="utf-8")
    rows = parse_csv(str(semi))
    assert [(r["description"], r["amount"]) for r in rows] == [("Miete", -1000.5), ("Null", 0.0)]
    assert rows.skipped_bad_amount == 1
