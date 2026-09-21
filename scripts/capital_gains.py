"""
Realized capital gains from recorded trades (FIFO) and a rough tax estimate.

Rule sets are 2025-era, simplified, and NOT verified against an official source
in this repo (no provenance/contract like locales/*): treat estimates as a
planning aid, not a filing figure. Supported: de, uk, ie. Other locales get the
gains with no tax figure.

Assumptions (also returned in the result so nothing is silent):
  de  Abgeltungsteuer 25% + 5.5% Soli on it; Sparer-Pauschbetrag EUR 1,000
      (2,000 joint); 30% Teilfreistellung on ETF gains/losses; no church tax.
  uk  Annual exempt amount GBP 3,000; 24% (higher band) or 18% (basic band).
  ie  33% above the EUR 1,270 annual exemption.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

try:
    from investment_tracker import get_trades, get_portfolio
    from currency import to_currency
    from profile_manager import get_locale, get_primary_currency
except ImportError:  # pragma: no cover
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from investment_tracker import get_trades, get_portfolio
    from currency import to_currency
    from profile_manager import get_locale, get_primary_currency


def realized_gains(year: int, symbol: Optional[str] = None) -> list[dict]:
    """FIFO disposals in `year`, in the primary currency (fees folded into cost/proceeds)."""
    primary = get_primary_currency()
    asset_type = {h.get("symbol"): h.get("type", "stock") for h in get_portfolio()["holdings"]}
    symbols = {t["symbol"] for t in get_trades()}
    out: list[dict] = []
    for sym in sorted(symbols if not symbol else {symbol.upper()}):
        lots: list[dict] = []
        for t in sorted(get_trades(sym), key=lambda t: (t["date"], t["side"] != "buy")):
            cur = t.get("currency", primary)
            if t["side"] == "buy":
                fee = t.get("fees", 0.0) / t["quantity"] if t["quantity"] else 0.0
                lots.append({"date": t["date"], "q": t["quantity"],
                             "unit_cost": to_currency(t["price"] + fee, cur, primary)})
                continue
            remaining = t["quantity"]
            sell_fee = to_currency(t.get("fees", 0.0), cur, primary)
            unit_proceeds = to_currency(t["price"], cur, primary)
            while remaining > 1e-9 and lots:
                take = min(remaining, lots[0]["q"])
                lot = lots[0]
                if t["date"][:4] == str(year):
                    share_fee = sell_fee * take / t["quantity"] if t["quantity"] else 0.0
                    proceeds = take * unit_proceeds - share_fee
                    cost = take * lot["unit_cost"]
                    held = (date.fromisoformat(t["date"]) - date.fromisoformat(lot["date"])).days
                    out.append({"symbol": sym, "sell_date": t["date"], "quantity": round(take, 8),
                                "proceeds": round(proceeds, 2), "cost": round(cost, 2),
                                "gain": round(proceeds - cost, 2), "holding_days": held,
                                "type": asset_type.get(sym, "stock")})
                lot["q"] -= take
                remaining -= take
                if lot["q"] <= 1e-9:
                    lots.pop(0)
    return out


def estimate_tax(year: int, locale: Optional[str] = None, *, joint: bool = False,
                 higher_rate: bool = True) -> dict:
    """Net realized gains for `year` and a simplified tax estimate for `locale`."""
    locale = locale or get_locale()
    rows = realized_gains(year)
    gains = round(sum(r["gain"] for r in rows), 2)
    result = {"year": year, "locale": locale, "currency": get_primary_currency(),
              "disposals": rows, "net_gain": gains, "tax": None, "assumptions": []}

    if locale == "de":
        taxable = sum(r["gain"] * (0.70 if r["type"] == "etf" else 1.0) for r in rows)
        allowance = 2000.0 if joint else 1000.0
        base = max(0.0, taxable - allowance)
        tax = base * 0.25 * 1.055
        result.update(taxable_after_teilfreistellung=round(taxable, 2), allowance=allowance,
                      tax=round(tax, 2))
        result["assumptions"] = ["25% Abgeltungsteuer + 5.5% Soli", f"Sparer-Pauschbetrag {allowance:.0f}",
                                 "30% Teilfreistellung on ETFs", "no church tax",
                                 "one pot: losses offset all gains (share-loss pot rules not modelled)"]
    elif locale == "uk":
        base = max(0.0, gains - 3000.0)
        rate = 0.24 if higher_rate else 0.18
        result.update(allowance=3000.0, rate=rate, tax=round(base * rate, 2))
        result["assumptions"] = ["annual exempt amount 3,000", f"{int(rate * 100)}% rate",
                                 "no same-day/30-day matching rules", "no pooled Section 104 cost"]
    elif locale == "ie":
        base = max(0.0, gains - 1270.0)
        result.update(allowance=1270.0, rate=0.33, tax=round(base * 0.33, 2))
        result["assumptions"] = ["33% CGT", "annual exemption 1,270"]
    else:
        result["assumptions"] = [f"no capital-gains rule set for locale {locale!r}; gains only"]
    return result
