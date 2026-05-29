"""Tests for the LLM-native import fallback."""
import os
import tempfile

from llm_import import (
    prepare_extraction_request, ingest_extracted, EXTRACTION_SCHEMA, _read_raw_text,
)


def _write(content, suffix=".xyz"):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return f.name


# ── prepare_extraction_request ───────────────────────────────────────────────

def test_prepare_request_reads_text(isolated_finance_dir):
    path = _write("some weird bank format\n01.01.2026 -42.50 Coffee\n")
    try:
        req = prepare_extraction_request(path, "checking", "EUR")
        assert req["needs_llm_extraction"] is True
        assert req["source"] == "text"
        assert "Coffee" in req["raw_text"]
        assert "date" in req["schema"]
        assert req["account_id"] == "checking"
    finally:
        os.unlink(path)


def test_prepare_request_flags_image(isolated_finance_dir):
    path = _write("not really an image", suffix=".png")
    try:
        req = prepare_extraction_request(path, "checking")
        assert req["source"] == "image"
        assert req["raw_text"] == ""
    finally:
        os.unlink(path)


# ── ingest_extracted ─────────────────────────────────────────────────────────

def test_ingest_dry_run_previews_without_committing(isolated_finance_dir):
    rows = [
        {"date": "2026-01-05", "amount": -42.50, "description": "Coffee Shop"},
        {"date": "2026-01-06", "amount": 2500.00, "description": "Salary"},
    ]
    result = ingest_extracted(rows, "checking", "EUR", dry_run=True)
    assert result["to_import"] == 2
    assert result["dry_run"] is True
    assert "imported" not in result
    # Nothing actually written
    from transaction_logger import get_transactions
    assert get_transactions(account_id="checking", year=2026) == []


def test_ingest_commit_writes_transactions(isolated_finance_dir):
    rows = [{"date": "2026-02-01", "amount": -19.99, "description": "Netflix"}]
    result = ingest_extracted(rows, "checking", "EUR", dry_run=False)
    assert result["imported"] == 1
    from transaction_logger import get_transactions
    txns = get_transactions(account_id="checking", year=2026)
    assert len(txns) == 1
    assert txns[0]["description"] == "Netflix"


def test_ingest_sanitizes_csv_injection(isolated_finance_dir):
    rows = [{"date": "2026-03-01", "amount": -10.0, "description": "=SUM(A1:A9)"}]
    result = ingest_extracted(rows, "checking", "EUR", dry_run=True)
    # Leading '=' must be neutralized
    assert not result["preview"][0]["description"].startswith("=")


def test_ingest_skips_rows_without_date_or_amount(isolated_finance_dir):
    rows = [
        {"amount": -10.0, "description": "no date"},
        {"date": "2026-01-01", "description": "no amount"},
        {"date": "2026-01-02", "amount": "not a number"},
        {"date": "2026-01-03", "amount": -5.0, "description": "valid"},
    ]
    result = ingest_extracted(rows, "checking", dry_run=True)
    assert result["to_import"] == 1


def test_ingest_empty_returns_error(isolated_finance_dir):
    assert ingest_extracted([], "checking")["to_import"] == 0
    assert "error" in ingest_extracted([], "checking")


def test_ingest_deduplicates_against_existing(isolated_finance_dir):
    from transaction_logger import add_transaction
    add_transaction(date="2026-01-05", type="expense", amount=-42.50,
                    category="dining", description="Coffee Shop", account_id="checking")
    rows = [
        {"date": "2026-01-05", "amount": -42.50, "description": "Coffee Shop"},  # dup
        {"date": "2026-01-07", "amount": -8.00, "description": "Tea"},           # new
    ]
    result = ingest_extracted(rows, "checking", dry_run=True)
    assert result["duplicates_removed"] >= 1
    assert result["to_import"] == 1


# ── import_router integration ────────────────────────────────────────────────

def test_unknown_format_routes_to_llm_fallback(isolated_finance_dir):
    from import_router import import_file
    # A file that detects as "unknown" (no CSV/OFX/MT940 markers, binary-ish)
    path = _write("\x00\x01 gibberish no delimiters here just words", suffix=".dat")
    try:
        result = import_file(path, "checking", dry_run=True, keep_original=False)
        assert result.get("needs_llm_extraction") is True
        assert "schema" in result
    finally:
        os.unlink(path)
