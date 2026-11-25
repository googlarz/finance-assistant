"""
Finance Assistant Category Learner.

Remembers user corrections to auto-categorization and improves accuracy
over time. Uses a simple JSON-based keyword store — no ML needed.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

try:
    from finance_storage import ensure_subdir, load_json, save_json
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import ensure_subdir, load_json, save_json


def _learner_path():
    return ensure_subdir("learner") / "category_rules.json"


def _load_rules() -> dict:
    return load_json(_learner_path(), default={
        "keyword_overrides": {},  # "rewe" -> "food"
        "payee_rules": {},        # "REWE" -> "food"
        "corrections": [],        # History of corrections
    })


def _save_rules(rules: dict) -> None:
    rules["last_updated"] = datetime.now().isoformat()
    save_json(_learner_path(), rules)


def learn_correction(
    description: str,
    payee: Optional[str],
    old_category: str,
    new_category: str,
) -> dict:
    """
    Record a user correction. Extracts keywords and payee rules
    so future similar transactions auto-categorize correctly.
    """
    rules = _load_rules()

    # Only the payee is learned automatically: learning every word of a
    # description made generic words ("payment", "card") steal categories.
    learned_payee = None
    if payee and len(payee.strip()) >= 2:
        learned_payee = payee.strip().lower()
        rules["payee_rules"][learned_payee] = new_category

    # Record the correction for history
    rules["corrections"].append({
        "timestamp": datetime.now().isoformat(),
        "description": description,
        "payee": payee,
        "old_category": old_category,
        "new_category": new_category,
    })

    # Keep only last 500 corrections
    rules["corrections"] = rules["corrections"][-500:]

    _save_rules(rules)

    return {
        "learned": True,
        "payee_rule": learned_payee,
        "new_category": new_category,
    }


def _has_word(text: str, needle: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", text) is not None


def add_rule(pattern: str, category: str, kind: str = "payee") -> dict:
    """Add an explicit rule. kind: "payee" (matches payee) or "keyword" (matches description)."""
    key = (pattern or "").strip().lower()
    if len(key) < 3 or kind not in ("payee", "keyword") or not category:
        return {"error": "need pattern (3+ chars), category, kind payee|keyword"}
    rules = _load_rules()
    rules["payee_rules" if kind == "payee" else "keyword_overrides"][key] = category
    _save_rules(rules)
    return {"added": key, "kind": kind, "category": category}


def remove_rule(pattern: str) -> bool:
    key = (pattern or "").strip().lower()
    rules = _load_rules()
    found = False
    for bucket in ("payee_rules", "keyword_overrides"):
        if key in rules.get(bucket, {}):
            del rules[bucket][key]
            found = True
    if found:
        _save_rules(rules)
    return found


def apply_rules(dry_run: bool = True) -> dict:
    """Re-categorize transactions still in other_expense/other_income using the rules."""
    from transaction_logger import get_transactions, update_transaction_fields
    changes = []
    for t in get_transactions(account_id="all"):
        if t.get("category") not in ("other_expense", "other_income"):
            continue
        new = suggest_category(t.get("description") or "", t.get("payee"))
        if new and new != t["category"]:
            changes.append((t, new))
    if not dry_run:
        for t, new in changes:
            year = int(str(t["date"])[:4])
            update_transaction_fields(t["account_id"], year, t["id"], {"category": new})
    sample = [{"id": t["id"], "description": t.get("description"), "to": n} for t, n in changes[:20]]
    key = "would_change" if dry_run else "changed"
    return {key: len(changes), "sample": sample}


def recategorize_transaction(txn_id: str, new_category: str) -> dict:
    """Change one transaction's category and learn its payee as a rule."""
    from transaction_logger import get_transactions, update_transaction_fields
    for t in get_transactions(account_id="all"):
        if t.get("id") == txn_id:
            year = int(str(t["date"])[:4])
            ok = update_transaction_fields(t["account_id"], year, txn_id, {"category": new_category})
            learned = None
            if ok:
                learned = learn_correction(t.get("description"), t.get("payee"),
                                           t.get("category"), new_category)["payee_rule"]
            return {"updated": bool(ok), "learned_payee": learned, "category": new_category}
    return {"updated": False, "error": "transaction not found"}


def suggest_category(description: str, payee: Optional[str] = None) -> Optional[str]:
    """
    Check learned rules for a category suggestion.
    Returns None if no learned rule matches (fall through to default auto_categorize).
    """
    rules = _load_rules()

    # 1. Payee rules (highest priority): exact, else whole-word containment
    # for stored names of 4+ chars (short names would match everything).
    if payee:
        payee_key = payee.strip().lower()
        payee_rules = rules.get("payee_rules", {})
        if payee_key in payee_rules:
            return payee_rules[payee_key]
        for stored, category in payee_rules.items():
            if len(stored) >= 4 and _has_word(payee_key, stored):
                return category

    # 2. Payee rules also match inside the description (payee is often absent),
    # then keyword overrides; whole-word only.
    desc_lower = (description or "").lower()
    for stored, category in rules.get("payee_rules", {}).items():
        if len(stored) >= 4 and _has_word(desc_lower, stored):
            return category
    for keyword, category in rules.get("keyword_overrides", {}).items():
        if _has_word(desc_lower, keyword):
            return category

    return None


def get_learned_rules() -> dict:
    """Return current learned rules for display."""
    rules = _load_rules()
    return {
        "payee_rules": len(rules.get("payee_rules", {})),
        "keyword_rules": len(rules.get("keyword_overrides", {})),
        "total_corrections": len(rules.get("corrections", [])),
        "top_payees": dict(list(rules.get("payee_rules", {}).items())[:20]),
        "top_keywords": dict(list(rules.get("keyword_overrides", {}).items())[:20]),
    }


def clear_learned_rules() -> bool:
    """Reset all learned categorization rules."""
    _save_rules({
        "keyword_overrides": {},
        "payee_rules": {},
        "corrections": [],
    })
    return True


def enhanced_auto_categorize(description: str, amount: float, payee: Optional[str] = None) -> tuple[str, str]:
    """
    Auto-categorize with learned rules. Returns (category, source).
    source is "learned" if from user corrections, "default" if from keyword matching.
    """
    # First check learned rules
    learned = suggest_category(description, payee)
    if learned:
        return learned, "learned"

    # Fall through to default auto_categorize
    from transaction_logger import auto_categorize
    category, sub = auto_categorize(description, amount)
    return category, "default"
