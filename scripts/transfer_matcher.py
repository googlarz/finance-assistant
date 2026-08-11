"""
Transfer detection and linking — Tiers 2 & 3 of #8's design.

Tier 1 (category/structural signal at import time) lives in
transaction_normalizer.py. This module handles what Tier 1 can't:

  Tier 2 — link_tier2_transfers(): among transactions ALREADY typed
    "transfer" (by Tier 1), find each row's matching leg in a different
    account and record it via transfer_peer_id. Safe to auto-apply: both
    sides were already independently excluded from income/spending by
    Tier 1, so linking only adds a peer reference — it can't misclassify
    a transaction that wasn't already a transfer.

  Tier 3 — suggest_transfer_pairs(): among ordinary income/expense rows
    with no category signal, find amount/date-matched candidates that
    LOOK like an untyped transfer. Returned as suggestions only — never
    auto-committed. Validated against a real Monarch export (#8): the same
    heuristic without this gate false-matched ~19 legitimate pairs
    (refunds, recurring identical charges).

  retro_type_transfers() — apply the Tier 3 heuristic to already-imported
  data as a maintenance command. Preview by default; only mutates on an
  explicit dry_run=False.

Matching rule, all tiers: opposite sign, equal absolute amount, SAME
currency, DIFFERENT account, within a settlement window (±3 days; ±5 for
anything either leg's subcategory marks as a credit-card payment) — and
the match must be mutually unique. If a candidate has more than one
qualifying counterpart, or is itself claimed by more than one row's
search, it is skipped rather than force-matched to a "best" guess. A used
row is never reused (no A→B→C chains). Cross-currency transfers are not
matched (v1 limitation, documented in #8's discussion).

Candidate pools span year boundaries: a settlement window can straddle
Dec 31/Jan 1, so _all_transactions() also pulls Dec of the prior year and
Jan of the next year alongside the requested year.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

try:
    from account_manager import list_accounts
    from transaction_logger import get_transactions, update_transaction_fields
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from account_manager import list_accounts
    from transaction_logger import get_transactions, update_transaction_fields


DEFAULT_WINDOW_DAYS = 3
CC_PAYMENT_WINDOW_DAYS = 5


def _window_for(txn: dict) -> int:
    subcat = (txn.get("subcategory") or "").lower()
    return CC_PAYMENT_WINDOW_DAYS if "credit card payment" in subcat else DEFAULT_WINDOW_DAYS


def _parse_date(txn: dict) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(txn["date"])
    except (KeyError, ValueError, TypeError):
        return None


def _txn_year(txn: dict, fallback: int) -> int:
    """A txn's own calendar year — needed for JSON storage lookups since
    _all_transactions() can pull rows from an adjacent year (Dec/Jan
    boundary widening)."""
    d = _parse_date(txn)
    return d.year if d else fallback


def find_pairs(txns: list[dict]) -> list[tuple[dict, dict]]:
    """Core matcher shared by all tiers. See module docstring for the rule.

    Pure function — takes a candidate pool, returns pairs. Callers decide
    what pool to pass (already-transfer rows for Tier 2, ordinary flow rows
    for Tier 3/retro) and what to do with the result (link vs. suggest).
    """
    pool = [t for t in txns if t.get("id") and t.get("date") and t.get("account_id")]
    pool.sort(key=lambda t: (t.get("date", ""), t.get("id", "")))
    by_id = {t["id"]: t for t in pool}

    def candidates_for(a: dict, exclude: set) -> list[dict]:
        a_amt = round(float(a.get("amount", 0)), 2)
        a_date = _parse_date(a)
        if a_amt == 0 or a_date is None:
            return []
        win = _window_for(a)
        out = []
        for b in pool:
            if b["id"] == a["id"] or b["id"] in exclude:
                continue
            if b.get("account_id") == a.get("account_id"):
                continue
            if a.get("currency") != b.get("currency"):
                continue  # same-currency matching only (cross-currency: punt, per #8 discussion)
            b_amt = round(float(b.get("amount", 0)), 2)
            if b_amt != -a_amt:
                continue
            b_date = _parse_date(b)
            if b_date is None:
                continue
            if abs((b_date - a_date).days) > max(win, _window_for(b)):
                continue
            out.append(b)
        return out

    used: set = set()
    pairs: list[tuple[dict, dict]] = []

    for a in pool:
        if a["id"] in used:
            continue
        a_candidates = candidates_for(a, used)
        if len(a_candidates) != 1:
            continue  # zero or ambiguous — never force-match
        b = a_candidates[0]

        # Mutual uniqueness: b must see a as ITS only candidate too, or this
        # is an asymmetric match order-dependent on which side we walked
        # first — treat as ambiguous.
        b_candidates = candidates_for(b, used)
        if len(b_candidates) != 1 or b_candidates[0]["id"] != a["id"]:
            continue

        used.add(a["id"])
        used.add(b["id"])
        pairs.append((by_id[a["id"]], by_id[b["id"]]))

    return pairs


def _all_transactions(year: Optional[int] = None, type: Optional[str] = None) -> list[dict]:
    """Gather transactions across every account (transfer legs are, by
    definition, never in the same account) for a given year.

    Also pulls December of the prior year and January of the next year —
    the settlement window (up to CC_PAYMENT_WINDOW_DAYS) can straddle a
    year boundary (e.g. a Dec 31 transfer settling Jan 2), and get_transactions
    is year-scoped. find_pairs() itself still enforces the window, so this
    just widens the candidate pool without loosening the matching rule.
    """
    year = year or datetime.now().year
    txns = []
    for acc in list_accounts():
        txns.extend(get_transactions(account_id=acc["id"], year=year, type=type))
        txns.extend(get_transactions(account_id=acc["id"], year=year - 1, month=12, type=type))
        txns.extend(get_transactions(account_id=acc["id"], year=year + 1, month=1, type=type))
    return txns


def link_tier2_transfers(year: Optional[int] = None) -> dict:
    """Tier 2: link matching legs among rows already typed "transfer".
    Safe to auto-apply — see module docstring."""
    year = year or datetime.now().year
    transfer_txns = [t for t in _all_transactions(year, type="transfer") if not t.get("transfer_peer_id")]
    pairs = find_pairs(transfer_txns)

    from audit_log import log_mutation

    linked = []
    for a, b in pairs:
        ok_a = update_transaction_fields(a["account_id"], _txn_year(a, year), a["id"], {"transfer_peer_id": b["id"]})
        ok_b = update_transaction_fields(b["account_id"], _txn_year(b, year), b["id"], {"transfer_peer_id": a["id"]})
        if ok_a and ok_b:
            try:
                log_mutation(
                    action="update", target="transaction", target_id=a["id"],
                    before={"transfer_peer_id": None}, after={"transfer_peer_id": b["id"]},
                    source="link_tier2_transfers",
                    metadata={"paired_with": b["id"], "amount": a["amount"], "date": a["date"]},
                )
            except Exception:
                pass
            linked.append({
                "a": {"id": a["id"], "account_id": a["account_id"], "amount": a["amount"], "date": a["date"]},
                "b": {"id": b["id"], "account_id": b["account_id"], "amount": b["amount"], "date": b["date"]},
            })

    return {"year": year, "linked": linked, "pairs_found": len(pairs)}


def suggest_transfer_pairs(year: Optional[int] = None) -> list[dict]:
    """Tier 3: candidate transfer pairs among ordinary (non-transfer) rows.
    Read-only — never mutates. Returned for the caller to present to the
    user for confirmation."""
    year = year or datetime.now().year
    flow_txns = [
        t for t in _all_transactions(year)
        if t.get("type") not in ("transfer", "investment", "debt_payment")
    ]
    pairs = find_pairs(flow_txns)
    return [
        {
            "a": {"id": a["id"], "account_id": a["account_id"], "amount": a["amount"],
                  "date": a["date"], "description": a.get("description", "")},
            "b": {"id": b["id"], "account_id": b["account_id"], "amount": b["amount"],
                  "date": b["date"], "description": b.get("description", "")},
        }
        for a, b in pairs
    ]


def retro_type_transfers(year: Optional[int] = None, dry_run: bool = True) -> dict:
    """Store-wide maintenance command (#8): find and, only when explicitly
    requested, apply the Tier 3 heuristic to already-imported data.

    Legacy imports never captured the original bank category (Tier 1's
    signal), so this is necessarily the amount/date/account heuristic —
    the same one Tier 3 uses for new imports. Preview by default
    (dry_run=True): returns candidates, changes nothing. Set dry_run=False
    to apply — each applied pair is audit-logged and idempotent (a second
    run finds no more candidates once both legs are already
    transfer-typed and linked).
    """
    year = year or datetime.now().year
    candidates = suggest_transfer_pairs(year)

    if dry_run:
        return {
            "year": year,
            "dry_run": True,
            "candidates": candidates,
            "candidate_count": len(candidates),
            "note": "Preview only — nothing changed. Call with dry_run=False to apply.",
        }

    from audit_log import log_mutation

    applied = []
    for pair in candidates:
        a, b = pair["a"], pair["b"]
        ok_a = update_transaction_fields(a["account_id"], _txn_year(a, year), a["id"],
                                          {"type": "transfer", "transfer_peer_id": b["id"]})
        ok_b = update_transaction_fields(b["account_id"], _txn_year(b, year), b["id"],
                                          {"type": "transfer", "transfer_peer_id": a["id"]})
        if ok_a and ok_b:
            applied.append(pair)
            try:
                log_mutation(
                    action="update", target="transaction", target_id=a["id"],
                    before={"type": "expense/income"}, after={"type": "transfer", "transfer_peer_id": b["id"]},
                    source="retro_type_transfers",
                    metadata={"paired_with": b["id"], "amount": a["amount"], "date": a["date"]},
                )
            except Exception:
                pass

    return {
        "year": year,
        "dry_run": False,
        "applied": applied,
        "applied_count": len(applied),
    }
