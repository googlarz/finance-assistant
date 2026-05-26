"""Tests for subscription_detector."""
from datetime import date, timedelta

from subscription_detector import (
    _normalize_merchant,
    detect_subscriptions,
    summarize,
    format_subscriptions,
)


def _txn(date_str, amount, desc):
    return {"date": date_str, "amount": amount, "description": desc}


def test_normalize_merchant_strips_noise():
    assert _normalize_merchant("NETFLIX.COM  REF:12345") == "netflix com"
    assert _normalize_merchant("Spotify 04/15/2025") == "spotify"
    assert _normalize_merchant("AMAZON #98765432") == "amazon"


def test_detect_three_monthly_charges():
    today = date(2026, 5, 1)
    txns = [
        _txn("2026-02-05", -14.99, "NETFLIX.COM"),
        _txn("2026-03-05", -14.99, "NETFLIX.COM"),
        _txn("2026-04-05", -14.99, "NETFLIX.COM"),
    ]
    subs = detect_subscriptions(txns, today=today)
    assert len(subs) == 1
    s = subs[0]
    assert s["cadence"] == "monthly"
    assert s["occurrences"] == 3
    assert s["monthly_cost"] == 14.99
    assert s["active"] is True


def test_skips_below_minimum_occurrences():
    today = date(2026, 5, 1)
    txns = [
        _txn("2026-03-05", -14.99, "NETFLIX"),
        _txn("2026-04-05", -14.99, "NETFLIX"),
    ]
    assert detect_subscriptions(txns, today=today) == []


def test_skips_irregular_cadence():
    today = date(2026, 5, 1)
    txns = [
        _txn("2026-01-05", -50.00, "RANDOM SHOP"),
        _txn("2026-01-15", -50.00, "RANDOM SHOP"),
        _txn("2026-04-20", -50.00, "RANDOM SHOP"),  # gap is too long
    ]
    assert detect_subscriptions(txns, today=today) == []


def test_detects_yearly_cadence():
    today = date(2026, 5, 1)
    txns = [
        _txn("2024-04-15", -99.00, "DOMAIN REGISTRAR"),
        _txn("2025-04-15", -99.00, "DOMAIN REGISTRAR"),
        _txn("2026-04-15", -99.00, "DOMAIN REGISTRAR"),
    ]
    subs = detect_subscriptions(txns, today=today)
    assert len(subs) == 1
    assert subs[0]["cadence"] == "yearly"
    assert subs[0]["monthly_cost"] == 8.25  # 99/12


def test_flags_inactive_subscription():
    today = date(2026, 5, 1)
    # Last charge > 60 days ago → inactive
    txns = [
        _txn("2025-10-05", -9.99, "OLD SERVICE"),
        _txn("2025-11-05", -9.99, "OLD SERVICE"),
        _txn("2025-12-05", -9.99, "OLD SERVICE"),
    ]
    subs = detect_subscriptions(txns, today=today)
    assert len(subs) == 1
    assert subs[0]["active"] is False


def test_flags_duplicate_subscriptions():
    today = date(2026, 5, 1)
    # Netflix charged at TWO different price points monthly = double-billed
    txns = []
    for m in range(2, 5):
        txns.append(_txn(f"2026-{m:02d}-05", -14.99, "NETFLIX"))
        txns.append(_txn(f"2026-{m:02d}-12", -19.99, "NETFLIX"))
    subs = detect_subscriptions(txns, today=today)
    assert len(subs) == 2
    assert all(s["is_potential_duplicate"] for s in subs)
    assert all(s["price_changed"] for s in subs)


def test_summarize_returns_totals():
    today = date(2026, 5, 1)
    txns = []
    for m in range(2, 5):
        txns.append(_txn(f"2026-{m:02d}-05", -14.99, "NETFLIX"))
        txns.append(_txn(f"2026-{m:02d}-08", -9.99, "SPOTIFY"))
    subs = detect_subscriptions(txns, today=today)
    s = summarize(subs)
    assert s["active_count"] == 2
    assert s["total_monthly"] == 24.98
    assert s["total_yearly"] == 299.76


def test_format_empty():
    out = format_subscriptions([])
    assert "No recurring subscriptions" in out


def test_format_handles_subscriptions():
    today = date(2026, 5, 1)
    txns = [_txn(f"2026-{m:02d}-05", -14.99, "NETFLIX") for m in range(2, 5)]
    subs = detect_subscriptions(txns, today=today)
    out = format_subscriptions(subs)
    assert "netflix" in out
    assert "14.99" in out
