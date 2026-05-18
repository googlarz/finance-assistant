#!/usr/bin/env python3
"""
Locale contract validator for finance-assistant.

Verifies that each locale's tax calculator exports the required function
and returns the required output keys with sensible types and value ranges.

Usage:
    python3 scripts/validate_locale.py               # validate all locales
    python3 scripts/validate_locale.py de uk         # validate specific locales

Exit code 0 = all locales pass. Non-zero = at least one failure.

Adding a new locale:
  1. Add an entry to LOCALE_CONTRACTS below.
  2. Specify the function to call, the test inputs, and the required output keys.
  3. Run this script — it will tell you exactly what's missing.
"""

from __future__ import annotations

import sys
import importlib
import traceback
from typing import Any

# ── Contract definitions ──────────────────────────────────────────────────────
#
# Each entry describes one locale. Structure:
#   "locale_code": {
#     "module": "locales.<code>.<module>",
#     "function": "function_name",
#     "test_inputs": [list of (args, kwargs) pairs — all must pass],
#     "required_keys": {
#       "key": (type_or_types, min_value_or_None, max_value_or_None)
#     }
#   }

LOCALE_CONTRACTS: dict[str, dict] = {
    "de": {
        "module": "locales.de.tax_calculator",
        "function": "calculate_refund",
        "test_inputs": [
            (
                [{"employment": {"annual_gross": 50_000}, "tax_profile": {"tax_year": 2024, "extra": {}}}],
                {},
            ),
        ],
        "required_keys": {
            # estimated_refund: float (negative = owed)
            "estimated_refund":  (float, None, None),
            # confidence_pct: int 0-100 (estimation quality score)
            "confidence_pct":    ((int, float), 0, 100),
        },
        "precision_keys": [],
    },
    "us": {
        "module": "locales.us.tax_calculator",
        "function": "calculate_liability",
        "test_inputs": [
            (
                [{"employment": {"annual_gross": 50_000}, "tax_profile": {"filing_status": "single", "tax_year": 2024, "extra": {}}}],
                {},
            ),
            (
                [{"employment": {"annual_gross": 120_000}, "tax_profile": {"filing_status": "married_filing_jointly", "tax_year": 2025, "extra": {}}}],
                {},
            ),
        ],
        "required_keys": {
            "taxable_income":     (float, 0.0, None),
            "total_tax":          (float, 0.0, None),
            "effective_rate":     (float, 0.0, 1.0),
            "currency":           (str,   None, None),
            "filing_status":      (str,   None, None),
        },
        "precision_keys": ["taxable_income", "total_tax", "effective_rate"],
    },
    "uk": {
        "module": "locales.uk.tax_calculator",
        "function": "calculate_tax",
        "test_inputs": [
            (
                [{"employment": {"annual_gross": 50_000}, "tax_profile": {"filing_status": "single", "tax_year": 2024, "extra": {}}}],
                {},
            ),
        ],
        "required_keys": {
            "tax":            (float, 0.0, None),
            "effective_rate": (float, 0.0, 1.0),
            "currency":       (str,   None, None),
            "net":            (float, 0.0, None),
        },
        "precision_keys": ["effective_rate"],
    },
    "fr": {
        "module": "locales.fr.tax_calculator",
        "function": "calculate_tax",
        "test_inputs": [
            (
                [{"employment": {"annual_gross": 40_000}, "tax_profile": {"tax_year": 2024, "extra": {}}}],
                {},
            ),
        ],
        "required_keys": {
            "income_tax":     (float, 0.0, None),
            "effective_rate": (float, 0.0, 1.0),
            "net":            (float, 0.0, None),
        },
        "precision_keys": ["effective_rate"],
    },
    "nl": {
        "module": "locales.nl.tax_calculator",
        "function": "calculate_tax",
        "test_inputs": [
            (
                [{"employment": {"annual_gross": 45_000}, "tax_profile": {"tax_year": 2024, "extra": {}}}],
                {},
            ),
        ],
        "required_keys": {
            "total_tax":      (float, 0.0, None),
            "effective_rate": (float, 0.0, 1.0),
        },
        "precision_keys": ["effective_rate"],
    },
    "pl": {
        "module": "locales.pl.tax_calculator",
        "function": "calculate_tax",
        "test_inputs": [
            (
                [{"employment": {"annual_gross": 60_000}, "tax_profile": {"tax_year": 2024, "extra": {}}}],
                {},
            ),
        ],
        "required_keys": {
            "effective_rate": (float, 0.0, 1.0),
            "currency":       (str,   None, None),
            "income_tax":     (float, 0.0, None),
        },
        "precision_keys": ["effective_rate"],
    },
}

