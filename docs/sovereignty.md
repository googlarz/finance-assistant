# Sovereignty Mode — zero data to Anthropic

By default Claude Code sends your prompts and file context to Anthropic's API. Your **data on disk** never leaves your machine, but the **conversation** does. For confidential client data, an employer's EU-sovereignty policy, or pure preference, you can route Claude Code through a local model so **nothing leaves your machine**.

> **The honest tradeoff up front:** open local models are meaningfully weaker than Claude at multi-step tax reasoning and "which rule applies" judgment. The deterministic tax math (`locales/<code>/tax_calculator.py`) runs identically regardless of model — but *interpreting your situation* degrades. Don't use this mode for tax-accuracy-critical decisions without verifying. The `sovereignty_check.py` harness below lets you measure the gap yourself.
>
> **Two things degrade, one doesn't.** The **numbers** are safe — they come from Python, not the model. What you lose is (1) **reasoning** — picking the right rule for a messy situation — and (2) **voice** — the warmth, the judgment calls, the "I'd go with avalanche" opinions that make this feel like a conversation rather than a calculator. The skill instructs a local model to compensate by leaning harder on the scripts and keeping answers short and plain, but expect a more clipped, less fluent assistant. If the *experience* matters more to you than zero-egress, stay on the default Claude path.

## Setup

### 1. Install Ollama and pull a model

```bash
# https://ollama.com
ollama pull llama3.3:70b      # best at this size; needs ~40GB RAM/VRAM
# smaller options:
# ollama pull qwen2.5:32b     # ~24GB, decent
# ollama pull llama3.1:8b     # fast, noticeably weaker — baseline only
```

Bigger models reason better about taxes. `llama3.1:8b` will run on a laptop but makes more mistakes; a 70B model on a workstation/GPU is much closer to usable.

### 2. Install claude-code-router

```bash
npm install -g @musistudio/claude-code-router
```

### 3. Point the router at Ollama

Follow the [claude-code-router README](https://github.com/musistudio/claude-code-router) to configure a provider targeting `http://localhost:11434` (Ollama's default). Then launch Claude Code through the router instead of directly.

## Verify the tradeoff before you trust it

Don't take this doc's word for the accuracy hit — measure it on your hardware:

```bash
ollama serve &                                   # if not already running
python3 scripts/sovereignty_check.py --model llama3.3:70b
```

The harness computes ground-truth tax numbers from the deterministic engine, then asks your local model to reason through the same case **unaided** (no tool call). It prints the delta:

```
── DE 2025, single, €60,000 gross
   ground truth (engine): €13,924.20
   local model (unaided): €13,100.00   ~ off (6% from truth)
```

A small gap means the local model reasons well and you're mostly relying on it correctly driving the skill's tools. A large gap means you're leaning heavily on the deterministic tools — fine for pure calculation, risky for judgment calls.

List recommended models:

```bash
python3 scripts/sovereignty_check.py --list-models
```

## When to use which path

| Situation | Use |
|-----------|-----|
| Your own personal finances | **Default Claude path** — best quality; your data already stays on disk, only the conversation egresses |
| Confidential client/employer data, sovereignty policy | **Sovereignty mode** — accept the quality hit for zero egress |
| Tax-accuracy-critical filing decision | **Default Claude path**, then confirm with a professional (`--tax-brief`) regardless of mode |

> **Not pre-validated.** This recipe is provided as-is. Local-model accuracy depends entirely on your hardware and model choice — run the harness, don't assume.
