#!/bin/bash
# Usage: dump.sh <outdir> <winid> [winid...]
# Captures each Terminal window's scrollback to <outdir>/w<winid>.txt
set -e
OUT="$1"; shift
[ -z "$OUT" ] && { echo "usage: dump.sh <outdir> <winid>..." >&2; exit 1; }
mkdir -p "$OUT/scroll"
for W in "$@"; do
  osascript -e "tell application \"Terminal\" to get contents of selected tab of (first window whose id is $W)" \
    > "$OUT/scroll/w$W.txt" 2>/dev/null || { echo "w$W: capture failed" >&2; continue; }
  echo "w$W: $(wc -c < "$OUT/scroll/w$W.txt") bytes"
done
