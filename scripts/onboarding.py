"""
Guided onboarding wizard for new Finance Assistant users.
9 steps, saves progress after each step, resumable.
State stored in .finance/onboarding_state.json
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

try:
    from finance_storage import get_finance_dir, save_json, load_json
    from profile_manager import update_profile, get_profile
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from finance_storage import get_finance_dir, save_json, load_json
    from profile_manager import update_profile, get_profile

try:
    from data_coach import get_unlock_nudge, format_nudge as _format_nudge
    _coach_available = True
except ImportError:
    _coach_available = False


STEPS = [
    "basics",       # name, country, currency
    "employment",   # type, gross income, employer
    "housing",      # rent/own, monthly cost, location
    "goals",        # at least one savings goal
    "debts",        # loans, credit cards, etc.
    "investments",  # stocks, ETFs, pension, etc.
    "accounts",     # at least one bank account
    "tax",          # locale-specific: Steuerklasse / tax code / etc.
    "budget",       # auto-suggest 50/30/20 or custom
]

STEP_LABELS = {
    "basics": "Basics",
    "employment": "Employment",
    "housing": "Housing",
    "goals": "Savings Goals",
    "debts": "Debts",
    "investments": "Investments",
    "accounts": "Accounts",
    "tax": "Tax",
    "budget": "Budget",
}

# Country code → locale mapping
_COUNTRY_TO_LOCALE: dict[str, str] = {
    "germany": "de", "deutschland": "de", "de": "de",
    "uk": "uk", "united kingdom": "uk", "england": "uk", "gb": "uk", "britain": "uk",
    "ireland": "ie", "éire": "ie", "ie": "ie",
    "france": "fr", "frankreich": "fr", "fr": "fr",
    "netherlands": "nl", "holland": "nl", "nl": "nl",
    "poland": "pl", "polska": "pl", "pl": "pl",
    "usa": "us", "us": "us", "united states": "us", "america": "us",
}

_COUNTRY_CURRENCY: dict[str, str] = {
    "de": "EUR", "fr": "EUR", "nl": "EUR", "ie": "EUR",
    "uk": "GBP",
    "pl": "PLN",
    "us": "USD",
}

_LOCALE_NAMES: dict[str, str] = {
    "de": "German",
    "uk": "UK",
    "ie": "Irish",
    "fr": "French",
    "nl": "Dutch",
    "pl": "Polish",
    "us": "US",
}


# ── State file ────────────────────────────────────────────────────────────────

def _get_state_path() -> Path:
    return get_finance_dir() / "onboarding_state.json"


def get_onboarding_state() -> dict:
    """Load current onboarding state from .finance/onboarding_state.json"""
    path = _get_state_path()
    default: dict[str, Any] = {
        "completed_steps": [],
        "skipped_steps": [],
        "step_data": {},
        "started": False,
    }
    return load_json(path, default=default) or default


def save_onboarding_state(state: dict) -> None:
    """Save onboarding state atomically."""
    save_json(_get_state_path(), state)


# ── Progress queries ──────────────────────────────────────────────────────────

def is_onboarding_complete() -> bool:
    """True if all steps completed or skipped."""
    state = get_onboarding_state()
    done = set(state.get("completed_steps", [])) | set(state.get("skipped_steps", []))
    return all(s in done for s in STEPS)


def get_current_step() -> str:
    """Return the current incomplete step name, or 'complete'."""
    state = get_onboarding_state()
    done = set(state.get("completed_steps", [])) | set(state.get("skipped_steps", []))
    for step in STEPS:
        if step not in done:
            return step
    return "complete"


def get_step_progress() -> dict:
    """
    Return:
    {
      "current_step": str,
      "step_number": int,       # 1-9
      "total_steps": int,       # 9
      "completed_steps": [str],
      "remaining_steps": [str],
      "pct_complete": int,
    }
    """
    state = get_onboarding_state()
    completed = state.get("completed_steps", [])
    skipped = state.get("skipped_steps", [])
    done = set(completed) | set(skipped)

    current = get_current_step()
    remaining = [s for s in STEPS if s not in done]

    if current == "complete":
        step_number = len(STEPS)
    else:
        step_number = STEPS.index(current) + 1

    total = len(STEPS)
    finished_count = len(done)
    pct = int(finished_count / total * 100)

    return {
        "current_step": current,
        "step_number": step_number,
        "total_steps": total,
        "completed_steps": completed,
        "skipped_steps": skipped,
        "remaining_steps": remaining,
        "pct_complete": pct,
    }


# ── Prompts ───────────────────────────────────────────────────────────────────

def get_step_prompt(step: str, locale: str = None) -> str:
    """
    Return the question Claude should ask for this step.
    Warm, conversational prompts that explain what each step unlocks.
    """
    locale = locale or "default"
    idx = STEPS.index(step) + 1 if step in STEPS else 0
    total = len(STEPS)

    profile = get_profile() or {}
    name = profile.get("personal", {}).get("name", "")

    if step == "basics":
        return (
            f"Step {idx} of {total} — Let's get you set up — this takes about 5 minutes, "
            "and the more you tell me, the more specific I can be with my advice.\n\n"
            "To start: what's your name, and which country are you based in?\n\n"
            "(Once I know where you are, I'll automatically set up the right currency and tax rules.)"
        )

    if step == "employment":
        greeting = f"Hey {name}! " if name else ""
        return (
            f"Step {idx} of {total} — Employment\n\n"
            f"{greeting}Income is the foundation of almost everything I can help with — "
            "your tax situation, how fast you can realistically save, whether your budget makes sense.\n\n"
            "Are you employed, self-employed, or freelance? And roughly what's your gross annual income?\n\n"
            "(Ballpark is fine — I just need an order of magnitude. E.g. 'Employed, around €65k')"
        )

    if step == "housing":
        return (
            f"Step {idx} of {total} — Housing\n\n"
            "Do you rent or own? And what's your monthly housing cost — rent or mortgage payment?\n\n"
            "This is usually the biggest line item, so getting it right matters. It also lets me benchmark "
            "how much you're paying against typical ranges and, when the time comes, give you an honest "
            "rent-vs-buy comparison.\n\n"
            "(E.g. 'Renting in Berlin, €1,200/month' or 'Mortgage, €980/month')"
        )

    if step == "goals":
        name_part = f", {name}" if name else ""
        return (
            f"Step {idx} of {total} — Savings Goals\n\n"
            f"What are you working toward{name_part}?\n\n"
            "This is where we go from just tracking money to actually doing something with it. "
            "Tell me one thing you're saving for — an emergency fund, a house deposit, a trip, "
            "retiring early, paying off debt, whatever's on your mind.\n\n"
            "Give me a name, a rough target amount, and when you'd like to get there. "
            "E.g. 'Emergency fund €10k by end of year' or 'Japan trip €3k in 8 months'. "
            "You can add more goals later."
        )

    if step == "debts":
        return (
            f"Step {idx} of {total} — Debts\n\n"
            "Any debts worth mentioning? — loans, credit cards, overdrafts, a mortgage, student debt?\n\n"
            "This one has a big impact on advice. If you have high-interest debt, the single most useful "
            "thing I can do is show you the optimal payoff order and exactly how much interest you can save. "
            "Even if you're just curious, the numbers are usually eye-opening.\n\n"
            "You can say 'no debts' or 'skip' if this doesn't apply.\n\n"
            "(E.g. 'Credit card €3k at 18%, car loan €8k at 6%' — just rough figures)"
        )

    if step == "investments":
        currency = profile.get("meta", {}).get("primary_currency", "EUR")
        return (
            f"Step {idx} of {total} — Investments\n\n"
            "Do you have any investments or a pension? — stocks, ETFs, a brokerage account, "
            "a company pension, ISA, a Riester/Rürup contract?\n\n"
            "Even a ballpark total is useful. It lets me track your net worth properly, calculate your "
            "FIRE timeline, and flag whether your allocation makes sense for where you're headed.\n\n"
            "Say 'nothing yet' to skip — there's no wrong answer here.\n\n"
            f"(E.g. 'About {currency} 20k in ETFs at a brokerage account, plus a company pension' or 'Just starting out, nothing yet')"
        )

    if step == "accounts":
        return (
            f"Step {idx} of {total} — Accounts\n\n"
            "Last piece of the infrastructure: what bank accounts do you have?\n\n"
            "Just names and types — no account numbers or IBANs needed. Once I have these, I can track "
            "your balances per account and import your bank statements directly if you want.\n\n"
            "(E.g. 'DKB checking, ING savings' or 'Monzo current, Marcus savings')"
        )

    if step == "tax":
        if locale == "de":
            return (
                f"Step {idx} of {total} — Tax\n\n"
                "Almost done — a few quick tax questions so I can give you accurate numbers.\n\n"
                "Germany's tax system has a few variables that change the calculation significantly:\n"
                "• What's your Steuerklasse? (1–6)\n"
                "• Do you pay Kirchensteuer?\n"
                "• Which Bundesland are you in?\n\n"
                "(E.g. 'Klasse 1, no Kirchensteuer, Berlin' — or just what you know, "
                "I'll fill in defaults for the rest)"
            )
        if locale == "uk":
            return (
                f"Step {idx} of {total} — Tax\n\n"
                "Almost done — just a couple of UK tax questions.\n\n"
                "• What's your tax code? (It's on your payslip — usually something like 1257L)\n"
                "• Do you file a Self Assessment return?\n\n"
                "(E.g. '1257L, no self-assessment' — skip if you're not sure, PAYE defaults are fine)"
            )
        if locale == "fr":
            return (
                f"Step {idx} of {total} — Tax\n\n"
                "Presque terminé — quelques questions fiscales rapides.\n\n"
                "• Quelle est votre situation familiale ? (célibataire, marié·e, pacsé·e)\n"
                "• Combien de parts fiscales ?\n\n"
                "(Par exemple : 'Célibataire, 1 part' ou 'Marié·e avec 2 enfants, 3 parts')"
            )
        if locale == "nl":
            return (
                f"Step {idx} of {total} — Tax\n\n"
                "Almost there — one Dutch tax question.\n\n"
                "Your Box 3 assets — savings and investments combined — are taxed differently if they "
                "exceed €57,000. Do yours?\n\n"
                "(E.g. 'No, well below that' or 'Yes, around €80k')"
            )
        if locale == "pl":
            return (
                f"Step {idx} of {total} — Tax\n\n"
                "Prawie gotowe — kilka szybkich pytań podatkowych.\n\n"
                "• Czy masz mniej niż 26 lat? (ulga dla młodych — brak podatku do €85,5k)\n"
                "• Czy rozliczasz się wspólnie z małżonkiem?\n\n"
                "(Np. 'Tak, mam 24 lata' lub 'Nie, rozliczam się samodzielnie')"
            )
        if locale == "us":
            return (
                f"Step {idx} of {total} — Tax\n\n"
                "A few quick questions for your federal tax estimate.\n\n"
                "• What's your filing status? (single / married filing jointly / head of household)\n"
                "• W-2 employee or self-employed / 1099?\n"
                "• Did you make pre-tax 401(k) contributions this year? If so, roughly how much?\n"
                "• Any HSA contributions?\n\n"
                "If you have your most recent pay stub handy, Box 2 ('Federal income tax withheld') "
                "is the number I'll use to estimate your refund.\n\n"
                "(Skip anything you're not sure about — defaults are fine to start)"
            )
        # Generic fallback
        return (
            f"Step {idx} of {total} — Tax\n\n"
            "A few tax questions to help with planning:\n"
            "• What's your filing status? (single, married, etc.)\n"
            "• Any special tax situations worth noting?\n"
            "(Keep it brief — we can go deeper later)"
        )

    if step == "budget":
        emp = profile.get("employment", {})
        gross = emp.get("annual_gross")
        currency = profile.get("meta", {}).get("primary_currency", "EUR")
        if gross:
            monthly = gross / 12
            needs = monthly * 0.50
            wants = monthly * 0.30
            savings = monthly * 0.20
            income_line = (
                f"Based on your income of {currency} {monthly:,.0f}/month, that's:\n"
                f"  • {currency} {needs:,.0f} needs / "
                f"{currency} {wants:,.0f} wants / "
                f"{currency} {savings:,.0f} savings"
            )
        else:
            income_line = "Enter your monthly take-home and I'll calculate the splits."

        return (
            f"Step {idx} of {total} — Budget\n\n"
            "One last thing — let's set up your budget so I can track spending against it.\n\n"
            "The simplest starting point is the 50/30/20 rule:\n"
            "  • 50% needs (housing, food, transport, utilities)\n"
            "  • 30% wants (dining out, entertainment, subscriptions)\n"
            "  • 20% savings and debt repayment\n\n"
            f"{income_line}\n\n"
            "Want to go with this, or adjust the splits? (You can always change it later.)"
        )

    return f"Step {idx} of {total} — {STEP_LABELS.get(step, step)}\n\nLet's set up your {step}."


# ── Value previews ────────────────────────────────────────────────────────────

def _append_coach_nudge(base_msg: str, profile: dict) -> str:
    """Append a one-line data-coach nudge if available and message is short enough."""
    if not _coach_available:
        return base_msg
    if len(base_msg) > 300:
        return base_msg
    try:
        nudge = get_unlock_nudge(profile)
        if nudge:
            return base_msg + f"\n\nNext: add {nudge['add']} and I can show you {nudge['unlocks'][0].lower()}."
    except Exception:
        pass
    return base_msg


def get_step_value_preview(step: str, data: dict) -> str:
    """
    Returns a short sentence showing what just became possible after a step completes.
    Called by the skill after complete_step() succeeds.
    """
    profile = get_profile() or {}
    base = _step_value_preview_inner(step, data, profile)
    return _append_coach_nudge(base, profile)


def _step_value_preview_inner(step: str, data: dict, profile: dict) -> str:
    currency = profile.get("meta", {}).get("primary_currency", "EUR")

    if step == "basics":
        locale = data.get("locale", "de")
        locale_name = _LOCALE_NAMES.get(locale, locale.upper())
        return f"Got it — I've set up {currency} and {locale_name} tax rules. Let's keep going."

    if step == "employment":
        gross = data.get("gross_annual")
        if gross:
            # Rough effective rate: 28% for <50k, 32% for 50-80k, 35% for >80k
            if gross < 50000:
                rate = 0.28
            elif gross <= 80000:
                rate = 0.32
            else:
                rate = 0.35
            takehome = int(gross * (1 - rate) / 12)
            return (
                f"Based on {currency} {gross:,}/year, your take-home is roughly "
                f"{currency} {takehome:,}/month after tax. "
                "I can sharpen this once we get to the tax step."
            )
        return "Got it — I'll use your income details to calibrate your plan."

    if step == "housing":
        cost = data.get("monthly_cost")
        if cost:
            emp = profile.get("employment", {})
            gross = emp.get("annual_gross")
            if gross:
                # Use same rough take-home calculation
                if gross < 50000:
                    rate = 0.28
                elif gross <= 80000:
                    rate = 0.32
                else:
                    rate = 0.35
                takehome_monthly = gross * (1 - rate) / 12
                pct = cost / takehome_monthly * 100
                if pct < 28:
                    label = "well within the comfortable range"
                elif pct <= 35:
                    label = "on the higher side"
                else:
                    label = "a significant chunk"
                return (
                    f"Housing at {currency} {cost}/month is {pct:.0f}% of your estimated take-home — "
                    f"{label}."
                )
            return f"Got it. Once I know your income I can benchmark this properly."
        return "Got it. Once I know your income I can benchmark this properly."

    if step == "goals":
        goals = data.get("goals", [])
        if goals:
            g = goals[0]
            goal_name = g.get("name", "your goal")
            timeline = g.get("timeline", "")
            target = g.get("target_amount")
            if timeline:
                return f"Love it — {goal_name} by {timeline}. I'll track your progress and let you know if you're on pace."
            elif target:
                return f"Love it — {goal_name} ({currency} {target:,}). I'll track your progress and let you know if you're on pace."
            else:
                return "Got it. Once you have a target amount in mind, I can tell you exactly what to save each month."
        return "Got it. Once you have a target amount in mind, I can tell you exactly what to save each month."

    if step == "debts":
        if data.get("no_debts"):
            return "Good news — no debt means all your surplus goes straight toward your goals."
        debts = data.get("debts", [])
        if debts:
            total_debt = sum(d.get("balance", 0) for d in debts)
            return (
                f"With {currency} {total_debt:,.0f} in debt, the first thing I can look at is the "
                "optimal payoff order. We'll do that properly once setup is done."
            )
        return "Got it. I'll factor this in once setup is done."

    if step == "investments":
        if data.get("no_investments"):
            return "No problem — we'll look at investment options once you're set up."
        investments = data.get("investments", [])
        if investments:
            total = sum(i.get("value", 0) for i in investments)
            if total > 0:
                return (
                    f"With {currency} {total:,.0f} invested so far, your FIRE journey has already started. "
                    "I'll track progress and flag rebalancing when needed."
                )
            return "Got it — I'll track your investments and flag rebalancing when needed."
        return "No problem — we'll look at investment options once you're set up."

    if step == "accounts":
        return "Got your accounts noted. You can import statements anytime with 'import [filename]'."

    if step == "tax":
        import datetime
        year = datetime.date.today().year
        return f"Tax setup done. I can now run accurate projections for {year}."

    if step == "budget":
        emp = profile.get("employment", {})
        gross = emp.get("annual_gross")
        if gross:
            monthly = gross / 12
            needs = monthly * 0.50
            wants = monthly * 0.30
            savings = monthly * 0.20
            return (
                f"Budget set up: {currency} {needs:,.0f} needs / "
                f"{currency} {wants:,.0f} wants / "
                f"{currency} {savings:,.0f} savings per month. "
                "I'll track against this as you log transactions."
            )
        return "Budget method saved. Add your income and I'll give you the actual numbers."

    return f"Got it — {step} step complete."


# ── Parse responses ───────────────────────────────────────────────────────────

def parse_step_response(step: str, user_text: str, locale: str = "de") -> dict:
    """
    Extract structured data from a natural language response.
    Returns a dict of extracted fields, or {"needs_clarification": True, "question": str}.
    Uses regex + heuristics — deterministic, no LLM calls.
    """
    text = user_text.strip()
    lower = text.lower()

    if step == "basics":
        return _parse_basics(text, lower)

    if step == "employment":
        return _parse_employment(text, lower)

    if step == "housing":
        return _parse_housing(text, lower)

    if step == "goals":
        return _parse_goals(text, lower)

    if step == "debts":
        return _parse_debts(text, lower)

    if step == "investments":
        return _parse_investments(text, lower)

    if step == "accounts":
        return _parse_accounts(text, lower)

    if step == "tax":
        return _parse_tax(text, lower, locale)

    if step == "budget":
        return _parse_budget(text, lower)

    return {"raw": text}


def _parse_basics(text: str, lower: str) -> dict:
    result: dict[str, Any] = {}

    # Extract name — "I'm Alex", "my name is Alex", "I am Alex"
    name_match = re.search(
        r"(?:i(?:'m| am)|my name is|name[:\s]+)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        text, re.IGNORECASE
    )
    if name_match:
        result["name"] = name_match.group(1).strip()

    # Extract country
    for country_str, code in _COUNTRY_TO_LOCALE.items():
        if re.search(r'\b' + re.escape(country_str) + r'\b', lower):
            result["country"] = "GB" if code == "uk" else code.upper()
            result["locale"] = code
            result["currency"] = _COUNTRY_CURRENCY.get(code, "EUR")
            break

    if not result:
        return {"needs_clarification": True, "question": "Could you tell me your name and country?"}

    return result


def _parse_employment(text: str, lower: str) -> dict:
    result: dict[str, Any] = {}

    # Employment type
    if re.search(r'\b(self.?employed|selbst.?st[äa]ndig)\b', lower):
        result["employment_type"] = "self_employed"
    elif re.search(r'\bfreelance[rd]?\b', lower):
        result["employment_type"] = "freelancer"
    elif re.search(r'\b(employed|angestellt|employee)\b', lower):
        result["employment_type"] = "employed"
    elif re.search(r'\b(retired|rentner|pension)\b', lower):
        result["employment_type"] = "retired"

    # Gross income — match €65k, €65,000, 65k, 65000, £80k, $90k, 80.000
    amount_match = re.search(
        r'(?:[€£$]|eur|gbp|usd)?\s*'
        r'(\d{1,3}(?:[.,]\d{3})*(?:\.\d+)?|\d+)\s*'
        r'(k|tsd\.?|thousand)?'
        r'(?:\s*(?:euro|euros|EUR|GBP|USD|CHF|PLN))?'
        r'(?:\s*/?\s*(?:year|yr|p\.a\.|pa|annual|jährlich))?',
        lower
    )
    if amount_match:
        raw = amount_match.group(1).replace(",", "").replace(".", "")
        # Handle European decimal: 65.000 → 65000
        if "." in amount_match.group(1) and amount_match.group(1).count(".") == 1:
            parts = amount_match.group(1).split(".")
            if len(parts[1]) == 3:
                raw = amount_match.group(1).replace(".", "")
        try:
            val = float(raw)
            if amount_match.group(2):  # k / tsd
                val *= 1000
            if val > 0:
                result["gross_annual"] = int(val)
        except ValueError:
            pass

    if not result:
        return {"needs_clarification": True, "question": "Are you employed, self-employed, or freelance? And roughly what's your gross annual income?"}

    return result


def _parse_housing(text: str, lower: str) -> dict:
    result: dict[str, Any] = {}

    # Housing type
    if re.search(r'\b(rent(ing|er)?|miete[rn]?|tenant)\b', lower):
        result["housing_type"] = "rent"
    elif re.search(r'\b(mortgage|hypothek|mortgaged)\b', lower):
        result["housing_type"] = "mortgage"
    elif re.search(r'\b(own(er)?|eigentuemer|eigentümer|bought|freehold)\b', lower):
        result["housing_type"] = "own"

    # Monthly cost
    cost_match = re.search(
        r'(?:[€£$])?\s*(\d{1,3}(?:[.,]\d{3})*|\d+)'
        r'\s*(?:[€£$])?\s*(?:/\s*(?:month|mo|monat))?',
        lower
    )
    if cost_match:
        raw = cost_match.group(1).replace(",", "").replace(".", "")
        if "." in cost_match.group(1):
            parts = cost_match.group(1).split(".")
            if len(parts[1]) == 3:
                raw = cost_match.group(1).replace(".", "")
        try:
            val = int(raw)
            if 100 <= val <= 20000:
                result["monthly_cost"] = val
        except ValueError:
            pass

    # City — common pattern: "in Berlin", "in Munich", "in London"
    city_match = re.search(r'\bin\s+([A-Z][a-zA-Zä-üÄ-Ü\s\-]+?)(?:\s*[,\.€£$\d]|$)', text)
    if city_match:
        city = city_match.group(1).strip().rstrip(",.")
        if len(city) > 1 and city.lower() not in ("a", "the", "an"):
            result["city"] = city

    if not result:
        return {"needs_clarification": True, "question": "Do you rent or own? What's your monthly housing cost?"}

    return result


def _parse_accounts(text: str, lower: str) -> dict:
    result: dict[str, Any] = {}
    accounts = []

    # Common banks and account type keywords
    bank_pattern = re.compile(
        r'\b(dkb|ing|sparkasse|volksbank|commerzbank|deutsche bank|n26|revolut|'
        r'barclays|lloyds|hsbc|natwest|santander|monzo|starling|wise|'
        r'bnp|socgen|crédit agricole|bnp paribas|abn amro|rabobank|'
        r'pkobp|pko|mbank|ing bank)\b',
        re.IGNORECASE
    )
    type_pattern = re.compile(r'\b(checking|current|savings?|depot|brokerage|investment|tagesgeld|girokonto)\b', re.IGNORECASE)

    for bank_match in bank_pattern.finditer(text):
        bank_name = bank_match.group(1)
        start = bank_match.start()
        # Look for account type nearby (within 30 chars before/after)
        context = text[max(0, start - 30):start + 30].lower()
        type_m = type_pattern.search(context)
        acc_type = type_m.group(1).lower() if type_m else "checking"
        # Normalize
        if acc_type in ("current", "girokonto"):
            acc_type = "checking"
        elif acc_type in ("tagesgeld",):
            acc_type = "savings"
        accounts.append({"bank": bank_name, "type": acc_type})

    # Also parse free-form "X checking, Y savings"
    if not accounts:
        free_pattern = re.compile(
            r'([A-Za-z][A-Za-z\s]+?)\s+(checking|current|savings?|depot|brokerage)',
            re.IGNORECASE
        )
        for m in free_pattern.finditer(text):
            bank = m.group(1).strip()
            acc_type = m.group(2).lower()
            if acc_type in ("current",):
                acc_type = "checking"
            if len(bank) <= 40:
                accounts.append({"bank": bank, "type": acc_type})

    if accounts:
        result["accounts"] = accounts
    else:
        # Store raw text as fallback
        result["accounts_raw"] = text

    return result


def _parse_goals(text: str, lower: str) -> dict:
    result: dict[str, Any] = {}
    goals = []

    # Amount: €10k, €3,000, 10000
    amounts = re.findall(
        r'(?:[€£$])?\s*(\d{1,3}(?:[.,]\d{3})*|\d+)\s*(k|tsd\.?)?'
        r'\s*(?:euro|euros|EUR|GBP|USD)?',
        lower
    )
    parsed_amounts = []
    for raw, suffix in amounts:
        raw_clean = raw.replace(",", "").replace(".", "")
        try:
            val = float(raw_clean)
            if suffix:
                val *= 1000
            if val >= 100:
                parsed_amounts.append(int(val))
        except ValueError:
            pass

    # Timeline: "by end of year", "in 8 months", "by Dec 2025"
    timeline_match = re.search(
        r'(?:by\s+(?:end of\s+)?(?:the\s+)?year|'
        r'in\s+(\d+)\s+months?|'
        r'by\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}|'
        r'by\s+\d{4})',
        lower
    )
    timeline = timeline_match.group(0) if timeline_match else None

    # Goal name heuristics
    goal_keywords = re.search(
        r'\b(emergency fund|notgroschen|trip|vacation|urlaub|car|auto|house|'
        r'wedding|hochzeit|education|ausbildung|retirement|rente|laptop|'
        r'investment|anlage)\b',
        lower
    )
    goal_name = goal_keywords.group(1).title() if goal_keywords else "Savings Goal"

    goals.append({
        "name": goal_name,
        "target_amount": parsed_amounts[0] if parsed_amounts else None,
        "timeline": timeline,
        "raw": text,
    })

    result["goals"] = goals
    return result


def _parse_debts(text: str, lower: str) -> dict:
    """Parse debt information from user response."""
    result: dict[str, Any] = {}

    # Check for "no debts" / "debt free" / "skip"
    if re.search(r'\b(no debts?|debt.?free|skip|none|nothing)\b', lower):
        result["no_debts"] = True
        return result

    debts = []

    # Common debt type patterns
    debt_type_map = {
        r'\bcredit\s*card\b': "credit_card",
        r'\bmortgage\b': "mortgage",
        r'\bstudent\s*(?:loan|debt)\b': "student_loan",
        r'\bcar\s*loan\b': "loan",
        r'\boverdraft\b': "overdraft",
        r'\b(?:personal\s*)?loan\b': "loan",
    }

    # Rate patterns: "18%", "at 18", "18 percent"
    def _extract_rate(context: str) -> float | None:
        m = re.search(r'(?:at\s+)?(\d+(?:\.\d+)?)\s*(?:%|percent)', context)
        if m:
            return float(m.group(1)) / 100
        return None

    # Balance patterns: reuse employment amount regex logic
    def _extract_balance(context: str) -> float | None:
        m = re.search(
            r'(?:[€£$])?\s*(\d{1,3}(?:[.,]\d{3})*|\d+)\s*(k|tsd\.?)?',
            context
        )
        if m:
            raw = m.group(1).replace(",", "").replace(".", "")
            if "." in m.group(1):
                parts = m.group(1).split(".")
                if len(parts[1]) == 3:
                    raw = m.group(1).replace(".", "")
            try:
                val = float(raw)
                if m.group(2):
                    val *= 1000
                if val > 0:
                    return val
            except ValueError:
                pass
        return None

    # Try to parse each debt mention
    # Split by commas or "and" to handle multiple debts
    segments = re.split(r',\s*|\s+and\s+', text)

    for segment in segments:
        seg_lower = segment.lower().strip()
        if not seg_lower:
            continue

        debt_type = "other"
        debt_name = None

        for pattern, dtype in debt_type_map.items():
            if re.search(pattern, seg_lower):
                debt_type = dtype
                # Capitalize first match as name
                m = re.search(pattern, seg_lower)
                if m:
                    debt_name = m.group(0).strip().title()
                break

        if debt_name is None and not re.search(r'\d', seg_lower):
            continue  # Skip segments with no debt type and no number

        if debt_name is None:
            # Try to infer a name from the segment
            debt_name = seg_lower.strip().title()[:40]

        balance = _extract_balance(seg_lower)
        rate = _extract_rate(seg_lower)

        if balance or rate:
            debts.append({
                "name": debt_name,
                "balance": balance or 0.0,
                "rate": rate or 0.0,
                "type": debt_type,
            })

    if debts:
        result["debts"] = debts
    elif not result.get("no_debts"):
        # No structured debts found but user didn't say "no debts" — store raw
        result["debts_raw"] = text

    return result


def _parse_investments(text: str, lower: str) -> dict:
    """Parse investment information from user response."""
    result: dict[str, Any] = {}

    # Check for "nothing yet" / "none" / "skip"
    if re.search(r'\b(nothing yet|no investments?|none|skip|not yet|just starting)\b', lower):
        result["no_investments"] = True
        return result

    investments = []

    # Investment type keywords
    type_map = [
        (r'\betf[s]?\b', "etf"),
        (r'\bstock[s]?\b', "stock"),
        (r'\bpension\b', "pension"),
        (r'\bisa\b', "isa"),
        (r'\briester\b', "riester"),
        (r'\br[uü]rup\b', "ruerup"),
        (r'\bcrypto\b', "crypto"),
        (r'\bsavings?\b', "savings"),
        (r'\bindex\s*fund\b', "etf"),
        (r'\bbrokerage\b', "stock"),
    ]

    def _extract_value(context: str) -> float | None:
        m = re.search(
            r'(?:[€£$])?\s*(\d{1,3}(?:[.,]\d{3})*|\d+)\s*(k|tsd\.?)?',
            context
        )
        if m:
            raw = m.group(1).replace(",", "").replace(".", "")
            if "." in m.group(1):
                parts = m.group(1).split(".")
                if len(parts[1]) == 3:
                    raw = m.group(1).replace(".", "")
            try:
                val = float(raw)
                if m.group(2):
                    val *= 1000
                return val
            except ValueError:
                pass
        return None

    # Split by commas, "plus", "and"
    segments = re.split(r',\s*|\s+plus\s+|\s+and\s+', text)

    for segment in segments:
        seg_lower = segment.lower().strip()
        if not seg_lower:
            continue

        inv_type = "other"
        inv_name = segment.strip()

        for pattern, itype in type_map:
            if re.search(pattern, seg_lower):
                inv_type = itype
                # Build name: include "at Provider" if present
                at_match = re.search(r'\bat\s+(\w+)', seg_lower)
                type_match = re.search(pattern, seg_lower)
                if type_match:
                    base = type_match.group(0).upper() if len(type_match.group(0)) <= 4 else type_match.group(0).title()
                    if at_match:
                        inv_name = f"{base} at {at_match.group(1).title()}"
                    else:
                        inv_name = base
                break

        value = _extract_value(seg_lower)

        # Only add if we found a known investment type
        if inv_type != "other" or value:
            investments.append({
                "name": inv_name,
                "value": value or 0.0,
                "type": inv_type,
            })

    if investments:
        result["investments"] = investments
    elif not result.get("no_investments"):
        result["investments_raw"] = text

    return result


def _parse_tax(text: str, lower: str, locale: str) -> dict:
    result: dict[str, Any] = {}

    if locale == "de":
        # Steuerklasse 1–6
        sk_match = re.search(r'(?:klasse|class|steuerklasse)?\s*([1-6])\b', lower)
        if sk_match:
            result["steuerklasse"] = int(sk_match.group(1))
        # Also match "Klasse IV" roman numeral
        sk_roman = re.search(r'klasse\s+(I{1,3}|IV|V|VI)\b', lower, re.IGNORECASE)
        if sk_roman and "steuerklasse" not in result:
            roman_map = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}
            result["steuerklasse"] = roman_map.get(sk_roman.group(1).upper(), 1)

        # Kirchensteuer
        if re.search(r'\b(no|ohne|kein[e]?)\s+kirchensteuer\b', lower):
            result["kirchensteuer"] = False
        elif re.search(r'\bkirchensteuer\b', lower):
            result["kirchensteuer"] = True

        # Bundesland
        bundeslaender = [
            "Berlin", "Bavaria", "Bayern", "Baden-Württemberg", "Brandenburg",
            "Bremen", "Hamburg", "Hessen", "Mecklenburg-Vorpommern",
            "Niedersachsen", "Nordrhein-Westfalen", "NRW", "Rheinland-Pfalz",
            "Saarland", "Sachsen", "Sachsen-Anhalt", "Schleswig-Holstein",
            "Thüringen",
        ]
        for bl in bundeslaender:
            if bl.lower() in lower:
                result["bundesland"] = bl
                break

    elif locale == "uk":
        # Tax code e.g. 1257L
        tax_code_match = re.search(r'\b(\d{3,4}[LMN])\b', text.upper())
        if tax_code_match:
            result["tax_code"] = tax_code_match.group(1)
        # Self assessment
        if re.search(r'\b(no|not|don.t)\s+(do\s+)?self.?assess', lower):
            result["self_assessment"] = False
        elif re.search(r'\bself.?assess', lower):
            result["self_assessment"] = True

    elif locale == "fr":
        # Situation familiale
        if re.search(r'\b(celibataire|célibataire|single)\b', lower):
            result["situation_familiale"] = "celibataire"
        elif re.search(r'\b(mari[ée]|married)\b', lower):
            result["situation_familiale"] = "marie"
        elif re.search(r'\b(pacs[ée]?|civil partnership)\b', lower):
            result["situation_familiale"] = "pacse"
        # Parts
        parts_match = re.search(r'(\d+(?:[.,]\d)?)\s+parts?', lower)
        if parts_match:
            try:
                result["parts_fiscales"] = float(parts_match.group(1).replace(",", "."))
            except ValueError:
                pass

    elif locale == "nl":
        # Box 3 threshold
        if re.search(r'\b(no|nee|not|under|below|beneath)\b', lower):
            result["box3_above_threshold"] = False
        elif re.search(r'\b(yes|ja|above|over)\b', lower):
            result["box3_above_threshold"] = True

    elif locale == "pl":
        # Under 26 (ulga dla młodych)
        age_match = re.search(r'\b(2[0-5])\s+(?:lat|year)', lower)
        if age_match:
            result["under_26"] = int(age_match.group(1)) < 26
        elif re.search(r'\b(tak|yes)\b.*\b26\b|\b26\b.*\b(tak|yes)\b', lower):
            result["under_26"] = True
        elif re.search(r'\b(nie|no)\b', lower):
            result["under_26"] = False

        # Joint filing
        if re.search(r'\b(wspólnie|joint(ly)?|razem)\b', lower):
            result["joint_filing"] = True
        elif re.search(r'\b(samodzielnie|individual|sam|sama)\b', lower):
            result["joint_filing"] = False

    if not result:
        result["tax_raw"] = text

    return result


def _parse_budget(text: str, lower: str) -> dict:
    result: dict[str, Any] = {}

    if re.search(r'\b(yes|yeah|sure|ok|okay|sounds good|go ahead|use it|fine|perfect|great)\b', lower):
        result["budget_method"] = "50-30-20"
        result["confirmed"] = True
    elif re.search(r'\b(custom|adjust|change|different|own|modify)\b', lower):
        result["budget_method"] = "custom"
        result["confirmed"] = False
    elif re.search(r'\b(zero.?based?|zero)\b', lower):
        result["budget_method"] = "zero-based"
        result["confirmed"] = True
    elif re.search(r'\b(envelope)\b', lower):
        result["budget_method"] = "envelope"
        result["confirmed"] = True
    else:
        result["budget_method"] = "50-30-20"
        result["confirmed"] = True

    return result


# ── Step completion ───────────────────────────────────────────────────────────

def complete_step(step: str, data: dict) -> dict:
    """
    Mark step as complete and save the data to the profile.
    Calls profile_manager to update the relevant fields.
    Returns updated onboarding state.
    """
    state = get_onboarding_state()

    # Save step data in state
    state.setdefault("step_data", {})[step] = data
    state.setdefault("started", True)

    if step not in state.get("completed_steps", []):
        state.setdefault("completed_steps", []).append(step)

    # Remove from skipped if previously skipped
    state["skipped_steps"] = [s for s in state.get("skipped_steps", []) if s != step]

    # Persist to profile
    _apply_step_to_profile(step, data)
    _persist_to_engines(step, data)

    save_onboarding_state(state)
    return state


def _persist_to_engines(step: str, data: dict) -> None:
    """Hand wizard answers to the real engines (idempotent by name).

    Before this, accounts/goals/debts/holdings/budget lived only in
    profile.meta.onboarding_* and every engine stayed empty after setup.
    """
    profile = get_profile()
    currency = profile.get("meta", {}).get("primary_currency") or "EUR"

    if step == "accounts":
        from account_manager import add_account, list_accounts
        have = {a.get("name", "").lower() for a in list_accounts()}
        for a in data.get("accounts") or []:
            name = f"{a['bank']} {a['type']}".title()
            if name.lower() in have:
                continue
            kind = a["type"] if a["type"] in ("checking", "savings") else "investment"
            add_account({"name": name, "type": kind, "institution": a["bank"],
                         "currency": currency})
            have.add(name.lower())

    elif step == "goals":
        from goal_tracker import add_goal, get_goals
        have = {g.get("name", "").lower() for g in get_goals()}
        for g in data.get("goals") or []:
            if g["name"].lower() in have or not g.get("target_amount"):
                continue
            add_goal({"name": g["name"], "target_amount": g["target_amount"],
                      "currency": currency})
            have.add(g["name"].lower())

    elif step == "debts":
        from debt_optimizer import add_debt, get_debts
        have = {d.get("name", "").lower() for d in get_debts()}
        for d in data.get("debts") or []:
            if d["name"].lower() in have:
                continue
            add_debt({"name": d["name"], "type": d["type"], "balance": d["balance"],
                      "interest_rate": d["rate"], "currency": currency})
            have.add(d["name"].lower())

    elif step == "investments":
        from investment_tracker import add_holding, get_portfolio
        have = {h.get("name", "").lower() for h in get_portfolio().get("holdings", [])}
        for i in data.get("investments") or []:
            if i["name"].lower() in have:
                continue
            add_holding({"name": i["name"], "type": i["type"],
                         "current_value": i["value"], "cost_basis": i["value"],
                         "currency": currency})
            have.add(i["name"].lower())

    elif step == "budget":
        gross = profile.get("employment", {}).get("annual_gross")
        if gross:
            import datetime
            from budget_engine import create_budget, get_budget
            today = datetime.date.today()
            if not get_budget(today.year, today.month):
                create_budget(today.year, today.month,
                              method=data.get("budget_method", "50-30-20"),
                              income_target=round(gross / 12, 2), currency=currency)


def _apply_step_to_profile(step: str, data: dict) -> None:
    """Write parsed step data into the finance profile."""
    if step == "basics":
        updates: dict[str, Any] = {}
        if data.get("name"):
            updates.setdefault("personal", {})["name"] = data["name"]
        if data.get("country"):
            updates.setdefault("personal", {})["country"] = data["country"]
        if data.get("locale"):
            updates.setdefault("meta", {})["locale"] = data["locale"]
            updates.setdefault("tax_profile", {})["locale"] = data["locale"]
        if data.get("currency"):
            updates.setdefault("meta", {})["primary_currency"] = data["currency"]
        if updates:
            update_profile(updates)

    elif step == "employment":
        updates = {}
        if data.get("employment_type"):
            updates.setdefault("employment", {})["type"] = data["employment_type"]
        if data.get("gross_annual"):
            updates.setdefault("employment", {})["annual_gross"] = data["gross_annual"]
            updates.setdefault("employment", {})["currency"] = "EUR"
        if updates:
            update_profile(updates)

    elif step == "housing":
        updates = {}
        type_map = {"rent": "renter", "own": "owner", "mortgage": "mortgage"}
        if data.get("housing_type"):
            updates.setdefault("housing", {})["type"] = type_map.get(data["housing_type"], data["housing_type"])
        if data.get("monthly_cost"):
            updates.setdefault("housing", {})["monthly_rent_or_mortgage"] = data["monthly_cost"]
        if data.get("city"):
            updates.setdefault("personal", {})["city"] = data["city"]
        if updates:
            update_profile(updates)

    elif step == "goals":
        if data.get("goals"):
            update_profile({"meta": {"onboarding_goals": data["goals"]}})

    elif step == "debts":
        if data.get("no_debts"):
            update_profile({"meta": {"onboarding_no_debts": True}})
        elif data.get("debts"):
            update_profile({"meta": {"onboarding_debts": data["debts"]}})

    elif step == "investments":
        if data.get("no_investments"):
            update_profile({"meta": {"onboarding_no_investments": True}})
        elif data.get("investments"):
            update_profile({"meta": {"onboarding_investments": data["investments"]}})

    elif step == "accounts":
        # Accounts stored in a separate file; for now save as profile note
        if data.get("accounts") or data.get("accounts_raw"):
            update_profile({"meta": {"onboarding_accounts": data.get("accounts") or data.get("accounts_raw")}})

    elif step == "tax":
        updates = {}
        locale = data.get("locale", "de")
        if data.get("steuerklasse"):
            updates.setdefault("tax_profile", {})["tax_class"] = data["steuerklasse"]
            updates.setdefault("employment", {})["type"] = updates.get("employment", {}).get("type")
        if "kirchensteuer" in data:
            updates.setdefault("tax_profile", {})["church_tax"] = data["kirchensteuer"]
        if data.get("bundesland"):
            updates.setdefault("personal", {})["region"] = data["bundesland"]
        # Store locale-specific extras
        extra_keys = ["tax_code", "self_assessment", "situation_familiale", "parts_fiscales",
                      "box3_above_threshold", "under_26", "joint_filing"]
        extra = {k: data[k] for k in extra_keys if k in data}
        if extra:
            updates.setdefault("tax_profile", {})["extra"] = extra
        if updates:
            update_profile(updates)

    elif step == "budget":
        method = data.get("budget_method", "50-30-20")
        update_profile({"preferences": {"budgeting_method": method}})


def skip_step(step: str) -> dict:
    """Mark a step as skipped (user said 'skip'). Can be revisited later."""
    state = get_onboarding_state()
    state.setdefault("started", True)
    if step not in state.get("skipped_steps", []):
        state.setdefault("skipped_steps", []).append(step)
    # Remove from completed if it was there
    state["completed_steps"] = [s for s in state.get("completed_steps", []) if s != step]
    save_onboarding_state(state)
    return state


def reset_onboarding() -> None:
    """Clear onboarding state to restart from step 1."""
    path = _get_state_path()
    if path.exists():
        path.unlink()


# ── Messages ──────────────────────────────────────────────────────────────────

def _progress_bar(completed: list[str], skipped: list[str], total: int = 9) -> str:
    """Render a simple text progress bar."""
    done = set(completed) | set(skipped)
    bar = ""
    for step in STEPS:
        if step in set(completed):
            bar += "█"
        elif step in set(skipped):
            bar += "░"
        else:
            bar += "·"
    pct = int(len(done) / total * 100)
    return f"[{bar}] {pct}%"


def get_resume_message() -> str:
    """
    For returning users mid-onboarding.
    Shows progress and completed steps warmly.
    """
    state = get_onboarding_state()
    completed = state.get("completed_steps", [])
    skipped = state.get("skipped_steps", [])
    current = get_current_step()
    progress = get_step_progress()
    step_num = progress["step_number"]
    total = progress["total_steps"]
    bar = _progress_bar(completed, skipped)

    name_from_profile = get_profile().get("personal", {}).get("name", "")
    if name_from_profile:
        greeting = f"Welcome back, {name_from_profile}!"
    else:
        greeting = "Welcome back!"

    done_count = len(set(completed) | set(skipped))
    header = f"{greeting} We're partway through setup — {done_count} of {total} steps done."
    progress_line = f"Progress: {bar}"

    label = STEP_LABELS.get(current, current.title()) if current != "complete" else "Done"
    step_header = f"You're on Step {step_num} of {total} — {label}."

    step_status = []
    for step in STEPS:
        if step in set(completed):
            step_status.append(f"  ✓ {STEP_LABELS[step]}")
        elif step in set(skipped):
            step_status.append(f"  ~ {STEP_LABELS[step]} (skipped)")
        elif step == current:
            step_status.append(f"  → {STEP_LABELS[step]} ← you are here")
        else:
            step_status.append(f"  ○ {STEP_LABELS[step]}")

    lines = [header, step_header, progress_line, ""] + step_status

    if current != "complete":
        lines += ["", get_step_prompt(current)]

    return "\n".join(lines)


def get_completion_message(profile: dict) -> str:
    """Final message when all steps done. Warm handoff showing what's now possible."""
    name = profile.get("personal", {}).get("name", "")
    greeting = f"You're all set{', ' + name if name else ''}!"

    # Build capability list based on what's in the profile
    capabilities = []
    if profile.get("employment", {}).get("annual_gross"):
        capabilities.append("💰 Tax optimization — I'll run your numbers and find what you're leaving on the table")
    if profile.get("meta", {}).get("onboarding_goals"):
        capabilities.append("🎯 Goal tracking — I'll tell you if you're on pace and what to adjust")
    if profile.get("meta", {}).get("onboarding_debts"):
        capabilities.append("📉 Debt payoff plan — optimal order to clear it fastest")
    if profile.get("meta", {}).get("onboarding_investments"):
        capabilities.append("📈 Portfolio + FIRE timeline — where you are and when you could retire")
    capabilities.append("📊 Budget tracking — I'll flag overspends as they happen")
    capabilities.append("🔔 Daily brief — I'll surface anything worth your attention at the start of each session")

    cap_text = "\n".join(capabilities)

    return (
        f"{greeting} Here's what I can help you with now:\n\n"
        f"{cap_text}\n\n"
        "What do you want to start with? You could say 'show my financial health', "
        "'what's my tax situation', or just ask whatever's on your mind."
    )
