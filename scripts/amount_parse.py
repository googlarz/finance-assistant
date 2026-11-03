"""Single place that turns a bank-export amount string into a float.

Used by the CSV, OFX and broker importers so they cannot disagree about
"1.234,56" (German) vs "1,234.56" (US).
"""
from __future__ import annotations

import re
from typing import Optional

_NOISE = re.compile(r"[\s $€£¥₹₽]|CHF|PLN|EUR|USD|GBP", re.IGNORECASE)


def parse_amount(text: object, decimal: Optional[str] = None) -> float:
    """Parse an amount string; raise ValueError if it is not a number.

    When both separators appear, the one that comes last is the decimal point.
    With only one kind of separator, `decimal` (",", "." or None) says what it
    means; None treats "," as a decimal comma and "." as a decimal point.

    Ambiguous case: a single separator followed by exactly three digits
    ("1.000", "1,000") cannot be told apart from a thousands separator without
    context. Without a hint "1.000" -> 1.0 and "1,000" -> 1.0; pass
    decimal="," for "1.000" -> 1000.0 or decimal="." for "1,000" -> 1000.0.
    Callers that read a whole column/file should use `infer_decimal` to get
    the hint. Several identical separators ("1.000.000") are always thousands.
    """
    t = _NOISE.sub("", str(text or "").strip().strip('"')).replace("\u2212", "-")
    negative = False
    if t.startswith("(") and t.endswith(")"):  # accounting style: (1.234,56)
        t, negative = t[1:-1], True
    elif t.endswith("-") and not t.startswith("-"):  # trailing minus: 1.234,56-
        t, negative = t[:-1], True
    if not t:
        return 0.0
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        # several commas can only be thousands separators ("1,234,567")
        thousands = decimal == "." or t.count(",") > 1
        t = t.replace(",", "") if thousands else t.replace(",", ".")
    elif "." in t and (decimal == "," or t.count(".") > 1):
        t = t.replace(".", "")
    value = float(t)
    return -abs(value) if negative else value


def infer_decimal(values) -> Optional[str]:
    """Infer the decimal separator ("," or ".") used by a set of amount strings.

    Evidence: a value with both separators (the last one is the decimal), a
    repeated separator (it is thousands, so the other one is the decimal), or a
    single separator not followed by exactly three digits. Single separator +
    exactly three digits is ambiguous and casts no vote. Returns None when there
    is no evidence or the evidence contradicts itself.
    """
    votes = set()
    for v in values:
        t = _NOISE.sub("", str(v or "").strip().strip('"')).replace("\u2212", "-")
        t = t.strip("()-")
        commas, dots = t.count(","), t.count(".")
        if commas and dots:
            votes.add("," if t.rfind(",") > t.rfind(".") else ".")
        elif commas > 1:
            votes.add(".")
        elif dots > 1:
            votes.add(",")
        elif commas == 1 or dots == 1:
            sep = "," if commas else "."
            if len(t.rsplit(sep, 1)[1]) != 3:
                votes.add(sep)
    return votes.pop() if len(votes) == 1 else None
