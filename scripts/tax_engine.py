"""
Country-agnostic tax engine for Finance Assistant.

Delegates all tax calculations to the active locale plugin.
The rest of the system never needs to know which country's rules apply.
"""

from __future__ import annotations

import importlib
from datetime import datetime
from typing import Optional

try:
    from profile_manager import get_profile, get_locale
    from finance_storage import get_tax_path, get_tax_claims_path, load_json, save_json
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from profile_manager import get_profile, get_locale
    from finance_storage import get_tax_path, get_tax_claims_path, load_json, save_json


ALLOWED_LOCALES = {"de", "uk", "fr", "nl", "pl", "us"}


def _validate_locale_code(locale_code: str) -> str:
    if locale_code not in ALLOWED_LOCALES:
        raise ValueError(
            f"Unknown locale {locale_code!r}. Supported: {sorted(ALLOWED_LOCALES)}"
        )
    return locale_code


def _load_locale(locale_code: str):
    """Dynamically import a locale plugin."""
    _validate_locale_code(locale_code)
    try:
        return importlib.import_module(f"locales.{locale_code}")
    except ImportError:
        # Try adding project root to path
        import os, sys
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        return importlib.import_module(f"locales.{locale_code}")


def get_active_locale() -> str:
    return get_locale()


def calculate_tax_estimate(profile: Optional[dict] = None, year: Optional[int] = None) -> dict:
    """Calculate tax estimate using the active locale plugin."""
    profile = profile or get_profile() or {}
    locale_code = profile.get("tax_profile", {}).get("locale") or get_locale()
    year = year or profile.get("meta", {}).get("tax_year", datetime.now().year)

    try:
        locale = _load_locale(locale_code)
        try:
            from locales.context import LocaleContext
            ctx = LocaleContext.from_finance_profile(profile, tax_year=year)
        except (ImportError, Exception):
            ctx = profile  # fallback to dict for locales that handle it
        result = locale.calculate_tax(ctx, year)
        result["locale"] = locale_code
        result["locale_name"] = getattr(locale, "LOCALE_NAME", locale_code.upper())
        try:
            from locale_telemetry import record
            record(locale_code, "tax_estimate")
        except Exception:
            pass
        return result
    except (ImportError, AttributeError) as e:
        return {
            "error": f"Locale '{locale_code}' not available or incomplete: {e}",
            "locale": locale_code,
            "suggestion": "Use set_locale() to change locale or help build the missing locale plugin.",
        }


def _num(*vals):
    """First value coercible to a non-None float, else None."""
    for v in vals:
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def get_tax_summary(profile: Optional[dict] = None, year: Optional[int] = None) -> dict:
    """Normalized, locale-agnostic tax totals for callers that need scalars.

    Locale plugins return wildly different shapes — US uses flat keys
    (federal_income_tax, social_security_tax), DE nests under `breakdown`
    (estimated_tax, total_tax_due, soli). Consumers that hand-read keys (the
    scenario engine did) silently miss them and fall back to crude guesses.
    This is the ONE place that normalization lives.

    Returns:
        {
          locale, year,
          gross,            # gross income used
          income_tax,       # income-tax component (always populated when computable)
          payroll_tax,      # employee social/payroll where the estimate includes it (US), else None
          total_tax,        # locale's complete tax figure (income + payroll/soli/etc.)
          net,              # gross - total_tax
          effective_rate,   # 0..1
          components,       # human note on what total_tax includes for this locale
          source,           # "engine"
          error?            # present only on failure
        }
    """
    est = calculate_tax_estimate(profile, year)
    if est.get("error"):
        return {"error": est["error"], "locale": est.get("locale"), "source": "error"}

    b = est.get("breakdown", {}) if isinstance(est.get("breakdown"), dict) else {}
    locale = est.get("locale", "")

    gross = _num(est.get("gross"), est.get("gross_income"), b.get("gross_income"))

    # Income tax: US federal_income_tax; DE breakdown.estimated_tax; others `tax`/income_tax
    income_tax = _num(est.get("tax"), est.get("federal_income_tax"),
                      b.get("estimated_tax"), b.get("income_tax"))

    # Surtax / solidarity (DE soli, etc.)
    soli = _num(est.get("soli"), b.get("soli")) or 0.0

    # Employee payroll/social — only where the estimate provides it annually (US SS+Medicare).
    # DE employee social is NOT in the income-tax estimate; left None (documented in components).
    ss = _num(est.get("social_security_tax")) or 0.0
    medi = _num(est.get("medicare_tax")) or 0.0
    se = _num(est.get("self_employment_tax")) or 0.0
    payroll_tax = (ss + medi + se) if (ss or medi or se) else None

    # Total tax: prefer the locale's own complete figure, else assemble.
    total_tax = _num(est.get("total_tax"), b.get("total_tax_due"))
    if total_tax is None:
        total_tax = (income_tax or 0.0) + soli + (payroll_tax or 0.0)

    net = (gross - total_tax) if (gross is not None and total_tax is not None) else None

    eff = est.get("effective_rate")
    effective_rate = None
    if eff is not None:
        try:
            eff = float(eff)
            effective_rate = eff if eff <= 1 else eff / 100.0
        except (TypeError, ValueError):
            pass
    if effective_rate is None and gross and income_tax is not None and gross > 0:
        effective_rate = round(income_tax / gross, 4)

    # Honest note on what total_tax covers per locale.
    if locale == "us":
        components = "US federal income tax + FICA (Social Security, Medicare)" + (
            " + self-employment tax" if se else "")
    elif locale == "de":
        components = ("DE income tax + Soli (+ church tax where set). NOTE: employee social "
                      "contributions (pension/health/care/unemployment) are NOT included here.")
    else:
        components = f"{locale.upper()} income tax (and surtaxes where applicable)"

    return {
        "locale": locale,
        "year": est.get("year") or year,
        "gross": round(gross, 2) if gross is not None else None,
        "income_tax": round(income_tax, 2) if income_tax is not None else None,
        "payroll_tax": round(payroll_tax, 2) if payroll_tax is not None else None,
        "total_tax": round(total_tax, 2) if total_tax is not None else None,
        "net": round(net, 2) if net is not None else None,
        "effective_rate": effective_rate,
        "components": components,
        "source": "engine",
    }


