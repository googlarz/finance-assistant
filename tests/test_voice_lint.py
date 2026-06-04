"""On-voice guard: the deterministic, code-generated text that gets shown to
users must not contain the robotic phrases SKILL.md §2 explicitly bans.

The model's prose can't be linted here — but the code's own string literals
can, and that's exactly the surface where "robotic code-strings win by
default" (the session monitor, alerts, onboarding). This test keeps that
surface honest so the data layer can't quietly drift off-voice.

Scans string *literals* via AST (not comments, not docstrings), so explanatory
prose in comments/docstrings never trips it.
"""
import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"

# User-facing text emitters. Add a module here when it prints/returns text
# the user actually reads at session time.
USER_FACING_FILES = [
    SCRIPTS / "financial_monitor.py",
    SCRIPTS / "session_alerts.py",
    SCRIPTS / "onboarding.py",
    SCRIPTS / "data_coach.py",
    PROJECT_ROOT / "skill.py",
]

# From SKILL.md §2 "Never say" + the robotic bad-example patterns. Lowercased.
BANNED = [
    "analysis complete",
    "task executed",
    "data retrieved",
    "processing...",
    "confidence: low",
    "confidence: medium",
    "confidence: high",
    "certainly!",
    "of course!",
    "great question!",
]


def _string_literals(path: Path):
    """Yield (lineno, value) for every string literal that is NOT a docstring."""
    tree = ast.parse(path.read_text(), filename=str(path))
    docstring_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docstring_nodes.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstring_nodes:
                yield node.lineno, node.value


@pytest.mark.parametrize("path", USER_FACING_FILES, ids=lambda p: p.name)
def test_no_robotic_phrases_in_user_facing_strings(path):
    offenders = []
    for lineno, value in _string_literals(path):
        low = value.lower()
        for phrase in BANNED:
            if phrase in low:
                offenders.append(f"{path.name}:{lineno} contains banned phrase {phrase!r}")
    assert not offenders, (
        "Robotic phrasing leaked into user-facing output (SKILL.md §2):\n"
        + "\n".join(offenders)
    )


def test_lint_actually_catches_a_violation():
    """Guard the guard — prove the matcher would fire on a real offender."""
    sample = 'print("Analysis complete. Confidence: medium.")'
    tree = ast.parse(sample)
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    hits = [p for p in BANNED if any(p in s.lower() for s in literals)]
    assert "analysis complete" in hits and "confidence: medium" in hits
