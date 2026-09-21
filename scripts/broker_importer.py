"""
Brokerage trade-history CSV import (buys/sells -> lots -> holdings).

Recognised by headers, not by bank name: a date column, a symbol/ticker/ISIN
column, a quantity column, a price column, and an action/side column whose
values say buy or sell. Trades are recorded via investment_tracker.record_trade
(deduplicated), which also keeps the matching holding's units/cost basis in sync.
"""
from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from typing import Optional

_DATE = ("date", "trade date", "datum", "execution date", "time")
_SYMBOL = ("symbol", "ticker", "isin", "wkn")
_QTY = ("quantity", "shares", "units", "qty", "stück", "anzahl")
_PRICE = ("price", "unit price", "kurs", "price per share", "share price")
_SIDE = ("action", "side", "type", "transaction type", "buy/sell", "order type")
_FEES = ("fees", "fee", "commission", "gebühren", "provision")
_CCY = ("currency", "währung")
_BUY = ("buy", "bought", "kauf", "purchase")
_SELL = ("sell", "sold", "verkauf")


def _pick(headers: list[str], names: tuple) -> Optional[str]:
    for h in headers:
        if h.strip().lower() in names:
            return h
    return None


def _read(file_path: str) -> tuple[list[str], list[dict]]:
    with open(file_path, newline="", encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    delim = ";" if text[:500].count(";") > text[:500].count(",") else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delim))
    return list(rows[0].keys()) if rows else [], rows


def _columns(headers: list[str]) -> Optional[dict]:
    cols = {k: _pick(headers, v) for k, v in
            dict(date=_DATE, symbol=_SYMBOL, qty=_QTY, price=_PRICE, side=_SIDE,
                 fees=_FEES, currency=_CCY).items()}
    return cols if all(cols[k] for k in ("date", "symbol", "qty", "price", "side")) else None


def looks_like_broker(file_path: str) -> bool:
    try:
        headers, rows = _read(file_path)
    except Exception:
        return False
    cols = _columns(headers)
    if not cols:
        return False
    sides = {str(r.get(cols["side"], "")).strip().lower() for r in rows[:50]}
    return any(any(w in s for w in _BUY + _SELL) for s in sides)


def _num(text: str) -> float:
    t = str(text or "").strip().replace("€", "").replace("£", "").replace("$", "").replace(" ", "")
    if not t:
        return 0.0
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    return float(t)


def _date(text: str) -> str:
    t = str(text).strip()[:19]
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r}")


def parse_broker_csv(file_path: str, currency: str = "EUR") -> tuple[list[dict], list[str]]:
    headers, rows = _read(file_path)
    cols = _columns(headers)
    trades, skipped = [], []
    for i, r in enumerate(rows, start=2):
        side_raw = str(r.get(cols["side"], "")).strip().lower()
        side = "buy" if any(w in side_raw for w in _BUY) else "sell" if any(w in side_raw for w in _SELL) else None
        if not side:
            skipped.append(f"row {i}: not a buy/sell ({side_raw!r})")
            continue
        try:
            trades.append({
                "date": _date(r[cols["date"]]),
                "symbol": str(r[cols["symbol"]]).strip().upper(),
                "side": side,
                "quantity": abs(_num(r[cols["qty"]])),
                "price": abs(_num(r[cols["price"]])),
                "fees": abs(_num(r.get(cols["fees"], 0))) if cols["fees"] else 0.0,
                "currency": (str(r.get(cols["currency"]) or "").strip().upper() or currency) if cols["currency"] else currency,
            })
        except (ValueError, KeyError) as exc:
            skipped.append(f"row {i}: {exc}")
    return trades, skipped


def trade_id(account_id: str, t: dict) -> str:
    key = f"{account_id}|{t['date']}|{t['symbol']}|{t['side']}|{t['quantity']}|{t['price']}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def import_broker_csv(file_path: str, account_id: str = "default", currency: str = "EUR",
                      dry_run: bool = True) -> dict:
    import os
    from investment_tracker import get_trades, record_trade
    trades, skipped = parse_broker_csv(file_path, currency)
    have = {t["id"] for t in get_trades()}
    new = [dict(t, id=trade_id(account_id, t), account_id=account_id) for t in trades]
    fresh = [t for t in new if t["id"] not in have]
    result = {
        "file": os.path.basename(file_path),
        "format": "broker",
        "account_id": account_id,
        "currency": currency,
        "total_parsed": len(trades),
        "to_import": len(fresh),
        "duplicates_removed": len(new) - len(fresh),
        "rows_skipped": len(skipped),
        "skipped_detail": skipped[:10],
        "preview": fresh[:5],
        "dry_run": dry_run,
    }
    if not dry_run:
        for t in fresh:
            record_trade(t)
        result["imported"] = len(fresh)
    return result