def generate_tax_claims(profile: Optional[dict] = None, year: Optional[int] = None, persist: bool = True) -> dict:
    """Generate tax claims using the active locale plugin."""
    profile = profile or get_profile() or {}
    locale_code = profile.get("tax_profile", {}).get("locale") or get_locale()
    year = year or profile.get("meta", {}).get("tax_year", datetime.now().year)

    try:
        locale = _load_locale(locale_code)
        try:
            from locales.context import LocaleContext
            ctx = LocaleContext.from_finance_profile(profile, tax_year=year)
        except (ImportError, Exception):
            ctx = profile  # fallback to dict for locales that handle it
        claims = locale.generate_tax_claims(ctx, year)
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "locale": locale_code,
            "tax_year": year,
            "claim_count": len(claims),
            "claims": claims,
        }
        if persist:
            save_json(get_tax_claims_path(locale_code, year), payload)
        return payload
    except (ImportError, AttributeError) as e:
        return {"error": str(e), "locale": locale_code, "claims": []}


def get_tax_deadlines(profile: Optional[dict] = None, year: Optional[int] = None) -> list[dict]:
    """Get filing deadlines from the active locale plugin."""
    profile = profile or get_profile() or {}
    locale_code = profile.get("tax_profile", {}).get("locale") or get_locale()
    year = year or datetime.now().year

    try:
        locale = _load_locale(locale_code)
        return locale.get_filing_deadlines(year)
    except (ImportError, AttributeError):
        return [{"error": f"Locale '{locale_code}' has no deadline information."}]


def get_tax_rules(profile: Optional[dict] = None, year: Optional[int] = None) -> dict:
    """Get tax rules from the active locale plugin."""
    profile = profile or get_profile() or {}
    locale_code = profile.get("tax_profile", {}).get("locale") or get_locale()
    year = year or datetime.now().year

    try:
        locale = _load_locale(locale_code)
        return locale.get_tax_rules(year)
    except (ImportError, AttributeError):
        return {"error": f"Locale '{locale_code}' not available."}


def get_social_contributions(
    profile: Optional[dict] = None,
    gross: Optional[float] = None,
    year: Optional[int] = None,
    filing_status: Optional[str] = None,
) -> dict:
    """Get social/payroll contribution estimates from the active locale plugin."""
    profile = profile or get_profile() or {}
    locale_code = profile.get("tax_profile", {}).get("locale") or get_locale()
    year = year or datetime.now().year
    if gross is None:
        gross = float(profile.get("employment", {}).get("annual_gross") or 0)
    if filing_status is None:
        filing_status = profile.get("tax_profile", {}).get("filing_status", "single") or "single"

    try:
        locale = _load_locale(locale_code)
        fn = getattr(locale, "get_social_contributions", None)
        if fn is None:
            return {"error": f"Locale '{locale_code}' does not implement get_social_contributions."}
        # Try with filing_status first (US locale supports it), fall back without
        try:
            return fn(gross, year, filing_status=filing_status)
        except TypeError:
            return fn(gross, year)
    except (ImportError, AttributeError) as e:
        return {"error": f"Locale '{locale_code}' not available: {e}"}


_available_locales_cache: list[dict] | None = None


def get_available_locales() -> list[dict]:
    """List available locale plugins."""
    global _available_locales_cache
    if _available_locales_cache is not None:
        return _available_locales_cache

    import os
    locales_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales")
    available = []
    if os.path.isdir(locales_dir):
        for entry in sorted(os.listdir(locales_dir)):
            init_path = os.path.join(locales_dir, entry, "__init__.py")
            if os.path.isfile(init_path):
                try:
                    locale = _load_locale(entry)
                    available.append({
                        "code": entry,
                        "name": getattr(locale, "LOCALE_NAME", entry.upper()),
                        "years": getattr(locale, "SUPPORTED_YEARS", []),
                        "currency": getattr(locale, "CURRENCY", ""),
                    })
                except ImportError:
                    available.append({"code": entry, "name": entry.upper(), "years": [], "error": "import failed"})
    _available_locales_cache = available
    return available
