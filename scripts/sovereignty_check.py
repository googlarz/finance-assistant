"""
Sovereignty mode accuracy harness.

Finance Assistant can run through a local model (Ollama via claude-code-router)
so no prompts reach Anthropic — see docs/sovereignty.md. The tradeoff is answer
quality: open local models are weaker at tax reasoning.

This harness lets you SEE that tradeoff on your own machine instead of taking
the docs' word for it. It:

  1. Computes ground-truth tax numbers from the deterministic Python engine
     (these are model-independent — the same whether Claude or a local model
     drives the skill).
  2. Asks your local Ollama model to reason through the SAME case UNAIDED
     (no tool call — pure model reasoning), which is exactly the capability
     that degrades in sovereignty mode.
  3. Prints the delta so you can decide whether the local model is good enough
     for your use.

Run it yourself — it needs Ollama running locally:
    ollama serve &                 # if not already running
    ollama pull llama3.3:70b
    python3 scripts/sovereignty_check.py --model llama3.3:70b

This is NOT run in CI and has NOT been pre-validated by the skill author —
local-model accuracy depends entirely on your hardware and model choice.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"

# Recommended models in rough capability order (largest first). Bigger = better
# tax reasoning but needs more VRAM.
RECOMMENDED_MODELS = [
    "llama3.3:70b",       # best general reasoning at this size
    "qwen2.5:72b",        # strong on structured/numeric tasks
    "deepseek-r1:70b",    # reasoning-tuned
    "qwen2.5:32b",        # fits 24GB VRAM, decent
    "llama3.1:8b",        # fast, noticeably weaker — baseline only
]


def _ground_truth_cases() -> list[dict]:
    """Compute model-independent ground-truth tax numbers from the engine."""
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    from tax_engine import calculate_tax_estimate

    cases = [
        {
            "label": "DE 2025, single, €60,000 gross",
            "profile": {
                "meta": {"locale": "de", "tax_year": 2025},
                "tax_profile": {"locale": "de", "filing_status": "single"},
                "employment": {"annual_gross": 60000},
                "income": 60000,
            },
            "year": 2025,
            "question": (
                "A single person in Germany earns €60,000 gross salary in 2025. "
                "Estimate their income tax (Einkommensteuer) for the year in euros. "
                "Reply with ONLY the number, no currency symbol, no explanation."
            ),
        },
    ]
    for c in cases:
        est = calculate_tax_estimate(c["profile"], c["year"])
        breakdown = est.get("breakdown", {})
        c["truth"] = breakdown.get("estimated_tax") or est.get("tax") or 0
    return cases


def _ask_ollama(model: str, prompt: str, timeout: int = 120) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data.get("response", "")


def _extract_number(text: str) -> float | None:
    """Pull the first number out of a model response."""
    cleaned = text.replace(",", "").replace("€", "").replace("$", "")
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(m.group()) if m else None


def run(model: str) -> int:
    print(f"Sovereignty accuracy check — model: {model}\n")
    print("Ground truth = deterministic Python engine (model-independent).")
    print("Local answer = your Ollama model reasoning UNAIDED (no tool call).\n")

    try:
        cases = _ground_truth_cases()
    except Exception as exc:
        print(f"Could not compute ground truth: {exc}", file=sys.stderr)
        return 1

    any_ok = False
    for c in cases:
        truth = float(c["truth"])
        print(f"── {c['label']}")
        print(f"   ground truth (engine): €{truth:,.2f}")
        try:
            raw = _ask_ollama(model, c["question"])
            guess = _extract_number(raw)
        except urllib.error.URLError:
            print("   ⚠ Ollama not reachable at localhost:11434.")
            print("     Start it with `ollama serve &` and pull the model, then re-run.")
            return 2
        except Exception as exc:
            print(f"   ⚠ model call failed: {exc}")
            continue

        any_ok = True
        if guess is None:
            print(f"   local model: could not parse a number from: {raw[:80]!r}")
            continue
        delta = guess - truth
        pct = (abs(delta) / truth * 100) if truth else 0
        verdict = "✓ close" if pct <= 5 else ("~ off" if pct <= 20 else "✗ way off")
        print(f"   local model (unaided): €{guess:,.2f}   {verdict} ({pct:.0f}% from truth)")
        print()

    if any_ok:
        print("Interpretation: the wider the gap, the more you're relying on the skill's")
        print("deterministic tools rather than the model's own reasoning. For tax-accuracy-")
        print("critical work, prefer the default Claude path (see README).")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare local-model tax reasoning vs the deterministic engine.")
    parser.add_argument("--model", default="llama3.3:70b", help="Ollama model tag (default: llama3.3:70b)")
    parser.add_argument("--list-models", action="store_true", help="Print recommended models and exit")
    args = parser.parse_args()
    if args.list_models:
        print("Recommended Ollama models (largest/best first):")
        for m in RECOMMENDED_MODELS:
            print(f"  {m}")
        return
    sys.exit(run(args.model))


if __name__ == "__main__":
    main()
