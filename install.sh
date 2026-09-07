#!/bin/bash
# Install the resume-claude-sessions skill into ~/.claude/skills/
set -e
SRC="$(cd "$(dirname "$0")" && pwd)/resume-claude-sessions"
DEST="$HOME/.claude/skills/resume-claude-sessions"

[ -d "$SRC" ] || { echo "error: $SRC not found. Run this from the repo root." >&2; exit 1; }

if [ -d "$DEST" ]; then
  echo "$DEST already exists."
  printf "Overwrite it? [y/N] "
  read -r a
  case "$a" in [yY]*) ;; *) echo "aborted."; exit 1;; esac
  rm -rf "$DEST"
fi

mkdir -p "$HOME/.claude/skills"
cp -R "$SRC" "$DEST"
chmod +x "$DEST"/scripts/*.sh "$DEST"/scripts/*.py 2>/dev/null || true

echo "installed to $DEST"
echo "Run /reload-skills in Claude Code, or restart it, to pick up the skill."
