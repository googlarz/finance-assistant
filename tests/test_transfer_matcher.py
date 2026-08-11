"""Tests for transfer_matcher.py (#8) — Tier 2/3 transfer detection and linking."""

from transaction_logger import add_transaction, get_transactions
from account_manager import add_account
from transfer_matcher import (
    find_pairs, link_tier2_transfers, suggest_transfer_pairs, retro_type_transfers,
)


def _setup_accounts():
    add_account({"id": "chk", "name": "Checking", "type": "checking"})
    add_account({"id": "sav", "name": "Savings", "type": "savings"})


# ── The negative test (write first, per design review) ──────────────────────

def test_refund_in_same_account_not_paired(isolated_finance_dir):
    """A refund and its original charge, both in the SAME account, must
    never be linked as a transfer — they aren't one. (Same-account rows are
    structurally excluded: a transfer's two legs are always in different
    accounts.)"""
    add_account({"id": "chk", "name": "Checking", "type": "checking"})
    add_transaction("2026-04-01", "expense", -50.0, "other_expense", "Store purchase", account_id="chk")
    add_transaction("2026-04-03", "income", 50.0, "refund", "Store refund", account_id="chk")

    txns = get_transactions(account_id="chk", year=2026)
    pairs = find_pairs(txns)
    assert pairs == []


def test_recurring_identical_charges_across_accounts_not_auto_linked(isolated_finance_dir):
    """Two DIFFERENT accounts each independently paying the same recurring
    amount (coincidence, not a transfer) must not corrupt live data — Tier 3
    only ever suggests, retro_type_transfers previews by default."""
    _setup_accounts()
    add_transaction("2026-04-05", "expense", -45.00, "subscriptions", "Gym membership", account_id="chk")
    add_transaction("2026-04-06", "expense", -45.00, "subscriptions", "Gym membership (spouse)", account_id="sav")

    # Even if this pair happens to be amount/date/account "unique" by the
    # matcher's rule, it must never mutate stored data without an explicit,
    # separate confirm step — retro_type_transfers defaults to preview.
    result = retro_type_transfers(year=2026)
    assert result["dry_run"] is True
    txns = get_transactions(account_id="chk", year=2026) + get_transactions(account_id="sav", year=2026)
    assert all(t["type"] != "transfer" for t in txns)


# ── Tier 2: linking already-transfer-typed rows ──────────────────────────────

def test_tier2_links_matching_transfer_legs(isolated_finance_dir):
    _setup_accounts()
    r1 = add_transaction("2026-04-01", "transfer", -500.0, "savings", "To savings", account_id="chk")
    r2 = add_transaction("2026-04-02", "transfer", 500.0, "savings", "From checking", account_id="sav")

    result = link_tier2_transfers(year=2026)
    assert result["pairs_found"] == 1
    assert len(result["linked"]) == 1

    chk_txn = get_transactions(account_id="chk", year=2026)[0]
    sav_txn = get_transactions(account_id="sav", year=2026)[0]
    assert chk_txn["transfer_peer_id"] == sav_txn["id"]
    assert sav_txn["transfer_peer_id"] == chk_txn["id"]


def test_tier2_does_not_link_same_account_transfers(isolated_finance_dir):
    """Two transfer-typed rows in the SAME account (e.g. two separate moves
    to different destinations) must not be linked to each other."""
    add_account({"id": "chk", "name": "Checking", "type": "checking"})
    add_transaction("2026-04-01", "transfer", -500.0, "savings", "Move A", account_id="chk")
    add_transaction("2026-04-01", "transfer", -500.0, "savings", "Move B", account_id="chk")

    result = link_tier2_transfers(year=2026)
    assert result["linked"] == []


def test_tier2_ambiguous_match_skipped(isolated_finance_dir):
    """Three candidate legs where two could plausibly match one — none
    should be force-matched."""
    add_account({"id": "chk", "name": "Checking", "type": "checking"})
    add_account({"id": "sav", "name": "Savings", "type": "savings"})
    add_account({"id": "biz", "name": "Business", "type": "checking"})

    add_transaction("2026-04-01", "transfer", -500.0, "savings", "Out", account_id="chk")
    add_transaction("2026-04-02", "transfer", 500.0, "savings", "In (candidate 1)", account_id="sav")
    add_transaction("2026-04-02", "transfer", 500.0, "savings", "In (candidate 2)", account_id="biz")

    result = link_tier2_transfers(year=2026)
    assert result["linked"] == []  # ambiguous — the -500 leg has 2 candidates


