#!/bin/bash
# List Terminal windows with id, tty and running processes.
# Windows whose processes are only "login, -zsh" are dead and resumable.
osascript <<'EOF'
tell application "Terminal"
  set out to ""
  repeat with w in windows
    set wid to id of w
    repeat with t in tabs of w
      set out to out & "winid=" & wid & "  tty=" & (tty of t) & "  procs=" & (processes of t as string) & linefeed
    end repeat
  end repeat
  return out
end tell
EOF
