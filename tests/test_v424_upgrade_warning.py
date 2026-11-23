"""v4.2.4: warn when a re-import may overlap rows stored by an older version."""
import os
import tempfile


def _import(csv_content, **kw):
    from import_router import import_file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
    try:
        return import_file(f.name, account_id="checking", dry_run=True, keep_original=False, **kw)
    finally:
        os.unlink(f.name)


CSV = (
    '"Date","Description","Amount","Running Bal."\n'
    '"01/05/2024","Coffee Shop","-42.50","57.50"\n'
    '"01/06/2024","Bakery","-10.00","47.50"\n'
)


def _seed(**kw):
    from transaction_logger import add_transaction
    base = dict(date="2024-01-05", type="expense", amount=-42.50, category="dining",
                description="Coffee Shop", account_id="checking")
    base.update(kw)
    add_transaction(**base)


def test_clean_reimport_has_no_warning(isolated_finance_dir):
    _seed()
    assert "warnings" not in _import(CSV)


def test_warns_on_stored_empty_description(isolated_finance_dir):
    _seed(date="2024-01-06", amount=-3.0, description="")
    assert _import(CSV).get("warnings")


def test_warns_on_opposite_sign_same_amount(isolated_finance_dir):
    _seed(type="income", amount=42.50)
    assert _import(CSV).get("warnings")


def test_empty_description_outside_range_ignored(isolated_finance_dir):
    _seed(date="2024-03-01", amount=-3.0, description="")
    assert "warnings" not in _import(CSV)
