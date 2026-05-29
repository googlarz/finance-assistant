"""Tests for locale_telemetry."""
from locale_telemetry import record, get_stats, format_stats


def test_record_and_stats(isolated_finance_dir):
    record("de", "tax_estimate")
    record("de", "tax_brief")
    record("us", "tax_estimate")
    stats = get_stats()
    assert stats["total"] == 3
    assert stats["by_locale"]["de"] == 2
    assert stats["by_locale"]["us"] == 1
    assert stats["by_operation"]["tax_estimate"] == 2


def test_stats_empty(isolated_finance_dir):
    stats = get_stats()
    assert stats == {"by_locale": {}, "by_operation": {}, "total": 0}


def test_format_stats_empty(isolated_finance_dir):
    assert "No locale usage" in format_stats()


def test_format_stats_nonempty(isolated_finance_dir):
    record("de", "tax_estimate")
    out = format_stats()
    assert "DE" in out
    assert "tax_estimate" in out


def test_record_never_raises(isolated_finance_dir):
    # Even with junk input, must not raise
    record(None, None)
    record("", "")


def test_records_no_financial_data(isolated_finance_dir):
    """Privacy: telemetry must only contain locale + operation + ts."""
    import json
    from locale_telemetry import _log_path
    record("de", "tax_estimate")
    line = _log_path().read_text().strip().split("\n")[0]
    entry = json.loads(line)
    assert set(entry.keys()) == {"ts", "locale", "operation"}
