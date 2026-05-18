"""
Price Sync — fetches live prices from Yahoo Finance and updates portfolio holdings.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

try:
    from investment_tracker import _load_portfolio, _save_portfolio
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from investment_tracker import _load_portfolio, _save_portfolio

# Asset types that have no ticker symbol — skip price fetch
_SKIP_TYPES = {"real_estate", "cash", "other"}

# Seconds before a cached price is considered stale (6 hours)
_TTL_SECONDS = 6 * 3600

_YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"


def fetch_price(symbol: str) -> tuple[float | None, str]:
    """Fetch the latest market price for *symbol* from Yahoo Finance.

    Returns (price, currency) on success, or (None, "") on failure.
    """
    url = _YAHOO_URL.format(symbol=symbol)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        meta = data["chart"]["result"][0]["meta"]
        price = float(meta["regularMarketPrice"])
        currency = str(meta.get("currency", ""))
        return price, currency
    except Exception:
        return None, ""


def sync_prices(force: bool = False) -> dict:
    """Sync live prices for all eligible holdings.

    Args:
        force: If True, bypass the 6-hour TTL and re-fetch all eligible holdings.

    Returns a dict with keys:
        updated  — list of symbol strings that were refreshed
        skipped  — list of symbol strings skipped (no ticker, wrong type, or within TTL)
        failed   — list of symbol strings where the fetch failed
        total_value_change — sum of current_value deltas across updated holdings
    """
    portfolio = _load_portfolio()
    now = datetime.now(tz=timezone.utc)

    updated: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    total_value_change = 0.0

    for holding in portfolio["holdings"]:
        symbol = holding.get("symbol", "").strip()
        asset_type = holding.get("type", "other")
        label = symbol or holding.get("name", holding.get("id", "?"))

        # Skip non-ticker types
        if asset_type in _SKIP_TYPES:
            skipped.append(label)
            continue

        # Skip holdings with no symbol
        if not symbol:
            skipped.append(label)
            continue

        # TTL check
        if not force:
            fetched_at_str = holding.get("price_fetched_at")
            if fetched_at_str:
                try:
                    fetched_at = datetime.fromisoformat(fetched_at_str)
                    # Make aware if naive
                    if fetched_at.tzinfo is None:
                        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
                    age = (now - fetched_at).total_seconds()
                    if age < _TTL_SECONDS:
                        skipped.append(symbol)
                        continue
                except ValueError:
                    pass  # Bad timestamp — treat as stale and re-fetch

        price, currency = fetch_price(symbol)

        if price is None:
            failed.append(symbol)
            continue

        old_value = float(holding.get("current_value", 0))
        units = float(holding.get("units", 0))
        new_value = units * price

        holding["current_value"] = new_value
        holding["price_source"] = "yahoo"
        holding["price_fetched_at"] = now.isoformat()
        if currency:
            holding["currency"] = currency

        total_value_change += new_value - old_value
        updated.append(symbol)

    _save_portfolio(portfolio)

    return {
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "total_value_change": round(total_value_change, 2),
    }


def get_stale_holding_count() -> tuple[int, float]:
    """Return (stale_count, max_age_hours) for eligible holdings with outdated prices.

    Read-only. Never fetches prices. Safe to call at session start.
    Returns (0, 0.0) if portfolio is empty, unreadable, or all prices are fresh.
    """
    try:
        portfolio = _load_portfolio()
    except Exception:
        return 0, 0.0

    now = datetime.now(tz=timezone.utc)
    stale_count = 0
    max_age_hours = 0.0

    for holding in portfolio.get("holdings", []):
        symbol = holding.get("symbol", "").strip()
        asset_type = holding.get("type", "other")

        if asset_type in _SKIP_TYPES or not symbol:
            continue

        fetched_at_str = holding.get("price_fetched_at")
        if not fetched_at_str:
            # Never synced — counts as stale
            stale_count += 1
            max_age_hours = max(max_age_hours, float("inf"))
            continue

        try:
            fetched_at = datetime.fromisoformat(fetched_at_str)
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            age_seconds = (now - fetched_at).total_seconds()
            if age_seconds >= _TTL_SECONDS:
                stale_count += 1
                max_age_hours = max(max_age_hours, age_seconds / 3600)
        except ValueError:
            stale_count += 1

    return stale_count, max_age_hours


def format_sync_result(result: dict) -> str:
    """Return a human-readable summary of a sync_prices() result."""
    lines = ["Price Sync Summary"]
    lines.append(f"  Updated : {len(result['updated'])} holding(s) — {', '.join(result['updated']) or '—'}")
    lines.append(f"  Skipped : {len(result['skipped'])} holding(s) — {', '.join(result['skipped']) or '—'}")
    lines.append(f"  Failed  : {len(result['failed'])} holding(s)" + (
        f" — {', '.join(result['failed'])}" if result["failed"] else ""
    ))
    change = result["total_value_change"]
    sign = "+" if change >= 0 else ""
    lines.append(f"  Value Δ : {sign}{change:,.2f}")
    return "\n".join(lines)
