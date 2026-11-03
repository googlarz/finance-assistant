"""
Shared helpers for the file importers: robust text decoding and near-duplicate
detection against already-stored transactions.
"""

from __future__ import annotations

import codecs
import re
import unicodedata
from typing import Optional

# ── Encoding ─────────────────────────────────────────────────────────────────

_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def _utf16_without_bom(data: bytes) -> Optional[str]:
    """Spot BOM-less UTF-16 of mostly-ASCII text by its NUL-byte pattern."""
    sample = data[:2000]
    if len(sample) < 4 or b"\x00" not in sample:
        return None
    even_nuls = sample[0::2].count(0)
    odd_nuls = sample[1::2].count(0)
    half = len(sample) // 2
    if odd_nuls > half * 0.8 and even_nuls == 0:
        return "utf-16-le"
    if even_nuls > half * 0.8 and odd_nuls == 0:
        return "utf-16-be"
    return None


def decode_bytes(data: bytes, hint: Optional[str] = None) -> tuple[str, str]:
    """Decode bank-export bytes. Returns (text, encoding_used).

    Order: BOM (UTF-8/16/32) -> BOM-less UTF-16 -> strict UTF-8 -> `hint`
    (e.g. cp1250 for Polish banks) -> cp1252 -> latin-1 (never fails).
    """
    for bom, enc in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(enc), enc
            except UnicodeDecodeError:
                break
    enc16 = _utf16_without_bom(data)
    if enc16:
        try:
            return data.decode(enc16), enc16
        except UnicodeDecodeError:
            pass

    candidates = ["utf-8"]
    if hint and hint.lower().replace("_", "-") not in ("utf-8", "utf8", "latin-1", "latin1", "cp1252"):
        candidates.append(hint)
    candidates += ["cp1252", "latin-1"]
    for enc in candidates:
        try:
            return data.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin-1", errors="replace"), "latin-1"  # pragma: no cover


def read_text(path: str, hint: Optional[str] = None, limit: Optional[int] = None) -> str:
    """Read a text file with BOM/encoding detection. `limit` reads only the
    first N bytes (for sniffing); a multi-byte character cut by the limit is
    dropped rather than forcing a fallback encoding."""
    with open(path, "rb") as f:
        data = f.read(limit) if limit else f.read()
    if limit and len(data) == limit:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.start >= len(data) - 3:
                data = data[:exc.start]
    return decode_bytes(data, hint)[0]


# ── Near-duplicate detection ─────────────────────────────────────────────────

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _tokens(text: str) -> list[str]:
    """Lowercased, accent-folded alphabetic tokens; tokens containing digits
    (card numbers, references, dates) are dropped because they are what banks
    most often rewrite between exports."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return [t for t in _NON_ALNUM.sub(" ", folded.lower()).split() if not any(c.isdigit() for c in t)]


def descriptions_match(a: str, b: str) -> bool:
    """True when two descriptions plausibly describe the same bank line."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False  # nothing to compare on (digits-only text): never "the same"
    sa, sb = set(ta), set(tb)
    return sa <= sb or sb <= sa


def _desc_key(txn: dict) -> str:
    return (txn.get("description") or "").lower()[:50]


def drop_near_duplicates(rows: list[dict], existing: list[dict],
                         exact_matched: Optional[list[dict]] = None) -> list[dict]:
    """Drop `rows` that match an already-stored transaction on date + amount
    and whose description/payee is merely a reworded version of it (the exact
    description match is handled by transaction_logger.deduplicate). Each
    stored transaction can absorb at most one new row, so genuine same-day,
    same-amount purchases are not collapsed wholesale.

    `exact_matched` are the file rows the exact dedup already absorbed; the
    stored transaction each one matched is consumed up front so it cannot
    absorb a second, merely similar row."""
    index: dict[tuple, list[dict]] = {}
    for old in existing:
        try:
            key = (old.get("date"), round(float(old.get("amount", 0)), 2))
        except (TypeError, ValueError):
            continue
        index.setdefault(key, []).append(old)

    consumed: set[int] = set()
    for row in exact_matched or []:
        try:
            key = (row.get("date"), round(float(row.get("amount", 0)), 2))
        except (TypeError, ValueError):
            continue
        cands = [o for o in index.get(key, []) if id(o) not in consumed]
        pick = next((o for o in cands if _desc_key(o) == _desc_key(row)), None) or (cands[0] if cands else None)
        if pick is not None:
            consumed.add(id(pick))
    kept = []
    for row in rows:
        try:
            key = (row.get("date"), round(float(row.get("amount", 0)), 2))
        except (TypeError, ValueError):
            kept.append(row)
            continue
        text = f"{row.get('payee') or ''} {row.get('description') or ''}"
        hit = None
        for old in index.get(key, []):
            if id(old) in consumed:
                continue
            if descriptions_match(text, f"{old.get('payee') or ''} {old.get('description') or ''}"):
                hit = old
                break
        if hit is not None:
            consumed.add(id(hit))
        else:
            kept.append(row)
    return kept
