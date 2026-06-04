"""Session-open must not become a wall: immediate alerts are capped and
critical-first (SKILL.md §2: 'pick the 2-3 things that actually matter')."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from financial_monitor import format_monitor_output


def _ctx(immediate):
    return {"immediate": immediate, "digest": [], "last_run": None, "inbox_pending": 0}


def _alert(title, urgency="warning"):
    return {"title": title, "detail": "x", "urgency": urgency}


def test_immediate_capped_at_three_with_overflow_line():
    out = format_monitor_output(_ctx([_alert(f"a{i}") for i in range(6)]))
    # 3 shown, overflow names the rest and points to the escape hatch
    shown = [ln for ln in out.splitlines() if ln.startswith(("[!]", "[~]", "•"))]
    assert len(shown) == 3
    assert "…and 3 more" in out
    assert "show all alerts" in out


def test_no_overflow_line_when_within_cap():
    out = format_monitor_output(_ctx([_alert("only"), _alert("two")]))
    assert "more" not in out.lower()


def test_critical_shown_before_warning_when_capped():
    immediate = [_alert(f"warn{i}", "warning") for i in range(3)] + [_alert("CRIT", "critical")]
    out = format_monitor_output(_ctx(immediate))
    # The critical one must survive the cap even though it was added last
    assert "CRIT" in out
