"""v4.2.4 regressions: broker import robustness/locale, recurring Feb-29 + resilience,
add_transaction date validation, tax_optimizer donation category + rule-derived amounts."""
import pytest


# ── 1. broker_importer: ragged rows / tab delimiter ──────────────────────────

RAGGED = (
    "Date,Symbol,Action,Quantity,Price\n"
    "2026-01-05,AAPL,Buy,10,150.5,EXTRA,FIELDS\n"
    "2026-01-06,MSFT,Sell,2,300\n"
    "2026-01-07,TSLA,Buy\n"
)


def test_looks_like_broker_survives_ragged_rows(tmp_path):
    import broker_importer as bi
    p = tmp_path / "t.csv"
    p.write_text(RAGGED)
    assert bi.looks_like_broker(str(p)) is True


def test_import_ragged_csv_does_not_crash_and_counts_bad_rows(tmp_path):
    import broker_importer as bi
    p = tmp_path / "t.csv"
    p.write_text(RAGGED)
    r = bi.import_broker_csv(str(p), dry_run=True)
    assert r["total_parsed"] == 2          # extra fields ignored; short row skipped
    assert r["rows_skipped"] == 1


def test_tab_delimited_broker_file_is_recognised(tmp_path):
    import broker_importer as bi
    p = tmp_path / "t.tsv"
    p.write_text("Date\tSymbol\tAction\tQuantity\tPrice\n2026-01-05\tAAPL\tBuy\t10\t150.5\n")
    assert bi.looks_like_broker(str(p)) is True
    r = bi.import_broker_csv(str(p), dry_run=True)
    assert r["total_parsed"] == 1 and r["preview"][0]["price"] == 150.5


def test_unrecognised_file_does_not_crash_parse(tmp_path):
    import broker_importer as bi
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n")
    trades, skipped = bi.parse_broker_csv(str(p))
    assert trades == [] and skipped


# ── 3. thousands vs decimal ambiguity ────────────────────────────────────────

def test_amount_parse_single_separator_three_digits_is_documented_and_hinted():
    from amount_parse import parse_amount
    assert parse_amount("1.000") == 1.0                 # no hint: "." is a decimal point
    assert parse_amount("1.000", decimal=",") == 1000.0
    assert parse_amount("1,000") == 1.0                 # no hint: "," is a decimal comma
    assert parse_amount("1,000", decimal=".") == 1000.0
    assert "ambiguous" in (parse_amount.__doc__ or "").lower()


def test_infer_decimal():
    from amount_parse import infer_decimal
    assert infer_decimal(["1.234,56", "2"]) == ","
    assert infer_decimal(["1,234.56"]) == "."
    assert infer_decimal(["0,5", "1.000"]) == ","
    assert infer_decimal(["1.000", "2.500"]) is None    # genuinely ambiguous
    assert infer_decimal(["1.000.000"]) == ","
    assert infer_decimal(["1,000,000"]) == "."
    assert infer_decimal(["0,5", "0.25"]) is None       # contradictory evidence


def test_german_broker_file_quantities_are_not_1000x_too_small(tmp_path):
    import broker_importer as bi
    p = tmp_path / "de.csv"
    p.write_text("Datum;Symbol;Type;Stück;Kurs\n"
                 "05.01.2026;SAP;Kauf;1.000;12,50\n"
                 "06.01.2026;SAP;Kauf;2.500;13,75\n")
    trades, _ = bi.parse_broker_csv(str(p))
    assert [t["quantity"] for t in trades] == [1000.0, 2500.0]
    assert [t["price"] for t in trades] == [12.5, 13.75]


def test_us_broker_file_with_dot_prices_keeps_decimal_point(tmp_path):
    import broker_importer as bi
    p = tmp_path / "us.csv"
    p.write_text("Date,Symbol,Action,Quantity,Price\n"
                 "2026-01-05,F,Buy,100,1.000\n"
                 "2026-01-06,F,Buy,50,2.500\n")
    trades, _ = bi.parse_broker_csv(str(p))
    assert [t["price"] for t in trades] == [1.0, 2.5]


# ── 2. recurring_engine: Feb 29 + per-item resilience ────────────────────────

def _acc():
    from account_manager import add_account
    add_account({"id": "chk", "name": "Checking", "type": "checking", "currency": "EUR"})


def test_annual_feb29_item_does_not_raise_and_clamps_in_non_leap_years():
    import recurring_engine as re_
    item = {"frequency": "annual", "start_date": "2024-02-29", "day_of_month": 29}
    from datetime import date
    got = re_._calculate_due_dates(item, date(2024, 2, 28), date(2028, 3, 1))
    assert [d.isoformat() for d in got] == [
        "2024-02-29", "2025-02-28", "2026-02-28", "2027-02-28", "2028-02-29"]


def test_generate_is_idempotent_with_feb29_annual_item():
    import recurring_engine as re_, transaction_logger as tl
    _acc()
    re_.add_recurring("Insurance", -120.0, "insurance", frequency="annual", account_id="chk",
                      start_date="2024-02-29")
    re_.add_recurring("Rent", -900.0, "housing", frequency="monthly", account_id="chk",
                      start_date="2025-11-01", day_of_month=1)
    r1 = re_.generate_due_transactions(as_of="2026-03-05")
    n1 = len(tl.get_transactions(account_id="chk", year=2026)) + \
        len(tl.get_transactions(account_id="chk", year=2025)) + \
        len(tl.get_transactions(account_id="chk", year=2024))
    assert r1["generated_count"] == n1 and not r1.get("errors")
    re_.generate_due_transactions(as_of="2026-03-05")
    n2 = len(tl.get_transactions(account_id="chk", year=2026)) + \
        len(tl.get_transactions(account_id="chk", year=2025)) + \
        len(tl.get_transactions(account_id="chk", year=2024))
    assert n2 == n1


