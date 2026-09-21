"""v4.1.0: broker CSV -> trades/lots -> holdings -> realized gains and tax estimate."""
import capital_gains as cg
import import_router
import investment_tracker as it

CSV = """Date,Ticker,Action,Quantity,Price,Fees,Currency
2024-01-10,VWCE,Buy,10,100.00,1.00,EUR
2024-06-01,VWCE,Buy,10,120.00,1.00,EUR
2025-03-01,VWCE,Sell,15,130.00,1.50,EUR
"""


def _import(tmp_path, dry_run=False):
    f = tmp_path / "broker.csv"
    f.write_text(CSV)
    return import_router.import_file(str(f), account_id="depot", dry_run=dry_run, keep_original=False)


def test_broker_csv_routes_and_dry_run_writes_nothing(tmp_path):
    r = _import(tmp_path, dry_run=True)
    assert r["format"] == "broker" and r["to_import"] == 3 and it.get_trades() == []


def test_import_updates_holding_and_is_idempotent(tmp_path):
    _import(tmp_path)
    r2 = _import(tmp_path)
    assert r2["duplicates_removed"] == 3 and r2["to_import"] == 0
    h = [h for h in it.get_portfolio()["holdings"] if h["symbol"] == "VWCE"][0]
    assert h["units"] == 5.0
    assert h["cost_basis"] == 5 * (120.0 + 0.1)  # 5 units left of the 2nd lot, fee per unit 0.10


def test_fifo_gain_and_de_tax(tmp_path, monkeypatch):
    _import(tmp_path)
    monkeypatch.setattr(cg, "get_primary_currency", lambda: "EUR")
    rows = cg.realized_gains(2025)
    # 10 units from lot 1 (cost 100.10) + 5 from lot 2 (cost 120.10); proceeds 130 less fee 1.50 pro rata
    assert sum(r["quantity"] for r in rows) == 15
    expected = 15 * 130 - 1.5 - (10 * 100.10 + 5 * 120.10)
    assert abs(sum(r["gain"] for r in rows) - expected) < 0.02
    est = cg.estimate_tax(2025, "de")
    assert abs(est["tax"] - round(max(0, expected - 1000) * 0.25 * 1.055, 2)) < 0.05
    assert cg.estimate_tax(2025, "uk")["tax"] == 0.0  # under the 3,000 exempt amount
    assert cg.estimate_tax(2025, "fr")["tax"] is None
