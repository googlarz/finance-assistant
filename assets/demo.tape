# VHS tape — short terminal tour of Finance Assistant's local-first CLI.
# Render with:  vhs assets/demo.tape   →   assets/demo.gif
# Requires: https://github.com/charmbracelet/vhs  (brew install vhs)
#
# The conversational magic (FIRE Monte Carlo chart, tax breakdowns) is best seen
# in the LIVE DEMO: https://googlarz.github.io/finance-assistant/  — a terminal
# GIF can only show the CLI utilities. Eyeball the rendered GIF before embedding.

Output assets/demo.gif

Set FontSize 16
Set Width 1100
Set Height 700
Set Theme "Dracula"
Set TypingSpeed 45ms
Set Padding 20

# ── Setup (hidden): isolate state in a temp dir + seed sample data quietly ──
Hide
Type "export FINANCE_PROJECT_DIR=$(mktemp -d)" Enter
Type "python3 skill.py --demo >/dev/null 2>&1" Enter
Type "clear" Enter
Show

# ── Visible tour ──
Type "# Finance Assistant — local-first. Runs on your machine, no cloud."
Enter
Sleep 800ms

Type "python3 skill.py --version"
Enter
Sleep 1.5s

Type "# generate an accountant-ready tax filing brief from your data"
Enter
Sleep 400ms
Type "python3 skill.py --tax-brief --year 2025"
Enter
Sleep 2s

Type "# ...and read it — computed tax, the statute applied, a doc checklist"
Enter
Sleep 400ms
Type "sed -n '1,22p' $FINANCE_PROJECT_DIR/.finance/workspace/tax_brief_de_2025.md"
Enter
Sleep 3.5s

Type "# every number above is deterministic Python, not a model guessing."
Enter
Sleep 2s

Hide
Type "rm -rf $FINANCE_PROJECT_DIR" Enter
Show
