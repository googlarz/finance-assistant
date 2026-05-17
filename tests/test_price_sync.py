"""Tests for price_sync.py."""

import io
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

scripts_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from price_sync import fetch_price, sync_prices, format_sync_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_yahoo_response(price: float, currency: str = "USD") -> MagicMock:
    """Build a mock urllib response object returning a minimal Yahoo Finance payload."""
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": price,
                        "currency": currency,
                    }
                }
            ]
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _make_portfolio(holdings: list) -> dict:
    return {"holdings": holdings, "target_allocation": {}}


# ---------------------------------------------------------------------------
# 1. fetch_price returns correct price from a mocked response
# ---------------------------------------------------------------------------

def test_fetch_price_returns_price_and_currency(isolated_finance_dir):
    mock_resp = _make_yahoo_response(price=182.45, currency="USD")
    with patch("urllib.request.urlopen", return_value=mock_resp):
        price, currency = fetch_price("AAPL")

    assert price == 182.45
    assert currency == "USD"


# ---------------------------------------------------------------------------
# 2. sync_prices updates current_value for a holding with a symbol
# ---------------------------------------------------------------------------

def test_sync_prices_updates_holding_with_symbol(isolated_finance_dir):
    holding = {
        "id": "h1",
        "symbol": "VWCE",
        "name": "Vanguard All-World",
        "type": "etf",
        "units": 10.0,
        "cost_basis": 800.0,
        "current_value": 900.0,
        "currency": "EUR",
    }
    portfolio = _make_portfolio([holding])

    mock_resp = _make_yahoo_response(price=100.0, currency="EUR")
    with patch("price_sync._load_portfolio", return_value=portfolio), \
         patch("price_sync._save_portfolio") as mock_save, \
         patch("urllib.request.urlopen", return_value=mock_resp):
        result = sync_prices()

    assert "VWCE" in result["updated"]
    assert "VWCE" not in result["skipped"]
    assert "VWCE" not in result["failed"]

    saved_portfolio = mock_save.call_args[0][0]
    updated_holding = saved_portfolio["holdings"][0]
    assert updated_holding["current_value"] == 1000.0  # 10 units * 100.0
    assert updated_holding["price_source"] == "yahoo"
    assert "price_fetched_at" in updated_holding
    # value delta: 1000 - 900 = 100
    assert result["total_value_change"] == 100.0


# ---------------------------------------------------------------------------
# 3. sync_prices skips a cash holding
# ---------------------------------------------------------------------------

def test_sync_prices_skips_cash_holding(isolated_finance_dir):
    cash_holding = {
        "id": "h2",
        "symbol": "",
        "name": "Savings Account",
        "type": "cash",
        "units": 1.0,
        "cost_basis": 5000.0,
        "current_value": 5000.0,
        "currency": "EUR",
    }
    portfolio = _make_portfolio([cash_holding])

    with patch("price_sync._load_portfolio", return_value=portfolio), \
         patch("price_sync._save_portfolio"), \
         patch("urllib.request.urlopen") as mock_urlopen:
        result = sync_prices()

    mock_urlopen.assert_not_called()
    assert result["updated"] == []
    assert result["failed"] == []
    assert len(result["skipped"]) == 1


# ---------------------------------------------------------------------------
# 4. sync_prices respects TTL — skips re-fetch within 6 hours
# ---------------------------------------------------------------------------

def test_sync_prices_respects_ttl(isolated_finance_dir):
    recent_fetch = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
    holding = {
        "id": "h3",
        "symbol": "IWDA",
        "name": "iShares Core MSCI World",
        "type": "etf",
        "units": 5.0,
        "cost_basis": 400.0,
        "current_value": 450.0,
        "currency": "EUR",
        "price_fetched_at": recent_fetch,
    }
    portfolio = _make_portfolio([holding])

    with patch("price_sync._load_portfolio", return_value=portfolio), \
         patch("price_sync._save_portfolio"), \
         patch("urllib.request.urlopen") as mock_urlopen:
        result = sync_prices(force=False)

    mock_urlopen.assert_not_called()
    assert "IWDA" in result["skipped"]
    assert result["updated"] == []


def test_sync_prices_force_bypasses_ttl(isolated_finance_dir):
    recent_fetch = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
    holding = {
        "id": "h4",
        "symbol": "IWDA",
        "name": "iShares Core MSCI World",
        "type": "etf",
        "units": 5.0,
        "cost_basis": 400.0,
        "current_value": 450.0,
        "currency": "EUR",
        "price_fetched_at": recent_fetch,
    }
    portfolio = _make_portfolio([holding])

    mock_resp = _make_yahoo_response(price=95.0, currency="EUR")
    with patch("price_sync._load_portfolio", return_value=portfolio), \
         patch("price_sync._save_portfolio"), \
         patch("urllib.request.urlopen", return_value=mock_resp):
        result = sync_prices(force=True)

    assert "IWDA" in result["updated"]
    assert result["skipped"] == []


# ---------------------------------------------------------------------------
# format_sync_result
# ---------------------------------------------------------------------------

def test_format_sync_result_contains_summary():
    result = {
        "updated": ["VWCE", "AAPL"],
        "skipped": ["Savings Account"],
        "failed": [],
        "total_value_change": 123.45,
    }
    summary = format_sync_result(result)
    assert "VWCE" in summary
    assert "AAPL" in summary
    assert "123.45" in summary
    assert "Price Sync Summary" in summary
