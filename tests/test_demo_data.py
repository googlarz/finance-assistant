"""Tests for demo_data.py — seed and wipe."""
from account_manager import list_accounts, get_account
from goal_tracker import get_goals
from debt_optimizer import get_debts
from investment_tracker import get_portfolio
from profile_manager import get_profile
from transaction_logger import get_transactions
from demo_data import (
    seed_demo_data, wipe_demo_data,
    DEMO_ACCOUNT_IDS, DEMO_GOAL_IDS, DEMO_DEBT_IDS, DEMO_HOLDING_IDS,
)


def test_seed_demo_data(isolated_finance_dir):
    assert seed_demo_data() is True
    assert len(list_accounts()) == 3
    assert len(get_goals()) == 2
    assert len(get_debts()) == 1
    assert len(get_portfolio()["holdings"]) == 1
    assert seed_demo_data() is False  # idempotent


def test_wipe_demo_data_removes_everything(isolated_finance_dir):
    """Regression: --wipe-demo used to only call delete_account(), which
    when DB-present was a JSON-only no-op — accounts, transactions, goals,
    debts, the holding, and the "Alex" profile all survived a wipe that
    printed success."""
    seed_demo_data()
    result = wipe_demo_data()

    assert result["accounts"] == 3
    assert result["goals"] == 2
    assert result["debts"] == 1
    assert result["holdings"] == 1
    assert result["profile_reset"] is True

    for account_id in DEMO_ACCOUNT_IDS:
        assert get_account(account_id) is None
    assert list_accounts() == []
    assert get_goals() == []
    assert get_debts() == []
    assert get_portfolio()["holdings"] == []

    profile = get_profile()
    assert profile.get("personal", {}).get("name") != "Alex"
    assert not profile.get("meta", {}).get("created")


def test_wipe_demo_data_db_present_removes_accounts(isolated_finance_dir_db):
    """The SQLite-active case: delete_account() alone used to leave the
    account fully visible via list_accounts() (which prefers SQLite)."""
    seed_demo_data()
    wipe_demo_data()
    for account_id in DEMO_ACCOUNT_IDS:
        assert get_account(account_id) is None
    assert list_accounts() == []


def test_wipe_demo_data_removes_transactions(isolated_finance_dir):
    seed_demo_data()
    checking_id = DEMO_ACCOUNT_IDS[0]
    assert len(get_transactions(account_id=checking_id)) > 0

    wipe_demo_data()
    assert get_transactions(account_id=checking_id) == []


def test_wipe_demo_data_leaves_real_profile_untouched(isolated_finance_dir):
    """If the user has already replaced the demo profile with real info
    (name no longer "Alex"), wipe_demo_data() must not reset it — that
    would be data loss, not cleanup."""
    seed_demo_data()
    from profile_manager import update_profile
    update_profile({"personal": {"name": "Dawid"}, "meta": {"created": True}})

    result = wipe_demo_data()
    assert result["profile_reset"] is False
    assert get_profile()["personal"]["name"] == "Dawid"


def test_wipe_demo_data_without_seeding_is_a_safe_noop(isolated_finance_dir):
    result = wipe_demo_data()
    assert result["accounts"] == 0
    assert result["profile_reset"] is False
