"""Tests for skill._health_nudge — the load-time degraded-install pointer."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def test_health_nudge_empty_when_healthy():
    import skill
    assert skill._health_nudge() == ""


def test_health_nudge_points_to_doctor_when_locales_missing(monkeypatch):
    import skill, doctor
    monkeypatch.setattr(doctor, "_check_locales_submodule", lambda: {
        "name": "Locales submodule", "status": "fail",
        "message": "locales/ is empty (submodule not initialised).",
    })
    out = skill._health_nudge()
    assert "--doctor" in out
    assert "locales/" in out


def test_health_nudge_never_raises(monkeypatch):
    import skill, doctor
    def boom():
        raise RuntimeError("doctor exploded")
    monkeypatch.setattr(doctor, "_check_requirements", boom)
    assert skill._health_nudge() == ""  # swallowed, no crash
