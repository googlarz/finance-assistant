"""Tests for doctor.py."""
from doctor import _check_tesseract, run_checks


def test_check_tesseract_reports_ok_when_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/tesseract")
    result = _check_tesseract()
    assert result["status"] == "ok"


def test_check_tesseract_warns_when_missing(monkeypatch):
    """Regression: --doctor used to have no tesseract check at all, so it
    reported all-clear on a machine where 'scan [receipt]' would throw
    TesseractNotFoundError."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = _check_tesseract()
    assert result["status"] == "warn"
    assert "tesseract" in result["message"].lower()


def test_run_checks_includes_tesseract():
    names = [c["name"] for c in run_checks()]
    assert any("tesseract" in n.lower() for n in names)
