# VHS tape — records a short terminal tour of Finance Assistant's local-first CLI.
# Render with:  vhs assets/demo.tape   →   assets/demo.gif
# Requires: https://github.com/charmbracelet/vhs  (brew install vhs)
#
# NOTE: this shows the CLI utilities (version, demo seed, debt strategy, tax brief).
# The conversational magic (FIRE Monte Carlo chart, tax breakdowns) is best seen
# in the live demo: https://googlarz.github.io/finance-assistant/
# Eyeball the rendered GIF before embedding it in the README.

Output assets/demo.gif

Set FontSize 16
Set Width 1100
Set Height 720
Set Theme "Dracula"
Set TypingSpeed 45ms
Set Padding 20

Type "# Finance Assistant — local-first, runs on your machine"
Enter
Sleep 800ms

Type "python3 skill.py --version"
Enter
Sleep 1.5s

Type "# seed sample data (no real numbers needed to try it)"
Enter
Sleep 500ms
Type "python3 skill.py --demo"
Enter
Sleep 2.5s

Type "# debt payoff: avalanche vs snowball, real interest math"
Enter
Sleep 500ms
Type "python3 skill.py --debt-strategy"
Enter
Sleep 3.5s

Type "# generate an accountant-ready tax filing brief"
Enter
Sleep 500ms
Type "python3 skill.py --tax-brief --year 2025"
Enter
Sleep 3s

Type "# everything stayed on this machine. nothing uploaded."
Enter
Sleep 2s
