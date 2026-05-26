"""
Recurring subscription detector.

Scans transaction history for likely subscriptions: same merchant + same
amount repeating at monthly (or near-monthly) cadence. Surfaces:
  - total monthly subscription burden
  - duplicate subscriptions (Netflix paid twice → flag for cancellation)
  - subscriptions that increased in price (price-creep detection)

Used by session alerts and the --subscriptions CLI flag.

Heuristics (deliberately conservative to avoid false positives):
  - Need ≥3 occurrences with the same normalized merchant + amount
  - Gaps between occurrences must be 25-35 days (monthly)
  - Amount tolerance: exact match (subscriptions don't usually drift cents)
  - Last occurrence must be within 60 days (still active)
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional


# Cadence windows in days
MONTHLY_MIN = 25
MONTHLY_MAX = 35
YEARLY_MIN = 350
YEARLY_MAX = 380

# An "active" subscription has a charge within this many days
ACTIVE_WINDOW_DAYS = 60

# Need at least this many occurrences to call something a subscription
MIN_OCCURRENCES = 3


_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def _normalize_merchant(name: str) -> str:
    """Strip transaction noise: trailing dates, refs, store numbers, punct."""
    if not name:
        return ""
    s = name.lower()
    # Strip common noise patterns
    s = re.sub(r"\b\d{2}[/.-]\d{2}([/.-]\d{2,4})?\b", "", s)  # dates
    s = re.sub(r"\bref:?\s*\w+", "", s)                       # ref numbers
    s = re.sub(r"\b\d{5,}\b", "", s)                          # long numeric IDs
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s[:40]  # cap length


def detect_subscriptions(
    transactions: list[dict],
    *,
    today: Optional[date] = None,
) -> list[dict]:
    """Detect recurring subscriptions from a transaction history.

    Args:
        transactions: list of txn dicts with date, amount, description/payee
        today: reference date for "still active" check (defaults to today)

    Returns:
        list of detected subscription dicts:
        {
            "merchant": str,
            "amount": float (negative for expenses),
            "cadence": "monthly" | "yearly",
            "occurrences": int,
            "first_seen": "YYYY-MM-DD",
            "last_seen": "YYYY-MM-DD",
            "monthly_cost": float,  # normalized to per-month
            "active": bool,
            "price_changed": bool,  # True if amount changed mid-history
        }
    """
    today = today or date.today()
    cutoff_active = today - timedelta(days=ACTIVE_WINDOW_DAYS)

    # Group by (normalized_merchant, abs(amount))
    groups: dict[tuple, list] = defaultdict(list)
    # Also group by merchant only (without amount) to catch price changes
    merchant_amounts: dict[str, set] = defaultdict(set)

    for t in transactions:
        amt = float(t.get("amount", 0))
        if amt >= 0:
            continue  # only expenses
        desc = t.get("description") or t.get("payee") or ""
        merchant = _normalize_merchant(desc)
        if not merchant:
            continue
        try:
            d = datetime.fromisoformat(t.get("date", ""))
        except (ValueError, TypeError):
            continue
        key = (merchant, round(abs(amt), 2))
        groups[key].append(d.date())
        merchant_amounts[merchant].add(round(abs(amt), 2))

    subscriptions: list[dict] = []
    seen_merchants: set = set()

    for (merchant, amount), dates in groups.items():
        if len(dates) < MIN_OCCURRENCES:
            continue
        dates_sorted = sorted(dates)
        gaps = [(dates_sorted[i + 1] - dates_sorted[i]).days for i in range(len(dates_sorted) - 1)]
        if not gaps:
            continue

        # Classify cadence: ≥75% of gaps must fit a single window
        monthly_count = sum(1 for g in gaps if MONTHLY_MIN <= g <= MONTHLY_MAX)
        yearly_count = sum(1 for g in gaps if YEARLY_MIN <= g <= YEARLY_MAX)

        if monthly_count / len(gaps) >= 0.75:
            cadence = "monthly"
            monthly_cost = amount
        elif yearly_count / len(gaps) >= 0.75 and len(dates_sorted) >= MIN_OCCURRENCES:
            cadence = "yearly"
            monthly_cost = round(amount / 12, 2)
        else:
            continue

        active = dates_sorted[-1] >= cutoff_active
        price_changed = len(merchant_amounts[merchant]) > 1

        subscriptions.append({
            "merchant": merchant,
            "amount": -amount,  # negative = outflow
            "cadence": cadence,
            "occurrences": len(dates_sorted),
            "first_seen": dates_sorted[0].isoformat(),
            "last_seen": dates_sorted[-1].isoformat(),
            "monthly_cost": monthly_cost,
            "active": active,
            "price_changed": price_changed,
        })
        seen_merchants.add(merchant)

    # Detect potential duplicates: same merchant, multiple different amounts,
    # both currently active
    duplicates: list[dict] = []
    for merchant in seen_merchants:
        same_merchant_subs = [s for s in subscriptions if s["merchant"] == merchant and s["active"]]
        if len(same_merchant_subs) >= 2:
            duplicates.append({
                "merchant": merchant,
                "active_subscriptions": same_merchant_subs,
                "potential_savings_monthly": sum(
                    s["monthly_cost"] for s in same_merchant_subs[1:]
                ),
            })

    # Sort: active monthly subs first, by cost descending
    subscriptions.sort(
        key=lambda s: (not s["active"], -s["monthly_cost"])
    )

    # Attach duplicate info to the result (callers may iterate either)
    for s in subscriptions:
        s["is_potential_duplicate"] = any(
            s["merchant"] == d["merchant"] for d in duplicates
        )

    return subscriptions


def summarize(subscriptions: list[dict]) -> dict:
    """Return high-level summary stats for session alerts and digest."""
    active = [s for s in subscriptions if s["active"]]
    total_monthly = sum(s["monthly_cost"] for s in active)
    duplicates = [s for s in active if s.get("is_potential_duplicate")]
    price_changes = [s for s in active if s.get("price_changed")]
    return {
        "active_count": len(active),
        "total_monthly": round(total_monthly, 2),
        "total_yearly": round(total_monthly * 12, 2),
        "duplicate_count": len(duplicates),
        "price_change_count": len(price_changes),
    }


def format_subscriptions(subscriptions: list[dict], currency: str = "EUR") -> str:
    """Format detected subscriptions for human display."""
    if not subscriptions:
        return "No recurring subscriptions detected. (Need ≥3 monthly charges from the same merchant.)"

    active = [s for s in subscriptions if s["active"]]
    inactive = [s for s in subscriptions if not s["active"]]
    summary = summarize(subscriptions)

    sym = {"EUR": "€", "USD": "$", "GBP": "£"}.get(currency, currency + " ")
    lines = [
        f"**Recurring subscriptions — {summary['active_count']} active**",
        f"Total monthly: {sym}{summary['total_monthly']:,.2f}  ·  "
        f"Yearly: {sym}{summary['total_yearly']:,.2f}",
        "",
    ]

    if summary["duplicate_count"]:
        lines.append(f"⚠  {summary['duplicate_count']} potential duplicate(s) — review for double-billing")
    if summary["price_change_count"]:
        lines.append(f"📈  {summary['price_change_count']} subscription(s) with changed prices")
    if summary["duplicate_count"] or summary["price_change_count"]:
        lines.append("")

    for s in active:
        flag = ""
        if s.get("is_potential_duplicate"):
            flag = " ⚠ DUPLICATE"
        elif s.get("price_changed"):
            flag = " 📈"
        cadence_label = "/mo" if s["cadence"] == "monthly" else "/yr"
        amt_display = s["amount"] if s["cadence"] == "monthly" else s["amount"]
        lines.append(
            f"  {sym}{amt_display:>7,.2f}{cadence_label}  "
            f"{s['merchant'][:30]:<30}  "
            f"({s['occurrences']} charges since {s['first_seen'][:7]}){flag}"
        )

    if inactive:
        lines.append("")
        lines.append(f"Inactive (no charge in {ACTIVE_WINDOW_DAYS} days):")
        for s in inactive[:5]:
            lines.append(
                f"  {sym}{s['amount']:>7,.2f}  {s['merchant'][:30]:<30}  "
                f"last: {s['last_seen']}"
            )

    return "\n".join(lines)


def get_for_account(account_id: str = "default", years_back: int = 2) -> list[dict]:
    """Convenience: load transactions for an account and detect subscriptions."""
    try:
        from transaction_logger import get_transactions
    except ImportError:
        import os, sys
        sys.path.insert(0, os.path.dirname(__file__))
        from transaction_logger import get_transactions

    today = date.today()
    txns: list[dict] = []
    for offset in range(years_back + 1):
        yr = today.year - offset
        txns.extend(get_transactions(account_id=account_id, year=yr))
    return detect_subscriptions(txns, today=today)
