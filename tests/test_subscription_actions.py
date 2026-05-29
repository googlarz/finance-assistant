"""Tests for subscription_actions."""
import pytest

from subscription_actions import (
    set_action, get_action, get_flagged, get_all_actions,
    still_charging_after_flag, format_actions,
)


def test_set_and_get_action(isolated_finance_dir):
    rec = set_action("Netflix", "flagged_to_cancel", monthly_cost=-14.99)
    assert rec["status"] == "flagged_to_cancel"
    assert rec["flagged_at"] is not None
    got = get_action("netflix")  # case-insensitive key
    assert got["merchant"] == "Netflix"


def test_invalid_status_rejected(isolated_finance_dir):
    with pytest.raises(ValueError):
        set_action("Netflix", "bogus_status")


def test_empty_merchant_rejected(isolated_finance_dir):
    with pytest.raises(ValueError):
        set_action("", "watching")


def test_cancelled_sets_timestamp(isolated_finance_dir):
    set_action("Spotify", "flagged_to_cancel", monthly_cost=-9.99)
    rec = set_action("Spotify", "cancelled")
    assert rec["status"] == "cancelled"
    assert rec["cancelled_at"] is not None
    assert rec["flagged_at"] is not None  # preserved from prior state


def test_get_flagged_returns_only_flagged(isolated_finance_dir):
    set_action("Netflix", "flagged_to_cancel")
    set_action("Spotify", "cancelled")
    set_action("Gym", "kept")
    flagged = get_flagged()
    assert len(flagged) == 1
    assert flagged[0]["merchant"] == "Netflix"


def test_still_charging_after_flag(isolated_finance_dir):
    set_action("Netflix", "flagged_to_cancel", monthly_cost=-14.99)
    # Detector still sees Netflix as active = zombie subscription
    detected = [
        {"merchant": "netflix", "monthly_cost": -14.99, "active": True},
        {"merchant": "spotify", "monthly_cost": -9.99, "active": True},  # not flagged
    ]
    zombies = still_charging_after_flag(detected)
    assert len(zombies) == 1
    assert zombies[0]["merchant"] == "netflix"
    assert zombies[0]["flagged_at"] is not None


def test_still_charging_ignores_inactive(isolated_finance_dir):
    set_action("Netflix", "flagged_to_cancel")
    detected = [{"merchant": "netflix", "monthly_cost": -14.99, "active": False}]
    assert still_charging_after_flag(detected) == []


def test_no_flagged_returns_empty(isolated_finance_dir):
    detected = [{"merchant": "netflix", "monthly_cost": -14.99, "active": True}]
    assert still_charging_after_flag(detected) == []


def test_format_actions_empty(isolated_finance_dir):
    assert "No subscription actions" in format_actions()


def test_format_actions_groups_by_status(isolated_finance_dir):
    set_action("Netflix", "flagged_to_cancel", monthly_cost=-14.99)
    set_action("Mint", "cancelled")
    out = format_actions()
    assert "Flagged to cancel" in out
    assert "Cancelled" in out
    assert "Netflix" in out
