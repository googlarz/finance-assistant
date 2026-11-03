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

try:
    from amount_parse import parse_amount, infer_decimal
except ImportError:  # pragma: no cover
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from amount_parse import parse_amount, infer_decimal

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


def _read(file_path: str) -> tuple[list[str], list[dict], str]:
    with open(file_path, newline="", encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    lines = text.splitlines()
    head = lines[0] if lines else ""
    delim = max((",", ";", "\t"), key=lambda d: head.count(d))  # ties -> ","
    reader = csv.DictReader(lines, delimiter=delim)
    headers = [h for h in (reader.fieldnames or []) if isinstance(h, str)]
    rows = []
    for raw in reader:
        # Rows longer than the header put the surplus under a None key (as a
        # list); shorter rows leave None values. Keep only str -> str cells.
        rows.append({k: (v if isinstance(v, str) else "") for k, v in raw.items()
                     if isinstance(k, str)})
    return headers, rows, delim


def _columns(headers: list[str]) -> Optional[dict]:
    cols = {k: _pick(headers, v) for k, v in
            dict(date=_DATE, symbol=_SYMBOL, qty=_QTY, price=_PRICE, side=_SIDE,
                 fees=_FEES, currency=_CCY).items()}
    return cols if all(cols[k] for k in ("date", "symbol", "qty", "price", "side")) else None


def looks_like_broker(file_path: str) -> bool:
    try:
        headers, rows, _ = _read(file_path)
    except Exception:
        return False
    cols = _columns(headers)
    if not cols:
        return False
    sides = {str(r.get(cols["side"], "")).strip().lower() for r in rows[:50]}
    return any(any(w in s for w in _BUY + _SELL) for s in sides)


def _num(text: str, decimal: Optional[str] = None) -> float:
    return parse_amount(text, decimal)


def _date(text: str) -> str:
    t = str(text).strip()[:19]
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r}")


def _column_decimals(rows: list[dict], cols: dict, delim: str) -> dict:
    """Decimal separator per numeric column: the column's own evidence, else the
    whole file's, else the delimiter's convention (";" files are German-style
    decimal commas, everything else decimal points)."""
    keys = [k for k in ("qty", "price", "fees") if cols.get(k)]
    values = {k: [r.get(cols[k], "") for r in rows] for k in keys}
    file_wide = infer_decimal([v for vs in values.values() for v in vs])
    default = "," if delim == ";" else "."
    return {k: infer_decimal(values[k]) or file_wide or default for k in keys}


def parse_broker_csv(file_path: str, currency: str = "EUR") -> tuple[list[dict], list[str]]:
    headers, rows, delim = _read(file_path)
    cols = _columns(headers)
    if not cols:
        return [], ["not a recognised broker trade file (need date, symbol, quantity, price, side columns)"]
    dec = _column_decimals(rows, cols, delim)
    trades, skipped = [], []
    for i, r in enumerate(rows, start=2):
        side_raw = str(r.get(cols["side"], "")).strip().lower()
        side = "buy" if any(w in side_raw for w in _BUY) else "sell" if any(w in side_raw for w in _SELL) else None
        if not side:
            skipped.append(f"row {i}: not a buy/sell ({side_raw!r})")
            continue
        try:
            quantity = abs(_num(r[cols["qty"]], dec["qty"]))
            if not quantity:  # empty/zero cell, e.g. a row cut short
                raise ValueError("missing quantity")
            trades.append({
                "date": _date(r[cols["date"]]),
                "symbol": str(r[cols["symbol"]]).strip().upper(),
                "side": side,
                "quantity": quantity,
                "price": abs(_num(r[cols["price"]], dec["price"])),
                "fees": abs(_num(r.get(cols["fees"], 0), dec["fees"])) if cols["fees"] else 0.0,
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
