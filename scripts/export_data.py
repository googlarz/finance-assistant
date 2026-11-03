"""Export transactions (CSV/XLSX) and realized capital gains (CSV).

CSV is UTF-8 with BOM so Excel opens it correctly. XLSX needs openpyxl, which is
optional. Existing files are never overwritten: a numeric suffix is added instead.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

from finance_storage import get_finance_dir

COLUMNS = ["date", "account", "description", "amount", "currency", "category", "payee"]
GAIN_COLUMNS = ["symbol", "sell_date", "quantity", "proceeds", "cost", "gain",
                "holding_days", "type"]
_FIRST_YEAR = 2000


def _safe(value) -> str:
    """Neutralise spreadsheet formula injection in free-text cells."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    n = 1
    while True:
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _resolve_out(out: Optional[str], default_name: str) -> Path:
    path = Path(out).expanduser() if out else get_finance_dir() / "exports" / default_name
    path.parent.mkdir(parents=True, exist_ok=True)
    return _unique_path(path)


def collect_rows(account_id: Optional[str] = None, year: Optional[int] = None,
                 date_from: Optional[str] = None, date_to: Optional[str] = None) -> list:
    """Transactions as export rows. account_id None = all accounts; year None = all years."""
    from transaction_logger import get_transactions
    acct = account_id or "all"
    years = [year] if year else range(_FIRST_YEAR, datetime.now().year + 1)
    rows = []
    for y in years:
        for t in get_transactions(acct, y):
            d = t.get("date", "")
            if (date_from and d < date_from) or (date_to and d > date_to):
                continue
            rows.append({
                "date": d,
                "account": t.get("account_id", acct if acct != "all" else ""),
                "description": t.get("description", ""),
                "amount": t.get("amount", 0),
                "currency": t.get("currency", ""),
                "category": t.get("category", ""),
                "payee": t.get("payee", ""),
            })
    rows.sort(key=lambda r: r["date"])
    return rows


def _name(prefix: str, year, account_id, ext: str) -> str:
    parts = [prefix, str(account_id) if account_id else "all", str(year) if year else "alltime"]
    return "-".join(parts) + "-" + datetime.now().strftime("%Y%m%d") + "." + ext


def export_transactions_csv(account_id=None, year=None, out=None,
                            date_from=None, date_to=None) -> dict:
    rows = collect_rows(account_id, year, date_from, date_to)
    path = _resolve_out(out, _name("transactions", year, account_id, "csv"))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r[c] if c in ("date", "amount", "currency") else _safe(r[c])
                        for c in COLUMNS])
    return {"path": str(path), "rows": len(rows)}


def export_transactions_xlsx(account_id=None, year=None, out=None,
                             date_from=None, date_to=None) -> dict:
    try:
        import openpyxl
    except ImportError:
        return {"error": "XLSX export needs openpyxl (pip install openpyxl). "
                         "Use --export csv instead; Excel opens it directly."}
    rows = collect_rows(account_id, year, date_from, date_to)
    path = _resolve_out(out, _name("transactions", year, account_id, "xlsx"))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append(COLUMNS)
    for r in rows:
        ws.append([r[c] if c in ("date", "amount", "currency") else _safe(r[c])
                   for c in COLUMNS])
    wb.save(str(path))
    return {"path": str(path), "rows": len(rows)}


def export_capital_gains_csv(year: int, out=None) -> dict:
    from capital_gains import realized_gains
    rows = realized_gains(year)
    path = _resolve_out(out, f"capital-gains-{year}-" + datetime.now().strftime("%Y%m%d") + ".csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(GAIN_COLUMNS)
        for r in rows:
            w.writerow([r.get(c, "") for c in GAIN_COLUMNS])
    return {"path": str(path), "rows": len(rows)}


def run_export(kind: str, year=None, account_id=None, out=None) -> dict:
    kind = kind.lower()
    if kind == "csv":
        return export_transactions_csv(account_id, year, out)
    if kind == "xlsx":
        return export_transactions_xlsx(account_id, year, out)
    if kind in ("capital-gains", "gains"):
        return export_capital_gains_csv(year or datetime.now().year, out)
    return {"error": "Unknown export type. Use: csv | xlsx | capital-gains"}
