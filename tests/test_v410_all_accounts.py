"""v4.1.0: all-accounts totals, currency-aware aggregation, budget actuals refresh."""
import datetime

import document_sorter  # import early: test_receipt_scanner later stubs sys.modules["PIL"], which breaks pypdf


def _y_m():
    t = datetime.date.today()
    return t.year, t.month


def test_totals_span_all_accounts_and_convert(monkeypatch):
    import transaction_logger as tl, account_manager as am, currency
    am.add_account({"name": "A", "type": "checking", "currency": "EUR"})
    am.add_account({"name": "B", "type": "checking", "currency": "USD"})
    y, m = _y_m()
    d = f"{y}-{m:02d}-05"
    tl.add_transaction(d, "expense", -100.0, "food", "x", account_id="a", currency="EUR")
    tl.add_transaction(d, "expense", -50.0, "food", "y", account_id="b", currency="USD")
    monkeypatch.setattr(currency, "convert", lambda amt, f, t, as_of=None: (round(amt * 2, 2), "high"))
    monkeypatch.setattr("profile_manager.get_primary_currency", lambda: "EUR")
    totals = tl.get_totals(account_id="all", year=y, month=m)
    assert totals["food"]["expense"] == 200.0  # 100 + 50*2
    assert tl.get_totals(account_id="a", year=y, month=m)["food"]["expense"] == 100.0


def test_manual_transaction_refreshes_budget_actuals():
    import budget_engine as be, transaction_logger as tl
    y, m = _y_m()
    be.create_budget(y, m, method="custom", income_target=3000, category_limits={"food": 200})
    tl.add_transaction(f"{y}-{m:02d}-03", "expense", -80.0, "food", "shop")
    assert be.get_budget(y, m)["actuals"]["food"]["spent"] == 80.0


def test_import_commit_refreshes_budget_actuals(tmp_path):
    import budget_engine as be, import_router
    y, m = _y_m()
    be.create_budget(y, m, method="custom", income_target=3000, category_limits={"food": 200})
    f = tmp_path / "s.csv"
    f.write_text(f"date,amount,description\n{y}-{m:02d}-04,-42.00,REWE MARKT\n")
    r = import_router.import_file(str(f), account_id="default", dry_run=False, keep_original=False)
    assert r["imported"] == 1
    spent = sum(v["spent"] for v in be.get_budget(y, m)["actuals"].values())
    assert spent == 42.0


def test_find_pairs_scales_and_reads_rates_once(monkeypatch):
    import time, currency, transfer_matcher as tm
    calls = []
    real = currency.get_exchange_rate
    monkeypatch.setattr(currency, "get_exchange_rate",
                        lambda f, t, as_of=None: (calls.append(1), (1.1, "high"))[1])
    rows = []
    for i in range(3000):
        d = f"2025-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"
        cur = "EUR" if i % 2 else "USD"
        acc = "a" if i % 2 else "b"
        rows.append({"id": f"t{i}", "date": d, "amount": (-1) ** i * (10 + i % 500),
                     "currency": cur, "account_id": acc})
    t0 = time.time()
    tm.find_pairs(rows)
    assert time.time() - t0 < 5
    assert len(calls) <= 4  # one rate lookup per currency pair, not per comparison


def test_launchd_plists_pin_project_dir(monkeypatch, capsys, tmp_path):
    import skill
    monkeypatch.setenv("FINANCE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))
    skill._setup_digest()
    skill._setup_watcher()
    out = capsys.readouterr().out
    assert out.count(f"<key>WorkingDirectory</key>\n    <string>{tmp_path.resolve()}</string>") == 2
    assert out.count("<key>FINANCE_PROJECT_DIR</key>") == 2


def test_document_sorter_never_overwrites(monkeypatch, tmp_path):
    ds = document_sorter
    for name, body in (("a.pdf", b"one"), ("b.pdf", b"two")):
        (tmp_path / name).write_bytes(body)
    monkeypatch.setattr(ds, "extract_text", lambda p: "Kindergeld")
    monkeypatch.setattr(ds, "classify_document", lambda t, n: "kindergeld")
    monkeypatch.setattr(ds, "extract_year", lambda t, n: "2025")
    ds.sort_folder(str(tmp_path), dry_run=False)
    moved = sorted(p.read_bytes() for p in tmp_path.rglob("*.pdf"))
    assert moved == [b"one", b"two"]


def test_wipe_demo_keeps_real_rows_in_demo_account():
    import demo_data, transaction_logger as tl, account_manager as am
    demo_data.seed_demo_data()
    tl.add_transaction("2026-01-10", "expense", -33.0, "food", "Real lunch", account_id="dkb-demo")
    demo_data.wipe_demo_data()
    left = tl.get_transactions(account_id="dkb-demo", year=2026)
    assert [t["description"] for t in left] == ["Real lunch"]
    assert any(a["id"] == "dkb-demo" for a in am.list_accounts())  # account kept
    assert not any(a["id"] == "ing-savings-demo" for a in am.list_accounts())


def test_alert_text_uses_profile_currency_symbol():
    import profile_manager, weekly_digest
    from account_manager import add_account
    profile_manager.update_profile({"meta": {"primary_currency": "USD"}})
    add_account({"name": "Checking", "type": "checking", "current_balance": 1000, "currency": "USD"})
    lines = weekly_digest._net_worth_summary(profile_manager.get_profile())
    assert lines and lines[0].startswith("Net worth: $") and "€" not in lines[0]
