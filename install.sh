#!/usr/bin/env bash
# One-command install: clone (or update) into ~/.claude/skills, install deps, run the health check.
#   curl -fsSL https://raw.githubusercontent.com/googlarz/finance-assistant/main/install.sh | bash
set -euo pipefail

DEST="${FINANCE_ASSISTANT_DIR:-$HOME/.claude/skills/finance-assistant}"
REPO="${FINANCE_ASSISTANT_REPO:-https://github.com/googlarz/finance-assistant.git}"

command -v git >/dev/null || { echo "git is required" >&2; exit 1; }
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
  || { echo "Python 3.9+ is required (found: $("$PY" --version 2>&1))" >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || echo "Note: $("$PY" --version 2>&1) is fine for the skill; the optional MCP server needs Python 3.10+."

if [ -d "$DEST/.git" ]; then
  echo "Updating $DEST"
  git -C "$DEST" pull --ff-only
  git -C "$DEST" submodule update --init --recursive
else
  echo "Installing to $DEST"
  mkdir -p "$(dirname "$DEST")"
  git clone --recurse-submodules "$REPO" "$DEST"
fi

"$PY" -m pip install --quiet -r "$DEST/requirements.txt"
echo
"$PY" "$DEST/skill.py" --doctor || { echo "Doctor reported problems — see above." >&2; exit 1; }
echo
echo 'Done. Start a new Claude Code session and ask: "What is my financial health?"'