# ── Validation logic ──────────────────────────────────────────────────────────

_PASS = "\033[32m✓\033[0m"
_FAIL = "\033[31m✗\033[0m"
_SKIP = "\033[33m~\033[0m"


def _check_precision(value: float, key: str, decimals: int = 4) -> str | None:
    """Return error string if float has more decimal places than allowed."""
    rounded = round(value, decimals)
    if abs(value - rounded) > 1e-9:
        return f"  {key}: precision exceeds {decimals} decimal places (got {value})"
    return None


def validate_locale(code: str, contract: dict) -> tuple[bool, list[str]]:
    """
    Validate one locale. Returns (passed, [error_lines]).
    """
    errors: list[str] = []

    # Import
    try:
        module = importlib.import_module(contract["module"])
    except ImportError as e:
        return False, [f"  ImportError: {e}"]
    except Exception as e:
        return False, [f"  Failed to import {contract['module']}: {e}"]

    # Resolve function
    fn_name = contract["function"]
    fn = getattr(module, fn_name, None)
    if fn is None:
        return False, [f"  Module {contract['module']} has no function '{fn_name}'"]

    # Run each test input
    for i, (args, kwargs) in enumerate(contract["test_inputs"], 1):
        input_label = f"test input {i}"
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            errors.append(f"  {input_label}: raised {type(e).__name__}: {e}")
            errors.append(f"    {traceback.format_exc().splitlines()[-1]}")
            continue

        if not isinstance(result, dict):
            errors.append(f"  {input_label}: return type must be dict, got {type(result).__name__}")
            continue

        # Check required keys
        for key, (expected_type, min_val, max_val) in contract["required_keys"].items():
            if key not in result:
                errors.append(f"  {input_label}: missing required key '{key}'")
                continue

            val = result[key]
            if not isinstance(val, expected_type):
                type_name = (
                    expected_type.__name__
                    if isinstance(expected_type, type)
                    else "/".join(t.__name__ for t in expected_type)
                )
                errors.append(
                    f"  {input_label}: key '{key}' must be {type_name}, "
                    f"got {type(val).__name__} ({val!r})"
                )
                continue

            if isinstance(val, (int, float)):
                if min_val is not None and val < min_val:
                    errors.append(f"  {input_label}: key '{key}' = {val} is below minimum {min_val}")
                if max_val is not None and val > max_val:
                    errors.append(f"  {input_label}: key '{key}' = {val} exceeds maximum {max_val}")

            if expected_type == str and not val:
                errors.append(f"  {input_label}: key '{key}' must be a non-empty string")

        # Check precision on nominated keys
        for key in contract.get("precision_keys", []):
            if key in result and isinstance(result[key], float):
                err = _check_precision(result[key], key)
                if err:
                    errors.append(f"  {input_label}:{err}")

    return len(errors) == 0, errors


def run(locales_to_check: list[str] | None = None) -> int:
    """Run the validator. Returns exit code."""
    codes_to_run = locales_to_check or list(LOCALE_CONTRACTS.keys())
    total = len(codes_to_run)
    passed = 0
    skipped = 0

    print(f"\nfinance-assistant locale validator\n{'─' * 40}")

    for code in codes_to_run:
        contract = LOCALE_CONTRACTS.get(code)
        if contract is None:
            print(f"{_SKIP} {code:6s}  (no contract defined — add to LOCALE_CONTRACTS)")
            skipped += 1
            continue

        ok, errors = validate_locale(code, contract)
        status = _PASS if ok else _FAIL
        fn_name = contract.get("function", "?")
        print(f"{status} {code:6s}  {contract['module']}.{fn_name}()")
        for err in errors:
            print(err)
        if ok:
            passed += 1

    failed = total - passed - skipped
    print(f"\n{'─' * 40}")
    print(f"Results: {passed}/{total - skipped} locales passed", end="")
    if skipped:
        print(f", {skipped} skipped", end="")
    if failed:
        print(f", {failed} FAILED")
    else:
        print()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    locales_arg = sys.argv[1:] or None
    sys.exit(run(locales_arg))