def test_one_failing_item_does_not_cause_rebooking_of_others(monkeypatch):
    import recurring_engine as re_, transaction_logger as tl
    _acc()
    good = re_.add_recurring("Rent", -900.0, "housing", frequency="monthly", account_id="chk",
                             start_date="2026-01-01", day_of_month=1)
    bad = re_.add_recurring("Broken", -5.0, "fees", frequency="monthly", account_id="chk",
                            start_date="2026-01-01", day_of_month=1)
    real = re_._calculate_due_dates

    def flaky(item, after, up_to):
        if item["id"] == bad["id"]:
            raise ValueError("boom")
        return real(item, after, up_to)

    monkeypatch.setattr(re_, "_calculate_due_dates", flaky)
    r1 = re_.generate_due_transactions(as_of="2026-03-05")
    assert r1["generated_count"] == 3
    assert [e["recurring_id"] for e in r1["errors"]] == [bad["id"]]
    assert "boom" in r1["errors"][0]["error"]
    r2 = re_.generate_due_transactions(as_of="2026-03-05")
    assert r2["generated_count"] == 0
    assert len(tl.get_transactions(account_id="chk", year=2026)) == 3


def test_failure_mid_item_keeps_progress(monkeypatch):
    import recurring_engine as re_, transaction_logger as tl
    _acc()
    re_.add_recurring("Rent", -900.0, "housing", frequency="monthly", account_id="chk",
                      start_date="2026-01-01", day_of_month=1)
    real_add = re_.add_transaction
    calls = {"n": 0}

    def flaky_add(**kw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("disk full")
        return real_add(**kw)

    monkeypatch.setattr(re_, "add_transaction", flaky_add)
    r1 = re_.generate_due_transactions(as_of="2026-03-05")
    assert r1["generated_count"] == 2 and len(r1["errors"]) == 1
    monkeypatch.setattr(re_, "add_transaction", real_add)
    r2 = re_.generate_due_transactions(as_of="2026-03-05")
    assert r2["generated_count"] == 1                    # only March is left
    assert len(tl.get_transactions(account_id="chk", year=2026)) == 3


def test_session_hygiene_surfaces_recurring_errors(monkeypatch):
    import recurring_engine as re_, session_hygiene as sh
    monkeypatch.setattr(re_, "generate_due_transactions", lambda: {
        "generated_count": 0, "errors": [{"recurring_id": "x1", "error": "boom"}]})
    notes = sh.run()
    assert any("x1" in n and "boom" in n for n in notes)

    def explode():
        raise RuntimeError("kaput")
    monkeypatch.setattr(re_, "generate_due_transactions", explode)
    assert any("kaput" in n for n in sh.run())


# ── 4. add_transaction rejects unparseable dates ─────────────────────────────

@pytest.mark.parametrize("bad", ["not-a-date", "", None, "31.12.2026x"])
def test_add_transaction_rejects_unparseable_date(bad):
    import transaction_logger as tl
    with pytest.raises(ValueError):
        tl.add_transaction(bad, "expense", -5.0, "food", "x")
    assert tl.get_transactions(year=2026) == []


def test_recurring_item_with_corrupt_date_is_reported_not_crash():
    import recurring_engine as re_
    it = re_.add_recurring("X", -1.0, "food", start_date="2026-01-01", day_of_month=1)
    re_.update_recurring(it["id"], {"start_date": "garbage"})
    r = re_.generate_due_transactions(as_of="2026-03-05")
    assert r["generated_count"] == 0 and len(r["errors"]) == 1


# ── 5. tax_optimizer ─────────────────────────────────────────────────────────

def test_ytd_charitable_counts_real_gifts_category():
    from db import get_conn, init_db
    from tax_optimizer import _get_ytd_data
    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO transactions (id, account_id, date, amount, currency, category, "
            "description, type, created_at) VALUES ('g1','a','2026-02-01',-80,'EUR','gifts',"
            "'Spende','expense','2026-02-01')")
        conn.execute(
            "INSERT INTO transactions (id, account_id, date, amount, currency, category, "
            "description, type, created_at) VALUES ('g2','a','2026-02-02',-20,'EUR','food',"
            "'x','expense','2026-02-02')")
        data = _get_ytd_data(conn, 2026)
    assert data["ytd_charitable"] == pytest.approx(80.0)


def _profile():
    return {"meta": {"primary_currency": "EUR", "locale": "de"},
            "employment": {"annual_gross": 120_000}, "family": {"status": "single"},
            "housing": {}, "tax_profile": {"locale": "de", "extra": {}}}


def test_ruerup_cap_follows_tax_year_rules():
    from tax_optimizer import get_de_opportunities
    from locales.de.tax_rules import get_tax_year_rules
    ytd = {"ytd_income": 120_000, "months_elapsed": 12}
    for year in (2025, 2026):
        cap = get_tax_year_rules(year)["ruerup_max_single"]
        opps = get_de_opportunities(_profile(), ytd, year)
        ru = [o for o in opps if "Rürup" in o["action"]][0]
        assert ru["max_deductible_amount"] == pytest.approx(cap)
    assert get_tax_year_rules(2025)["ruerup_max_single"] != get_tax_year_rules(2026)["ruerup_max_single"]


def test_import_skips_bad_date_rows(isolated_finance_dir, tmp_path):
    from import_router import import_file
    f = tmp_path / "x.csv"
    f.write_text("Date,Amount,Description\n2025-01-05,-10.00,Coffee\nTotal,-10.00,Summary\n", encoding="utf-8")
    r = import_file(str(f), "default", dry_run=False)
    assert r.get("imported", 0) <= 1
    assert "error" not in r
