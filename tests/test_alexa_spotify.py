"""Tests for scripts/alexa_spotify.py — multi-Spotify account Alexa linking."""

import os
import tempfile
import pytest


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path):
    os.environ["FINANCE_PROJECT_DIR"] = str(tmp_path)
    yield
    del os.environ["FINANCE_PROJECT_DIR"]


def _mod():
    import importlib, sys
    # Force fresh import so storage paths use the patched env var
    for key in list(sys.modules):
        if "alexa_spotify" in key or "finance_storage" in key:
            del sys.modules[key]
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import alexa_spotify
    return alexa_spotify


class TestLink:
    def test_link_and_retrieve(self):
        m = _mod()
        link = m.link_spotify_account("Alice", "alice@example.com")
        assert link["alexa_profile"] == "Alice"
        assert link["spotify_email"] == "alice@example.com"
        assert link["spotify_display_name"] == "Alice"
        assert link["financial_account_id"] is None
        assert "id" in link
        assert "added" in link

    def test_link_with_display_name_and_account(self):
        m = _mod()
        link = m.link_spotify_account(
            "Bob", "bob@example.com",
            spotify_display_name="Bob's Tunes",
            financial_account_id="checking",
        )
        assert link["spotify_display_name"] == "Bob's Tunes"
        assert link["financial_account_id"] == "checking"

    def test_duplicate_profile_replaces_existing(self):
        m = _mod()
        m.link_spotify_account("Alice", "alice-old@example.com")
        m.link_spotify_account("Alice", "alice-new@example.com")
        links = m.list_spotify_links()
        assert len(links) == 1
        assert links[0]["spotify_email"] == "alice-new@example.com"

    def test_case_insensitive_profile_matching(self):
        m = _mod()
        m.link_spotify_account("Alice", "alice@example.com")
        m.link_spotify_account("alice", "alice2@example.com")
        assert len(m.list_spotify_links()) == 1

    def test_invalid_email_raises(self):
        m = _mod()
        with pytest.raises(ValueError):
            m.link_spotify_account("Alice", "not-an-email")

    def test_empty_profile_raises(self):
        m = _mod()
        with pytest.raises(ValueError):
            m.link_spotify_account("", "alice@example.com")
        with pytest.raises(ValueError):
            m.link_spotify_account("   ", "alice@example.com")


class TestUnlink:
    def test_unlink_existing(self):
        m = _mod()
        m.link_spotify_account("Alice", "alice@example.com")
        assert m.unlink_spotify_account("Alice") is True
        assert m.list_spotify_links() == []

    def test_unlink_nonexistent_returns_false(self):
        m = _mod()
        assert m.unlink_spotify_account("Ghost") is False

    def test_unlink_case_insensitive(self):
        m = _mod()
        m.link_spotify_account("Alice", "alice@example.com")
        assert m.unlink_spotify_account("ALICE") is True
        assert m.list_spotify_links() == []


class TestListAndGet:
    def test_list_empty(self):
        m = _mod()
        assert m.list_spotify_links() == []

    def test_list_sorted_by_profile(self):
        m = _mod()
        m.link_spotify_account("Zara", "z@example.com")
        m.link_spotify_account("Alice", "a@example.com")
        m.link_spotify_account("Bob", "b@example.com")
        names = [l["alexa_profile"] for l in m.list_spotify_links()]
        assert names == ["Alice", "Bob", "Zara"]

    def test_get_existing(self):
        m = _mod()
        m.link_spotify_account("Alice", "alice@example.com")
        link = m.get_spotify_link("Alice")
        assert link is not None
        assert link["spotify_email"] == "alice@example.com"

    def test_get_missing_returns_none(self):
        m = _mod()
        assert m.get_spotify_link("Ghost") is None

    def test_get_case_insensitive(self):
        m = _mod()
        m.link_spotify_account("Alice", "alice@example.com")
        assert m.get_spotify_link("alice") is not None
        assert m.get_spotify_link("ALICE") is not None


class TestUpdate:
    def test_update_email(self):
        m = _mod()
        m.link_spotify_account("Alice", "alice@example.com")
        updated = m.update_spotify_link("Alice", {"spotify_email": "new@example.com"})
        assert updated["spotify_email"] == "new@example.com"
        assert m.get_spotify_link("Alice")["spotify_email"] == "new@example.com"

    def test_update_ignores_immutable_fields(self):
        m = _mod()
        m.link_spotify_account("Alice", "alice@example.com")
        original = m.get_spotify_link("Alice")
        m.update_spotify_link("Alice", {"id": "hacked", "alexa_profile": "Evil", "added": "2000-01-01"})
        link = m.get_spotify_link("Alice")
        assert link["id"] == original["id"]
        assert link["alexa_profile"] == "Alice"
        assert link["added"] == original["added"]

    def test_update_nonexistent_returns_none(self):
        m = _mod()
        assert m.update_spotify_link("Ghost", {"spotify_email": "x@x.com"}) is None


class TestDisplay:
    def test_display_empty(self):
        m = _mod()
        text = m.display_spotify_links()
        assert "No Spotify" in text

    def test_display_with_links(self):
        m = _mod()
        m.link_spotify_account("Alice", "alice@example.com", financial_account_id="checking")
        m.link_spotify_account("Bob", "bob@example.com")
        text = m.display_spotify_links()
        assert "Alice" in text
        assert "alice@example.com" in text
        assert "checking" in text
        assert "Bob" in text
        assert "2" in text  # link count
