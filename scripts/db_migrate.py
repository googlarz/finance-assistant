"""
Migrate existing JSON data into SQLite.
Run once: python3 scripts/db_migrate.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def migrate_all(finance_dir: Path) -> dict:
    """
    Read all existing JSON files and insert into SQLite.
    Returns {"migrated": {table: count}, "errors": [str]}
    """
    try:
        import sys, os
        sys.path.insert(0, str(Path(__file__).parent))
        from db import init_db, get_conn
        from finance_storage import load_json
    except ImportError as e:
        return {"migrated": {}, "errors": [f"Import error: {e}"]}

    init_db()
    migrated: dict[str, int] = {}
    errors: list[str] = []
    now = datetime.now().isoformat()

    def _migrate(label: str, fn):
        try:
            count = fn()
            if count:
                migrated[label] = count
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    # ── profile ──────────────────────────────────────────────────────────────
    def _migrate_profile() -> int:
        profile_path = finance_dir / "finance_profile.json"
        data = load_json(profile_path)
        if not data or not isinstance(data, dict):
            return 0
        count = 0
        with get_conn() as conn:
            for key, val in _flatten_dict(data):
                conn.execute(
                    "INSERT OR IGNORE INTO profile(key, value, updated_at) VALUES (?, ?, ?)",
                    (key, json.dumps(val), now),
                )
                count += 1
        return count

    _migrate(label="profile", fn=_migrate_profile)

    # ── accounts ─────────────────────────────────────────────────────────────
    def _migrate_accounts() -> int:
        accounts_path = finance_dir / "accounts" / "accounts.json"
        data = load_json(accounts_path)
        if not data:
            return 0
        accounts = data.get("accounts", []) if isinstance(data, dict) else []
        count = 0
        with get_conn() as conn:
            for acc in accounts:
                conn.execute(
                    """INSERT OR IGNORE INTO accounts
                       (id, name, type, current_balance, currency, institution,
                        is_asset, as_of, include_in_net_worth, include_in_budget,
                        notes, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        acc.get("id", ""),
                        acc.get("name", ""),
                        acc.get("type", "other"),
                        float(acc.get("current_balance") or 0),
                        acc.get("currency", "EUR"),
                        acc.get("institution"),
                        int(bool(acc.get("is_asset", True))),
                        acc.get("as_of") or now,
                        int(bool(acc.get("include_in_net_worth", True))),
                        int(bool(acc.get("include_in_budget", True))),
                        acc.get("notes"),
                        acc.get("as_of") or now,
                    ),
                )
                count += 1
        return count

    _migrate(label="accounts", fn=_migrate_accounts)

    # ── transactions ─────────────────────────────────────────────────────────
    def _migrate_transactions() -> int:
        txn_dir = finance_dir / "accounts" / "transactions"
        if not txn_dir.exists():
            return 0
        count = 0
        with get_conn() as conn:
            for txn_file in txn_dir.glob("*.json"):
                data = load_json(txn_file)
                if not data:
                    continue
                txns = data.get("transactions", []) if isinstance(data, dict) else []
                for t in txns:
                    conn.execute(
                        """INSERT OR IGNORE INTO transactions
                           (id, account_id, date, amount, currency,
                            category, description, source, payee, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            t.get("id", ""),
                            t.get("account_id", "default"),
                            t.get("date", ""),
                            float(t.get("amount") or 0),
                            t.get("currency", "EUR"),
                            t.get("category"),
                            t.get("description"),
                            t.get("import_source", "manual"),
                            t.get("payee"),
                            t.get("created_at") or now,
                        ),
                    )
                    count += 1
        return count

    _migrate(label="transactions", fn=_migrate_transactions)

    # ── budgets ───────────────────────────────────────────────────────────────
    def _migrate_budgets() -> int:
        budget_dir = finance_dir / "budgets"
        if not budget_dir.exists():
            return 0
        count = 0
        with get_conn() as conn:
            for budget_file in budget_dir.glob("*.json"):
                data = load_json(budget_file)
                if not data or not isinstance(data, dict):
                    continue
                year = data.get("year")
                month = data.get("month")
                if month:
                    month_key = f"{year}-{month:02d}"
                else:
                    month_key = str(year)
                currency = data.get("currency", "EUR")
                limits = data.get("category_limits", {})
                actuals = data.get("actuals", {})
                for cat, limit_val in limits.items():
                    actual_data = actuals.get(cat, {})
                    actual_val = (
                        float(actual_data.get("spent", 0))
                        if isinstance(actual_data, dict)
                        else float(actual_data or 0)
                    )
                    conn.execute(
                        """INSERT OR IGNORE INTO budget_categories
                           (month, category, limit_amount, actual_amount, currency)
                           VALUES (?, ?, ?, ?, ?)""",
                        (month_key, cat, float(limit_val), actual_val, currency),
                    )
                    count += 1
        return count

    _migrate(label="budget_categories", fn=_migrate_budgets)

    # ── goals ─────────────────────────────────────────────────────────────────
    def _migrate_goals() -> int:
        goals_path = finance_dir / "goals" / "goals.json"
        data = load_json(goals_path)
        if not data:
            return 0
        goals = data.get("goals", []) if isinstance(data, dict) else []
        count = 0
        with get_conn() as conn:
            for g in goals:
                conn.execute(
                    """INSERT OR IGNORE INTO goals
                       (id, name, target_amount, current_amount,
                        target_date, currency, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        g.get("id", ""),
                        g.get("name", ""),
                        float(g.get("target_amount") or 0),
                        float(g.get("current_amount") or 0),
                        g.get("target_date"),
                        g.get("currency", "EUR"),
                        g.get("status", "active"),
                        g.get("created_at") or now,
                        g.get("updated_at") or now,
                    ),
                )
                count += 1
        return count

    _migrate(label="goals", fn=_migrate_goals)

    # ── holdings (investments) ────────────────────────────────────────────────
    def _migrate_holdings() -> int:
        portfolio_path = finance_dir / "investments" / "portfolio.json"
        data = load_json(portfolio_path)
        if not data:
            return 0
        holdings = data.get("holdings", []) if isinstance(data, dict) else []
        count = 0
        with get_conn() as conn:
            for h in holdings:
                conn.execute(
                    """INSERT OR IGNORE INTO holdings
                       (id, name, ticker, asset_class, quantity,
                        purchase_price, current_price, currency, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        h.get("id", ""),
                        h.get("name", ""),
                        h.get("ticker"),
                        h.get("asset_class"),
                        float(h.get("quantity") or 0),
                        h.get("purchase_price"),
                        h.get("current_price"),
                        h.get("currency", "EUR"),
                        h.get("updated_at") or now,
                    ),
                )
                count += 1
        return count

    _migrate(label="holdings", fn=_migrate_holdings)

    # ── debts ─────────────────────────────────────────────────────────────────
    def _migrate_debts() -> int:
        debts_path = finance_dir / "debt" / "debts.json"
        data = load_json(debts_path)
        if not data:
            return 0
        debts = data.get("debts", []) if isinstance(data, dict) else []
        count = 0
        with get_conn() as conn:
            for d in debts:
                conn.execute(
                    """INSERT OR IGNORE INTO debts
                       (id, name, balance, interest_rate, minimum_payment,
                        type, currency, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        d.get("id", ""),
                        d.get("name", ""),
                        float(d.get("balance") or 0),
                        float(d.get("interest_rate") or 0),
                        float(d.get("minimum_payment") or 0),
                        d.get("type", "loan"),
                        d.get("currency", "EUR"),
                        d.get("updated_at") or now,
                    ),
                )
                count += 1
        return count

    _migrate(label="debts", fn=_migrate_debts)

    # ── snapshots ─────────────────────────────────────────────────────────────
    def _migrate_snapshots() -> int:
        count = 0
        snap_dirs = [
            ("net_worth", finance_dir / "net_worth" / "snapshots"),
            ("investment", finance_dir / "investments" / "snapshots"),
        ]
        with get_conn() as conn:
            for snap_type, snap_dir in snap_dirs:
                if not snap_dir.exists():
                    continue
                for snap_file in snap_dir.glob("*.json"):
                    data = load_json(snap_file)
                    if not data:
                        continue
                    date_str = snap_file.stem
                    conn.execute(
                        "INSERT OR IGNORE INTO snapshots(type, date, data) VALUES (?, ?, ?)",
                        (snap_type, date_str, json.dumps(data)),
                    )
                    count += 1
        return count

    _migrate(label="snapshots", fn=_migrate_snapshots)

    # ── recurring items ───────────────────────────────────────────────────────
    def _migrate_recurring() -> int:
        # recurring data may live in various places; try common paths
        candidates = [
            finance_dir / "recurring.json",
            finance_dir / "recurring" / "items.json",
        ]
        count = 0
        with get_conn() as conn:
            for path in candidates:
                data = load_json(path)
                if not data:
                    continue
                items = data.get("items", []) if isinstance(data, dict) else []
                for item in items:
                    conn.execute(
                        """INSERT OR IGNORE INTO recurring_items
                           (id, name, amount, frequency, day_of_month,
                            category, account_id, start_date, currency, active)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            item.get("id", ""),
                            item.get("name", ""),
                            float(item.get("amount") or 0),
                            item.get("frequency", "monthly"),
                            item.get("day_of_month"),
                            item.get("category"),
                            item.get("account_id"),
                            item.get("start_date"),
                            item.get("currency", "EUR"),
                            1 if item.get("active", True) else 0,
                        ),
                    )
                    count += 1
        return count

    _migrate(label="recurring_items", fn=_migrate_recurring)

    # ── scenarios ─────────────────────────────────────────────────────────────
    def _migrate_scenarios() -> int:
        scenarios_dir = finance_dir / "scenarios"
        if not scenarios_dir.exists():
            return 0
        count = 0
        with get_conn() as conn:
            for sc_file in scenarios_dir.glob("*.json"):
                data = load_json(sc_file)
                if not data or not isinstance(data, dict):
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO scenarios
                       (slug, name, type, inputs, result, profile_snapshot, saved_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        data.get("slug", sc_file.stem),
                        data.get("name", sc_file.stem),
                        data.get("type", "unknown"),
                        json.dumps(data.get("inputs", {})),
                        json.dumps(data.get("result", {})),
                        json.dumps(data.get("profile_snapshot")) if data.get("profile_snapshot") else None,
                        data.get("saved_at") or now,
                    ),
                )
                count += 1
        return count

    _migrate(label="scenarios", fn=_migrate_scenarios)

    # ── thresholds ────────────────────────────────────────────────────────────
    def _migrate_thresholds() -> int:
        thresholds_path = finance_dir / "thresholds.json"
        data = load_json(thresholds_path)
        if not data:
            return 0
        items = data.get("thresholds", []) if isinstance(data, dict) else []
        count = 0
        with get_conn() as conn:
            for t in items:
                conn.execute(
                    """INSERT OR IGNORE INTO thresholds
                       (metric, value, direction, label, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        t.get("metric", ""),
                        float(t.get("value") or 0),
                        t.get("direction", "above"),
                        t.get("label"),
                        t.get("created_at") or now,
                    ),
                )
                count += 1
        return count

    _migrate(label="thresholds", fn=_migrate_thresholds)

    # ── insurance policies ────────────────────────────────────────────────────
    def _migrate_insurance() -> int:
        insurance_path = finance_dir / "insurance" / "policies.json"
        data = load_json(insurance_path)
        if not data:
            return 0
        policies = data.get("policies", []) if isinstance(data, dict) else []
        count = 0
        with get_conn() as conn:
            for p in policies:
                conn.execute(
                    """INSERT OR IGNORE INTO insurance_policies
                       (id, name, type, premium, premium_frequency,
                        coverage_amount, renewal_date, provider, currency, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        p.get("id", ""),
                        p.get("name", ""),
                        p.get("type", "other"),
                        p.get("premium"),
                        p.get("premium_frequency"),
                        p.get("coverage_amount"),
                        p.get("renewal_date"),
                        p.get("provider"),
                        p.get("currency", "EUR"),
                        p.get("updated_at") or now,
                    ),
                )
                count += 1
        return count

    _migrate(label="insurance_policies", fn=_migrate_insurance)

    return {"migrated": migrated, "errors": errors}


def _flatten_dict(d: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Flatten a nested dict into (dot.key, value) pairs."""
    items = []
    if isinstance(d, dict):
        for k, v in d.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                items.append((full_key, v))
            else:
                items.append((full_key, v))
    return items


if __name__ == "__main__":
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import get_finance_dir
    finance_dir = get_finance_dir()
    result = migrate_all(finance_dir)
    print("Migration complete:")
    for table, count in result["migrated"].items():
        print(f"  {table}: {count} rows")
    if result["errors"]:
        print("Errors:")
        for err in result["errors"]:
            print(f"  {err}")
