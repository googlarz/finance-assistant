"""
Tax scenario comparisons — the law-accurate "what if?" a general assistant can't do.

Each comparison runs the SAME gross through the real tax engine
(tax_engine.get_tax_summary) under two configurations and shows the delta:

  - filing status:   single vs married filing jointly
  - employment type: W-2 employee vs 1099 self-employed (SE tax + QBI)
  - pre-tax savings: with vs without a 401(k)/pension contribution

Results are saveable/recallable via scenario_store, so you can revisit
"the freelance comparison I ran in March" and see if it still holds.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Optional

try:
    from tax_engine import get_tax_summary
    from profile_manager import get_profile
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from tax_engine import get_tax_summary
    from profile_manager import get_profile


def _summary_for(
    base: Optional[dict],
    gross: float,
    year: Optional[int],
    *,
    employment_type: Optional[str] = None,
    married: Optional[bool] = None,
    pretax_401k: Optional[float] = None,
) -> dict:
    """Build a profile variant and return its normalized tax summary."""
    p = deepcopy(base or {})
    p.setdefault("employment", {})["annual_gross"] = float(gross)
    if employment_type is not None:
        p["employment"]["type"] = employment_type
    if married is not None:
        p.setdefault("family", {})["status"] = "married" if married else "single"
    if pretax_401k is not None:
        p.setdefault("tax_profile", {}).setdefault("extra", {})["pretax_401k"] = float(pretax_401k)
    return get_tax_summary(p, year)


def _build(comparison_type: str, variants: list[tuple[str, dict]], year: Optional[int]) -> dict:
    """Assemble a comparison result. Winner = highest net (ties → lowest total_tax)."""
    scenarios = []
    for label, s in variants:
        scenarios.append({
            "label": label,
            "gross": s.get("gross"),
            "income_tax": s.get("income_tax"),
            "total_tax": s.get("total_tax"),
            "net": s.get("net"),
            "effective_rate": s.get("effective_rate"),
            "components": s.get("components"),
            "source": s.get("source"),
            "error": s.get("error"),
        })

    usable = [s for s in scenarios if s.get("net") is not None]
    best = None
    delta = None
    if len(usable) >= 2:
        best = max(usable, key=lambda s: s["net"])
        nets = sorted((s["net"] for s in usable), reverse=True)
        delta = round(nets[0] - nets[1], 2)

    return {
        "type": comparison_type,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "year": year or datetime.now().year,
        "scenarios": scenarios,
        "best": best["label"] if best else None,
        "net_advantage": delta,
        "engine": all(s.get("source") == "engine" for s in scenarios),
    }


# ── Named comparisons ─────────────────────────────────────────────────────────

def compare_filing_status(gross: float, year: Optional[int] = None, profile: Optional[dict] = None) -> dict:
    """Single vs married filing jointly at the same gross."""
    base = profile or get_profile() or {}
    return _build("filing_status", [
        ("Single", _summary_for(base, gross, year, married=False)),
        ("Married filing jointly", _summary_for(base, gross, year, married=True)),
    ], year)


def compare_employment_type(gross: float, year: Optional[int] = None, profile: Optional[dict] = None) -> dict:
    """W-2 employee vs 1099 self-employed at the same headline gross."""
    base = profile or get_profile() or {}
    return _build("employment_type", [
        ("W-2 employee", _summary_for(base, gross, year, employment_type="employed")),
        ("1099 self-employed", _summary_for(base, gross, year, employment_type="self_employed")),
    ], year)


def compare_pretax_contribution(
    gross: float, contribution: float, year: Optional[int] = None, profile: Optional[dict] = None
) -> dict:
    """With vs without a pre-tax retirement contribution.

    Also reports the tax saved (the whole point of the comparison).
    """
    base = profile or get_profile() or {}
    without = _summary_for(base, gross, year, pretax_401k=0)
    with_ = _summary_for(base, gross, year, pretax_401k=contribution)
    result = _build("pretax_contribution", [
        (f"No contribution", without),
        (f"Contribute {contribution:,.0f}", with_),
    ], year)
    # The headline number for this comparison is tax saved, not net (net is lower
    # because the contribution leaves your paycheck — but it's still your money).
    if without.get("total_tax") is not None and with_.get("total_tax") is not None:
        result["tax_saved"] = round(without["total_tax"] - with_["total_tax"], 2)
        result["contribution"] = float(contribution)
    return result


# ── Save / format ─────────────────────────────────────────────────────────────

def save(name: str, comparison: dict, profile: Optional[dict] = None) -> dict:
    """Persist a comparison via scenario_store for later recall."""
    from scenario_store import save_scenario
    return save_scenario(
        name=name,
        scenario_type=f"tax_{comparison['type']}",
        inputs={"year": comparison["year"]},
        result=comparison,
        profile_snapshot=profile,
    )


def format_comparison(comparison: dict, currency: str = "USD") -> str:
    """Human-readable comparison table."""
    sym = {"EUR": "€", "USD": "$", "GBP": "£"}.get(currency, currency + " ")
    titles = {
        "filing_status": "Filing status",
        "employment_type": "Employment type",
        "pretax_contribution": "Pre-tax contribution",
    }
    lines = [f"**Tax comparison — {titles.get(comparison['type'], comparison['type'])} ({comparison['year']})**", ""]

    if not comparison.get("engine"):
        lines.append("_⚠ No locale set — figures are estimates. Set a locale (e.g. `set locale us`) for law-accurate math._")
        lines.append("")

    for s in comparison["scenarios"]:
        if s.get("error"):
            lines.append(f"  {s['label']}: (unavailable — {s['error']})")
            continue
        eff = f" · {s['effective_rate']*100:.1f}% eff" if s.get("effective_rate") is not None else ""
        lines.append(f"  {s['label']}")
        lines.append(f"     income tax {sym}{(s['income_tax'] or 0):,.0f} · total tax {sym}{(s['total_tax'] or 0):,.0f} · net {sym}{(s['net'] or 0):,.0f}{eff}")

    lines.append("")
    if comparison["type"] == "pretax_contribution" and comparison.get("tax_saved") is not None:
        lines.append(f"→ Contributing {sym}{comparison['contribution']:,.0f} saves {sym}{comparison['tax_saved']:,.0f} in tax this year.")
    elif comparison.get("best"):
        adv = comparison.get("net_advantage")
        adv_str = f" — keeps {sym}{adv:,.0f} more" if adv else ""
        lines.append(f"→ Better: **{comparison['best']}**{adv_str}.")

    # Honest caveat where social isn't included
    if any("social contributions" in (s.get("components") or "").lower() for s in comparison["scenarios"]):
        lines.append("")
        lines.append("_Note: DE figures cover income tax + Soli; employee social contributions are not included._")
    return "\n".join(lines)
