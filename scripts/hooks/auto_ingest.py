#!/usr/bin/env python3
"""
UserPromptSubmit hook — detect financial data in user prompts.

Runs before Claude sees the message. Extracts what it can from the prompt,
then injects a structured hint into Claude's context via additionalContext.
Claude then asks the user for any missing details before saving.
No tmp files. No Stop hook needed.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

# Add scripts dir to path
_SCRIPTS = Path(__file__).parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# ── Finance keyword detection ─────────────────────────────────────────────────

_TRANSACTION = re.compile(
    r"\b(spent|paid|bought|purchased|charged|cost|fee|expense|bill|invoice|"
    r"received|earned|income|salary|bonus|refund|cashback)\b",
    re.IGNORECASE,
)
_BALANCE = re.compile(
    r"\b(balance|account|savings?|checking|current account|isa|401k|pension|"
    r"portfolio|holding|asset|net worth)\b",
    re.IGNORECASE,
)
_DEBT = re.compile(
    r"\b(mortgage|loan|debt|credit card|overdraft|owe|owing|repay|installment)\b",
    re.IGNORECASE,
)
_INVESTMENT = re.compile(
    r"\b(shares?|stocks?|etf|fund|units?|bonds?|crypto|btc|eth|invested?|"
    r"dividend|yield|return|gain|loss)\b",
    re.IGNORECASE,
)
_AMOUNT = re.compile(
    r"(?:€|\$|£|PLN|EUR|USD|GBP)\s*\d+|\d+\s*(?:€|\$|£|PLN|EUR|USD|GBP)|"
    r"\b\d{1,3}(?:[,\.]\d{3})*(?:\.\d{1,2})?\b",
)

def classify(text: str) -> list[str]:
    types = []
    if _TRANSACTION.search(text):
        types.append("transaction")
    if _BALANCE.search(text):
        types.append("balance")
    if _DEBT.search(text):
        types.append("debt")
    if _INVESTMENT.search(text):
        types.append("investment")
    # Only flag if there's an actual amount too — avoids false positives
    if types and not _AMOUNT.search(text):
        types = []
    return types


# ── Extraction helpers ────────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(
    r"(€|\$|£|PLN|EUR|USD|GBP)\s*(\d+(?:[,.]\d{1,2})?)"
    r"|(\d+(?:[,.]\d{1,2})?)\s*(€|\$|£|PLN|EUR|USD|GBP)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(today|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)\b",
    re.IGNORECASE,
)
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

def extract_date(text: str) -> str:
    """Extract date from prompt text, falling back to today."""
    today = date.today()
    m = _DATE_RE.search(text)
    if not m:
        return today.isoformat()
    token = m.group(1).lower()
    if token == "today":
        return today.isoformat()
    if token == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    if token in _WEEKDAYS:
        target_wd = _WEEKDAYS.index(token)
        days_back = (today.weekday() - target_wd) % 7
        if days_back == 0:
            days_back = 7  # "monday" when today is monday → last monday
        return (today - timedelta(days=days_back)).isoformat()
    # Numeric date e.g. 15/04 or 15.04.2025
    parts_list = re.split(r"[./-]", token)
    try:
        if len(parts_list) == 2:
            day, month = int(parts_list[0]), int(parts_list[1])
            return date(today.year, month, day).isoformat()
        elif len(parts_list) == 3:
            day, month, yr = int(parts_list[0]), int(parts_list[1]), int(parts_list[2])
            if yr < 100:
                yr += 2000
            return date(yr, month, day).isoformat()
    except Exception:
        pass
    return today.isoformat()
_CATEGORY_RE = re.compile(
    r"\b(groceries?|food|supermarket|restaurant|cafe|coffee|transport|"
    r"uber|taxi|fuel|petrol|rent|utilities|gas|electricity|water|"
    r"subscriptions?|netflix|spotify|gym|health|pharmacy|doctor|"
    r"clothing|shopping|entertainment|travel|hotel|flight|insurance)\b",
    re.IGNORECASE,
)

def extract_amount(text: str) -> tuple[float | None, str]:
    m = _AMOUNT_RE.search(text)
    if not m:
        return None, "EUR"
    currency_map = {"€": "EUR", "$": "USD", "£": "GBP"}
    # Group 1+2: symbol then number; group 3+4: number then symbol
    if m.group(1):
        sym, raw = m.group(1), m.group(2)
    else:
        sym, raw = m.group(4), m.group(3)
    currency = currency_map.get(sym, sym.upper() if sym else "EUR")
    raw = raw.replace(",", ".")
    try:
        return float(raw), currency
    except ValueError:
        return None, currency

def extract_category(text: str) -> str:
    m = _CATEGORY_RE.search(text)
    return m.group(1).lower() if m else "other"

_MERCHANT_RE = re.compile(
    r"\b(?:at|from|in|@)\s+([A-Z][a-zA-Z0-9&'\-\s]{1,30})",
    re.IGNORECASE,
)
_RATE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")

def extract_merchant(text: str) -> str | None:
    m = _MERCHANT_RE.search(text)
    return m.group(1).strip() if m else None


# ── Detection (no saving — Claude confirms details then saves) ────────────────

_DEBT_KEYWORDS = {
    "mortgage": "mortgage", "credit card": "credit card",
    "student loan": "student loan", "car loan": "car loan",
    "overdraft": "overdraft", "loan": "loan",
}
_ACCOUNT_KEYWORDS = {
    "savings": "savings", "checking": "checking",
    "current account": "checking", "isa": "isa",
    "pension": "pension", "401k": "retirement", "portfolio": "investment",
}
_INV_KEYWORDS = [
    (r"etf", "ETF"), (r"stocks?", "stock"), (r"bonds?", "bond"),
    (r"crypto", "crypto"), (r"btc", "Bitcoin"), (r"eth", "Ethereum"), (r"fund", "fund"),
]


def detect(prompt: str, types: list[str]) -> list[str]:
    lines = []
    prompt_lower = prompt.lower()

    if "transaction" in types:
        amount, currency = extract_amount(prompt)
        if amount is not None:
            category = extract_category(prompt)
            txn_date = extract_date(prompt)
            merchant = extract_merchant(prompt)
            sign_word = _TRANSACTION.search(prompt).group(1).lower()
            sign = -1 if sign_word in (
                "spent", "paid", "bought", "purchased", "charged", "cost",
                "fee", "expense", "bill", "invoice"
            ) else 1

            known_parts = [
                f"amount={sign * amount:+.2f} {currency}",
                f"date={txn_date}",
                f"category={category}",
            ]
            if merchant:
                known_parts.append(f"merchant={merchant}")

            missing = []
            if not merchant:
                missing.append("store/merchant name")
            if category == "other":
                missing.append("category (e.g. groceries, transport, restaurant)")
            if abs(amount) >= 20:
                missing.append("receipt photo (optional but useful)")

            lines.append(
                f"TRANSACTION DETECTED — extracted: {', '.join(known_parts)}. "
                f"Ask the user for: {', '.join(missing) if missing else 'confirmation to save'}. "
                f"Once you have all details, call add_transaction() to save."
            )

    if "balance" in types and "transaction" not in types:
        amount, currency = extract_amount(prompt)
        if amount is not None:
            account_type = next(
                (label for kw, label in _ACCOUNT_KEYWORDS.items() if kw in prompt_lower),
                "account"
            )
            lines.append(
                f"BALANCE DETECTED — extracted: {account_type} balance={amount:.2f} {currency}. "
                f"Ask user to confirm account name if unclear, then call "
                f"update_account_balance() to save."
            )

    if "debt" in types and "transaction" not in types:
        amount, currency = extract_amount(prompt)
        if amount is not None:
            debt_type = next(
                (label for kw, label in _DEBT_KEYWORDS.items() if kw in prompt_lower),
                "debt"
            )
            rate_m = _RATE_RE.search(prompt)
            rate = float(rate_m.group(1)) if rate_m else None
            known = f"type={debt_type}, balance={amount:.2f} {currency}"
            if rate:
                known += f", rate={rate}%"
            missing = ([] if rate else ["interest rate"]) + ["monthly payment (optional)"]
            lines.append(
                f"DEBT DETECTED — extracted: {known}. "
                f"Ask user for: {', '.join(missing)}. "
                f"Then call add_debt() to save."
            )

    if "investment" in types and "transaction" not in types:
        amount, currency = extract_amount(prompt)
        if amount is not None:
            inv_type = next(
                (label for pattern, label in _INV_KEYWORDS
                 if re.search(r"\b" + pattern + r"\b", prompt, re.IGNORECASE)),
                "investment"
            )
            ticker_m = _TICKER_RE.search(prompt)
            ticker = ticker_m.group(1) if ticker_m else None
            known = f"type={inv_type}, amount={amount:.2f} {currency}"
            if ticker:
                known += f", ticker={ticker}"
            missing = ([] if ticker else ["ticker/fund name"]) + ["number of units/shares"]
            lines.append(
                f"INVESTMENT DETECTED — extracted: {known}. "
                f"Ask user for: {', '.join(missing)}. "
                f"Then call add_holding() to save."
            )

    return lines


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        return

    prompt = (data.get("prompt") or data.get("message") or "").strip()
    if not prompt or len(prompt) < 8:
        return

    types = classify(prompt)
    if not types:
        return

    hints = detect(prompt, types)

    if hints:
        context = "Finance data detected in user message:\n" + "\n".join(f"  • {h}" for h in hints)
        out = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }
        print(json.dumps(out))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # Never block the session
