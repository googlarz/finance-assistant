"""Tests for scripts/export_data.py (v4.2.4)."""
import csv
import sys

import export_data
from transaction_logger import add_transaction


def _seed():
    add_transaction(amount=-12.5, description="Coffee", category="food", type="expense",
                    date="2024-03-02", account_id="default", currency="EUR")
    add_transaction(amount=-40, description="=HYPERLINK(1)", category="misc", type="expense",
                    date="2025-05-09", account_id="default", currency="EUR")


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_csv_content_and_bom(isolated_finance_dir):
    _seed()
    res = export_data.export_transactions_csv()
    assert res["rows"] == 2
    assert "exports" in res["path"]
    raw = open(res["path"], "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = _read(res["path"])
    assert list(rows[0].keys()) == export_data.COLUMNS
    assert rows[0]["description"] == "Coffee" and rows[0]["amount"] == "-12.5"
    assert rows[1]["description"].startswith("'=")


def test_year_filter(isolated_finance_dir):
    _seed()
    res = export_data.export_transactions_csv(year=2025)
    rows = _read(res["path"])
    assert len(rows) == 1 and rows[0]["date"].startswith("2025")


def test_no_overwrite(isolated_finance_dir, tmp_path):
    _seed()
    out = str(tmp_path / "out.csv")
    a = export_data.export_transactions_csv(out=out)
    b = export_data.export_transactions_csv(out=out)
    assert a["path"] == out
    assert b["path"] != out and b["path"].endswith("out-1.csv")
    assert len(_read(out)) == 2


def test_xlsx_without_openpyxl(isolated_finance_dir, monkeypatch):
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    res = export_data.export_transactions_xlsx()
    assert "openpyxl" in res["error"]


def test_unknown_kind(isolated_finance_dir):
    assert "error" in export_data.run_export("pdf")


def test_capital_gains_csv_header(isolated_finance_dir):
    res = export_data.export_capital_gains_csv(2024)
    assert res["rows"] == 0
    assert open(res["path"], encoding="utf-8-sig").readline().strip().startswith("symbol,sell_date")
