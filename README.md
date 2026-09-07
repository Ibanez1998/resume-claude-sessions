# resume-claude-sessions

A [Claude Code](https://claude.com/claude-code) skill that brings your sessions
back after Claude Code dies but your Terminal windows survive: a battery death,
a crash, a force quit, a reboot.

If you had twenty terminals running Claude Code and they are all sitting at a
shell prompt now, this figures out which session each window was running and
resumes it in that same window.

## The problem

You can already recover one session by hand: `cd` to the project, run `claude`,
type `/resume`, and hunt for the right conversation in the list. That is fine
once. At twenty windows it is an hour of squinting at nearly identical entries.

The obvious shortcut, "just resume the most recent N sessions", does not work:

- You have far more transcripts on disk than were actually open. On the machine
  this was built for: 35 transcripts, 20 open windows.
- Recency does not separate them. Idle sessions get their metadata rewritten at
  shutdown, so a transcript's file mtime can be hours newer than its last real
  message.

The only trustworthy signal for *which* sessions were open is the text still
sitting in each terminal window. So that is what this matches on.

## How it works

1. **Survey.** Enumerate Terminal windows via AppleScript. A window whose only
   processes are `login, -zsh` is dead and a candidate.
2. **Fingerprint.** Capture each window's scrollback and score it against every
   transcript in `~/.claude/projects/` using 8-word shingle overlap. The winner
   is normally 70 to 95 percent overlap with a near-zero runner-up.
3. **Sanity-check.** Compare each window's last visible message to that
   session's last message. A mismatch means the window is showing an older point
   of the conversation, which usually means it died in an earlier incident and
   may already be live in another window.
4. **Resume.** Send `cd '<project dir>' && claude --resume <id>` into that same
   window, answer Claude Code's "resume from summary or full" prompt, and verify
   the session actually came up live.

## Install

```bash
git clone https://github.com/Ibanez1998/resume-claude-sessions.git
cd resume-claude-sessions
./install.sh
```

`install.sh` copies the skill to `~/.claude/skills/resume-claude-sessions`.
Restart Claude Code, or run `/reload-skills`, and it will be available.

To install by hand, copy the `resume-claude-sessions/` directory into
`~/.claude/skills/`.

## Use

Just say what happened:

> My laptop died and I have 20 Terminal windows sitting at a prompt. Can you
> match each one to its Claude session and resume them?

Claude picks up the skill and walks the procedure. It will show you the match
table before resuming anything, and it will ask whether you want full context or
summaries, because resuming a dozen 300k-token sessions at full fidelity uses a
real chunk of your usage limits.

You can also run the scripts directly:

```bash
resume-claude-sessions/scripts/survey.sh
resume-claude-sessions/scripts/dump.sh /tmp/rescue 110 111 112
python3 resume-claude-sessions/scripts/match.py /tmp/rescue
resume-claude-sessions/scripts/resume.sh /tmp/rescue
```

Add `--new` to `resume.sh` to open a fresh window per session instead of
reattaching, for when the original windows are gone.

## What it will not do

- **Resume the same session in two windows.** That means two processes writing
  one transcript. When two windows match one session it keeps the one showing
  the current end of the conversation and quarantines the other for you to look
  at.
- **Guess on a weak match.** Low-confidence and flagged windows are reported,
  not resumed.
- **Invent a session that is gone.** Transcripts do get pruned. If nothing in a
  window appears in any transcript, it says so instead of resuming the closest
  thing.

## Requirements

- macOS with Terminal.app. iTerm2 is not supported yet.
- The controlling process needs AppleScript permission for Terminal. macOS
  prompts for this the first time under System Settings, Privacy and Security,
  Automation.
- Claude Code transcripts in the default location,
  `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`.

## Notes for anyone adapting this

The hard-won details are written up in the Gotchas section of
[`SKILL.md`](resume-claude-sessions/SKILL.md). The three that cost the most time:

- **The `cd` is mandatory.** Claude Code resolves a session id relative to the
  current directory, so `claude --resume <id>` from the wrong place silently
  starts a new session instead. Use the *first* `cwd` recorded in the transcript,
  not the last, since a session that changes directory mid-conversation still
  belongs to the project directory it started in.
- **Do not detect readiness by grepping the whole scrollback.** The buffer still
  contains the pre-crash status bar, so a naive grep reports "loaded" instantly
  and leaves every window parked on an unanswered prompt. Check the tab's
  process list plus the last few non-blank lines.
- **Count distinct shingle matches, not per-chunk hits.** Summing across
  overlapping read chunks double-counts and produced a 163 percent match that
  assigned a window to the wrong session.

## License

MIT. See [LICENSE](LICENSE).