def test_tier2_ambiguous_cluster_does_not_block_unrelated_pair(isolated_finance_dir):
    """A used leg is never reused for a second pairing, and one ambiguous
    cluster (3+ overlapping candidates) doesn't prevent an unrelated,
    unambiguous pair elsewhere in the same run from linking."""
    add_account({"id": "chk", "name": "Checking", "type": "checking"})
    add_account({"id": "sav", "name": "Savings", "type": "savings"})
    add_account({"id": "biz", "name": "Business", "type": "checking"})

    # Ambiguous cluster: A's only same-day counterpart is contested by two
    # accounts (sav and biz) — must be skipped entirely, not force-matched.
    add_transaction("2026-04-01", "transfer", -500.0, "savings", "A", account_id="chk")
    add_transaction("2026-04-02", "transfer", 500.0, "savings", "B (candidate 1)", account_id="sav")
    add_transaction("2026-04-02", "transfer", 500.0, "savings", "B (candidate 2)", account_id="biz")

    # Unrelated, unambiguous pair — different amount, far enough away in
    # time that it shares no candidates with the ambiguous cluster above.
    add_transaction("2026-05-01", "transfer", -300.0, "savings", "C", account_id="chk")
    add_transaction("2026-05-02", "transfer", 300.0, "savings", "D", account_id="sav")

    result = link_tier2_transfers(year=2026)
    assert result["pairs_found"] == 1  # only C-D links; the ±500 cluster is skipped

    chk_txns = {t["description"]: t for t in get_transactions(account_id="chk", year=2026)}
    assert chk_txns["A"]["transfer_peer_id"] is None       # ambiguous — untouched
    assert chk_txns["C"]["transfer_peer_id"] is not None   # unambiguous — linked


def test_tier2_outside_window_not_linked(isolated_finance_dir):
    _setup_accounts()
    add_transaction("2026-04-01", "transfer", -500.0, "savings", "Out", account_id="chk")
    add_transaction("2026-04-10", "transfer", 500.0, "savings", "In, too late", account_id="sav")

    result = link_tier2_transfers(year=2026)
    assert result["linked"] == []


def test_tier2_credit_card_payment_gets_wider_window(isolated_finance_dir):
    """A subcategory of 'Credit Card Payment' (preserved by Tier 1 from the
    source category) gets a ±5d window instead of ±3d."""
    _setup_accounts()
    r1 = add_transaction("2026-04-01", "transfer", -500.0, "other_expense",
                          "CC payment", account_id="chk", subcategory="Credit Card Payment")
    r2 = add_transaction("2026-04-05", "transfer", 500.0, "other_expense",
                          "CC payment received", account_id="sav")

    result = link_tier2_transfers(year=2026)
    assert result["pairs_found"] == 1  # 4 days apart — within the 5d CC window


def test_tier2_idempotent(isolated_finance_dir):
    _setup_accounts()
    add_transaction("2026-04-01", "transfer", -500.0, "savings", "Out", account_id="chk")
    add_transaction("2026-04-02", "transfer", 500.0, "savings", "In", account_id="sav")

    r1 = link_tier2_transfers(year=2026)
    r2 = link_tier2_transfers(year=2026)
    assert len(r1["linked"]) == 1
    assert len(r2["linked"]) == 0  # already-linked rows excluded from the pool


# ── Tier 3: suggestions only, never auto-committed ───────────────────────────

def test_suggest_transfer_pairs_never_mutates(isolated_finance_dir):
    _setup_accounts()
    add_transaction("2026-04-01", "expense", -300.0, "other_expense", "Move to savings", account_id="chk")
    add_transaction("2026-04-02", "income", 300.0, "other_income", "From checking", account_id="sav")

    suggestions = suggest_transfer_pairs(year=2026)
    assert len(suggestions) == 1

    txns = get_transactions(account_id="chk", year=2026) + get_transactions(account_id="sav", year=2026)
    assert all(t["type"] != "transfer" for t in txns)  # suggestion only, nothing changed


