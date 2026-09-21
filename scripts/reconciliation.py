"""
Balance-assertion reconciliation.

The user (or an import) states an account's balance on a date. Between two
consecutive assertions, the change in stated balance must equal the sum of the
transactions booked in that window; any difference is money the ledger can't
explain (missing rows, dropped imports, wrong signs).

Assertions live in .finance/accounts/balance_assertions.json:
  [{"account_id", "date", "balance"}]
"""
from __future__ import annotations

from datetime import date
from typing import Optional

try:
    from finance_storage import ensure_subdir, load_json, save_json
    from account_manager import list_accounts
    from transaction_logger import get_transactions
    from currency import to_currency
except ImportError:  # pragma: no cover
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import ensure_subdir, load_json, save_json
    from account_manager import list_accounts
    from transaction_logger import get_transactions
    from currency import to_currency

DEFAULT_THRESHOLD = 1.00  # account currency; below this is rounding noise


def _path():
    return ensure_subdir("accounts") / "balance_assertions.json"


def _load() -> list[dict]:
    data = load_json(_path(), default=[])
    return data if isinstance(data, list) else []


def assert_balance(account_id: str, balance: float, on: Optional[str] = None) -> dict:
    """Record that `account_id` held `balance` at end of day `on` (default today)."""
    on = on or date.today().isoformat()
    items = [a for a in _load() if not (a["account_id"] == account_id and a["date"] == on)]
    entry = {"account_id": account_id, "date": on, "balance": round(float(balance), 2)}
    items.append(entry)
    items.sort(key=lambda a: (a["account_id"], a["date"]))
    save_json(_path(), items)
    return entry


def _flows_between(account_id: str, start: str, end: str, currency: str) -> float:
    """Sum of signed amounts with start < date <= end, in the account's currency."""
    y0, y1 = int(start[:4]), int(end[:4])
    total = 0.0
    for year in range(y0, y1 + 1):
        for t in get_transactions(account_id=account_id, year=year):
            d = str(t.get("date", ""))[:10]
            if start < d <= end:
                total += to_currency(float(t.get("amount", 0)), t.get("currency"), currency)
    return round(total, 2)


def check_account(account_id: str, threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    """Unexplained deltas between consecutive assertions for one account."""
    acc = next((a for a in list_accounts() if a["id"] == account_id), {})
    currency = acc.get("currency", "EUR")
    points = [a for a in _load() if a["account_id"] == account_id]
    out = []
    for prev, cur in zip(points, points[1:]):
        expected_change = round(cur["balance"] - prev["balance"], 2)
        booked = _flows_between(account_id, prev["date"], cur["date"], currency)
        delta = round(expected_change - booked, 2)
        if abs(delta) >= threshold:
            out.append({"account_id": account_id, "from": prev["date"], "to": cur["date"],
                        "stated_change": expected_change, "booked": booked,
                        "unexplained": delta, "currency": currency})
    return out


def check_all(threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    ids = sorted({a["account_id"] for a in _load()})
    return [d for i in ids for d in check_account(i, threshold)]


def format_alerts(deltas: list[dict]) -> list[str]:
    lines = []
    for d in deltas:
        direction = "missing income/credits" if d["unexplained"] > 0 else "missing spending/debits"
        lines.append(
            f"{d['account_id']}: {d['unexplained']:+,.2f} {d['currency']} unexplained between "
            f"{d['from']} and {d['to']} ({direction}). Statement says the balance moved "
            f"{d['stated_change']:+,.2f}; transactions account for {d['booked']:+,.2f}."
        )
    return lines
