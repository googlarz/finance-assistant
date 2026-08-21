"""Tests for currency.py."""
import json
from decimal import Decimal
from currency import Money, format_money, convert, get_exchange_rate, normalize_to_primary, sync_exchange_rates


def test_money_creation():
    m = Money(100, "EUR")
    assert m.amount == Decimal("100")
    assert m.currency == "EUR"


def test_money_add():
    result = Money(100, "EUR") + Money(50, "EUR")
    assert float(result) == 150.0


def test_money_sub():
    result = Money(100, "EUR") - Money(30, "EUR")
    assert float(result) == 70.0


def test_money_mul():
    result = Money(100, "EUR") * 1.5
    assert float(result) == 150.0


def test_money_neg():
    result = -Money(100, "EUR")
    assert float(result) == -100.0


def test_money_format():
    assert format_money(1234.56, "EUR") == "€1,234.56"
    assert format_money(1234.56, "EUR", "de") == "€1.234,56"
    assert format_money(1000, "JPY") == "¥1,000"


def test_money_format_method():
    m = Money(1234.56, "EUR")
    assert "1,234.56" in m.format()


def test_same_currency_rate():
    rate, confidence = get_exchange_rate("EUR", "EUR")
    assert rate == 1.0
    assert confidence == "exact"


def test_fallback_rate():
    rate, confidence = get_exchange_rate("EUR", "USD")
    assert rate > 0
    assert confidence == "fallback"


def test_convert():
    amount, confidence = convert(100, "EUR", "EUR")
    assert amount == 100.0
    assert confidence == "exact"


def test_normalize_to_primary():
    amount, conf = normalize_to_primary(100, "EUR", "EUR")
    assert amount == 100.0


# ── sync_exchange_rates(): the previously-dead-code rate cache ──────────────

class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_sync_exchange_rates_populates_cache_used_by_get_exchange_rate(isolated_finance_dir, monkeypatch):
    """Regression: _save_cached_rates() had zero callers anywhere — every
    conversion fell through to the hardcoded ~2024 fallback table regardless
    of the claimed 24h-TTL cache. sync_exchange_rates() is the fetcher that
    was missing."""
    import urllib.request

    def fake_urlopen(req, timeout=10):
        return _FakeResponse({"date": "2026-08-21", "base": "EUR", "rates": {"USD": 1.10, "GBP": 0.85}})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = sync_exchange_rates()
    assert result["status"] == "ok"
    assert result["currencies"] == 3  # USD, GBP + EUR itself

    rate, confidence = get_exchange_rate("EUR", "USD")
    assert confidence == "cached"  # not "fallback" — the cache is now populated
    assert rate == 1.10


def test_sync_exchange_rates_reports_failure_without_crashing(isolated_finance_dir, monkeypatch):
    import urllib.request

    def fake_urlopen(req, timeout=10):
        raise OSError("network unreachable")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = sync_exchange_rates()
    assert result["status"] == "failed"
    # get_exchange_rate() must still work — falls back cleanly
    rate, confidence = get_exchange_rate("EUR", "USD")
    assert confidence == "fallback"
