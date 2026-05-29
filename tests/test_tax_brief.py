"""Tests for tax_brief."""
from tax_brief import build_brief, render_markdown, generate


def test_build_brief_returns_structure(isolated_finance_dir):
    profile = {
        "meta": {"locale": "de", "tax_year": 2025},
        "tax_profile": {"locale": "de", "filing_status": "single"},
        "employment": {"annual_gross": 60000},
        "income": 60000,
    }
    brief = build_brief(profile, 2025)
    assert brief["year"] == 2025
    assert brief["locale"] == "de"
    assert "estimate" in brief


def test_render_markdown_has_sections(isolated_finance_dir):
    profile = {
        "meta": {"locale": "de", "tax_year": 2025},
        "tax_profile": {"locale": "de"},
        "income": 60000,
    }
    brief = build_brief(profile, 2025)
    md = render_markdown(brief)
    assert "Tax Filing Brief" in md
    assert "Documents to gather" in md
    assert "estimate, not a filing" in md  # disclaimer present


def test_render_handles_error_locale(isolated_finance_dir):
    brief = {
        "error": "Locale 'zz' not available",
        "locale": "zz",
        "locale_name": "ZZ",
        "year": 2025,
    }
    md = render_markdown(brief)
    assert "error" in md.lower()
    assert "DE, FR, NL, PL, UK, US" in md  # tells user what IS available


def test_generate_writes_file(isolated_finance_dir):
    profile = {
        "meta": {"locale": "de", "tax_year": 2025},
        "tax_profile": {"locale": "de"},
        "income": 60000,
    }
    path = generate(profile, 2025)
    assert path.endswith("tax_brief_de_2025.md")
    from pathlib import Path
    assert Path(path).exists()
    content = Path(path).read_text()
    assert "Tax Filing Brief" in content
