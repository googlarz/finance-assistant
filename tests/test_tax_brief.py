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


def test_computed_estimate_table_is_populated_de(isolated_finance_dir):
    """Regression: the estimate table was empty because render looked for keys
    (gross/tax/net) that no locale returns — DE nests them under `breakdown`."""
    profile = {
        "meta": {"locale": "de", "tax_year": 2025},
        "tax_profile": {"locale": "de"},
        "employment": {"type": "employed", "annual_gross": 58000},
    }
    md = render_markdown(build_brief(profile, 2025))
    assert "Gross income" in md
    assert "Income tax" in md
    assert "no figures on record" not in md  # table must NOT be the empty fallback


def test_computed_estimate_table_is_populated_us(isolated_finance_dir):
    """US returns flat keys (federal_income_tax, gross_income, social_security_tax)
    — the normalizer must pick those up too, plus effective rate as a %."""
    profile = {
        "meta": {"locale": "us", "tax_year": 2024},
        "tax_profile": {"locale": "us", "filing_status": "single"},
        "employment": {"type": "employed", "annual_gross": 80000},
    }
    md = render_markdown(build_brief(profile, 2024))
    assert "Gross income" in md
    assert "Income tax" in md
    assert "Social contributions" in md
    assert "11.8%" in md  # effective_rate (0.118 fraction) rendered as percent
    assert "no figures on record" not in md


def test_us_freelancer_brief_shows_se_tax_and_qbi(isolated_finance_dir):
    profile = {
        "meta": {"locale": "us", "tax_year": 2024},
        "tax_profile": {"locale": "us", "filing_status": "single"},
        "employment": {"type": "self_employed", "annual_gross": 80000},
    }
    md = render_markdown(build_brief(profile, 2024))
    assert "Self-employment tax" in md
    assert "QBI" in md


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
