"""
Alexa multi-Spotify account manager.

Lets each Alexa voice profile in a household be linked to a separate Spotify
account. Stored in .finance/integrations/alexa_spotify.json.

Usage:
    link_spotify_account("Alice", "alice@example.com")
    link_spotify_account("Bob",   "bob@example.com", financial_account_id="checking")
    list_spotify_links()
    get_spotify_link("Alice")
    unlink_spotify_account("Bob")
    display_spotify_links()
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Optional

try:
    from finance_storage import ensure_subdir, load_json, save_json
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import ensure_subdir, load_json, save_json


def _integrations_path():
    return ensure_subdir("integrations") / "alexa_spotify.json"


def _load() -> list[dict]:
    data = load_json(_integrations_path(), default={"links": []})
    return data.get("links", []) if isinstance(data, dict) else []


def _save(links: list[dict]) -> None:
    save_json(_integrations_path(), {
        "last_updated": datetime.now().isoformat(),
        "links": links,
    })


def _normalize_profile(name: str) -> str:
    """Case-insensitive, strip whitespace."""
    return name.strip().lower()


# ── Public API ────────────────────────────────────────────────────────────────

def link_spotify_account(
    alexa_profile: str,
    spotify_email: str,
    *,
    spotify_display_name: Optional[str] = None,
    financial_account_id: Optional[str] = None,
) -> dict:
    """Link a Spotify account to an Alexa voice profile.

    If the profile already has a link it is replaced (one active link per
    profile at a time).

    Args:
        alexa_profile: The Alexa household voice profile name (e.g. "Alice").
        spotify_email: The Spotify account email address.
        spotify_display_name: Optional friendly label (defaults to alexa_profile).
        financial_account_id: Optional finance-assistant account ID for
            subscription tracking against this Spotify account.

    Returns:
        The created or updated link dict.
    """
    if not alexa_profile or not alexa_profile.strip():
        raise ValueError("alexa_profile must not be empty")
    if not spotify_email or "@" not in spotify_email:
        raise ValueError(f"Invalid Spotify email: {spotify_email!r}")

    links = _load()
    key = _normalize_profile(alexa_profile)

    existing = next((l for l in links if _normalize_profile(l["alexa_profile"]) == key), None)
    if existing:
        existing["spotify_email"] = spotify_email
        existing["spotify_display_name"] = spotify_display_name or alexa_profile
        if financial_account_id is not None:
            existing["financial_account_id"] = financial_account_id
        existing["updated"] = datetime.now().date().isoformat()
        _save(links)
        return existing

    link = {
        "id": str(uuid.uuid4())[:8],
        "alexa_profile": alexa_profile.strip(),
        "spotify_email": spotify_email,
        "spotify_display_name": spotify_display_name or alexa_profile.strip(),
        "financial_account_id": financial_account_id,
        "added": datetime.now().date().isoformat(),
    }
    links.append(link)
    _save(links)
    return link


def unlink_spotify_account(alexa_profile: str) -> bool:
    """Remove the Spotify link for an Alexa voice profile.

    Returns True if a link was removed, False if none existed.
    """
    links = _load()
    key = _normalize_profile(alexa_profile)
    filtered = [l for l in links if _normalize_profile(l["alexa_profile"]) != key]
    if len(filtered) == len(links):
        return False
    _save(filtered)
    return True


def list_spotify_links() -> list[dict]:
    """Return all Alexa→Spotify links, sorted by profile name."""
    return sorted(_load(), key=lambda l: l["alexa_profile"].lower())


def get_spotify_link(alexa_profile: str) -> Optional[dict]:
    """Return the Spotify link for a specific Alexa voice profile, or None."""
    key = _normalize_profile(alexa_profile)
    return next(
        (l for l in _load() if _normalize_profile(l["alexa_profile"]) == key),
        None,
    )


def update_spotify_link(alexa_profile: str, updates: dict) -> Optional[dict]:
    """Update fields on an existing link. Returns the updated link or None."""
    links = _load()
    key = _normalize_profile(alexa_profile)
    for link in links:
        if _normalize_profile(link["alexa_profile"]) == key:
            # Don't allow overwriting immutable fields via updates
            for field in ("id", "alexa_profile", "added"):
                updates.pop(field, None)
            link.update(updates)
            link["updated"] = datetime.now().date().isoformat()
            _save(links)
            return link
    return None


def display_spotify_links() -> str:
    """Return a human-readable summary of all Alexa→Spotify links."""
    links = list_spotify_links()
    if not links:
        return (
            "No Spotify accounts linked to Alexa profiles yet.\n"
            "Use link_spotify_account(alexa_profile, spotify_email) to add one."
        )

    lines = [f"═══ Alexa → Spotify Links ({len(links)}) ═══\n"]
    for l in links:
        fin = f"  [tracks: {l['financial_account_id']}]" if l.get("financial_account_id") else ""
        lines.append(f"  {l['alexa_profile']:<20} → {l['spotify_email']}{fin}")
    lines.append("")
    lines.append(
        "Each Alexa voice profile uses its own Spotify account for music playback "
        "and subscription tracking."
    )
    return "\n".join(lines)
