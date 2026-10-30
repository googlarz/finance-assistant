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
    """
    t = _NOISE.sub("", str(text or "").strip().strip('"'))
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
    return float(t)