# ── retro_type_transfers: preview vs apply, idempotency ──────────────────────

def test_retro_type_transfers_preview_does_not_mutate(isolated_finance_dir):
    _setup_accounts()
    add_transaction("2026-04-01", "expense", -300.0, "other_expense", "Move to savings", account_id="chk")
    add_transaction("2026-04-02", "income", 300.0, "other_income", "From checking", account_id="sav")

    result = retro_type_transfers(year=2026, dry_run=True)
    assert result["candidate_count"] == 1
    txns = get_transactions(account_id="chk", year=2026) + get_transactions(account_id="sav", year=2026)
    assert all(t["type"] != "transfer" for t in txns)


def test_retro_type_transfers_apply_links_and_retypes(isolated_finance_dir):
    _setup_accounts()
    add_transaction("2026-04-01", "expense", -300.0, "other_expense", "Move to savings", account_id="chk")
    add_transaction("2026-04-02", "income", 300.0, "other_income", "From checking", account_id="sav")

    result = retro_type_transfers(year=2026, dry_run=False)
    assert result["applied_count"] == 1

    chk_txn = get_transactions(account_id="chk", year=2026)[0]
    sav_txn = get_transactions(account_id="sav", year=2026)[0]
    assert chk_txn["type"] == "transfer"
    assert sav_txn["type"] == "transfer"
    assert chk_txn["transfer_peer_id"] == sav_txn["id"]


def test_retro_type_transfers_apply_is_idempotent(isolated_finance_dir):
    _setup_accounts()
    add_transaction("2026-04-01", "expense", -300.0, "other_expense", "Move to savings", account_id="chk")
    add_transaction("2026-04-02", "income", 300.0, "other_income", "From checking", account_id="sav")

    r1 = retro_type_transfers(year=2026, dry_run=False)
    r2 = retro_type_transfers(year=2026, dry_run=False)
    assert r1["applied_count"] == 1
    assert r2["applied_count"] == 0  # already-transfer rows excluded from the candidate pool


# ── find_pairs core matcher ──────────────────────────────────────────────────

def test_find_pairs_empty_input():
    assert find_pairs([]) == []


def test_find_pairs_ignores_zero_amount():
    txns = [
        {"id": "a", "date": "2026-04-01", "account_id": "chk", "amount": 0.0},
        {"id": "b", "date": "2026-04-01", "account_id": "sav", "amount": 0.0},
    ]
    assert find_pairs(txns) == []


def test_find_pairs_rejects_cross_currency_match():
    """Same amount/date/account shape but different currencies must not be
    treated as a transfer pair (v1: same-currency matching only)."""
    txns = [
        {"id": "a", "date": "2026-04-01", "account_id": "chk", "amount": -500.0, "currency": "EUR"},
        {"id": "b", "date": "2026-04-02", "account_id": "sav", "amount": 500.0, "currency": "USD"},
    ]
    assert find_pairs(txns) == []


# ── Year-boundary pairing ─────────────────────────────────────────────────────

def test_tier2_links_pair_spanning_year_boundary(isolated_finance_dir):
    """A transfer settling a couple days into the new year must still link —
    the candidate pool widens to Dec/Jan of adjacent years."""
    _setup_accounts()
    add_transaction("2025-12-31", "transfer", -500.0, "savings", "Year-end move", account_id="chk")
    add_transaction("2026-01-02", "transfer", 500.0, "savings", "Year-end move landed", account_id="sav")

    result = link_tier2_transfers(year=2025)
    assert result["pairs_found"] == 1

    # Each leg must be persisted in ITS OWN year's storage, not the requested year's.
    chk_txn = get_transactions(account_id="chk", year=2025, type="transfer")[0]
    sav_txn = get_transactions(account_id="sav", year=2026, type="transfer")[0]
    assert chk_txn["transfer_peer_id"] == sav_txn["id"]
    assert sav_txn["transfer_peer_id"] == chk_txn["id"]

    # Idempotent: rerunning either year finds nothing new.
    assert link_tier2_transfers(year=2025)["pairs_found"] == 0
    assert link_tier2_transfers(year=2026)["pairs_found"] == 0
