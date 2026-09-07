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
2. **Read the id if it is there.** A clean `/exit` prints `Resume this session
   with: claude --resume <id>` into the window. When that line is present the id
   is taken straight from it and reported as `EXACT`, with no scanning at all.
3. **Otherwise fingerprint.** A crash or battery kill never prints that line, so
   for those windows the scrollback is scored against every transcript in
   `~/.claude/projects/` using 8-word shingle overlap. The winner is normally 70
   to 95 percent overlap with a near-zero runner-up.
4. **Sanity-check.** Compare each window's last visible message to that
   session's last message. A mismatch means the window is showing an older point
   of the conversation, which usually means it died in an earlier incident and
   may already be live in another window.
5. **Resume.** Send `cd '<project dir>' && claude --resume <id>` into that same
   window, answer Claude Code's "resume from summary or full" prompt, and verify
   the session actually came up live.

## What it does to your machine, before you run it

This drives Terminal.app through AppleScript. Concretely, it will:

- **read the scrollback** of the Terminal windows you point it at, and write
  copies into the output directory you name
- **type a command into those windows and press return**, specifically
  `cd '<project dir>' && claude --resume <id>`
- **send a single keystroke** to answer Claude Code's resume prompt

It does not read or transmit anything outside your machine, and it makes no
network calls of its own. But it is a downloaded script that types into your
terminals, so read `scripts/resume.sh` before you trust it. It only ever touches
window ids you pass on the command line.

Nothing is destructive: the worst realistic outcome is a window that opens the
wrong conversation, which you undo with `/exit` and one rerun.

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

### Running the scripts directly

**1. Find the dead windows.** A window whose processes are only `login, -zsh`
has no Claude running and is a candidate. Skip the window you are working in.

```
$ scripts/survey.sh
winid=675  tty=/dev/ttys021  procs=login-zshclaudenode      <- your live session, skip
winid=110  tty=/dev/ttys001  procs=login-zsh                <- dead, recover this
winid=111  tty=/dev/ttys002  procs=login-zsh                <- dead, recover this
winid=112  tty=/dev/ttys003  procs=login-zsh                <- dead, recover this
```

**2. Capture and match.** Pass the dead window ids from step 1:

```
$ scripts/dump.sh /tmp/rescue 110 111 112
w110: 6199 bytes
w111: 7826 bytes
w112: 7740 bytes

$ python3 scripts/match.py /tmp/rescue
3 windows vs 35 transcripts (excluding 009eaac1)
w110 -> 9ad9a799  EXACT (session id printed in window)  Onboard the new client account
w111 -> 74784e7d  HIGH overlap= 91.9% end= 91.1%  Site redesign approved
w112 -> 0a041851  LOW  overlap= 76.1% end=  0.0%  Scorecard landing page  [STALE? window
                                                  may show an older point]  [restored 2x]

!! review before resuming: ['112']
wrote /tmp/rescue/plan.json
```

Read that table before going further. `overlap` is how much of the window's text
was found in that transcript. `end` is whether the window shows the session's
*current* end, so a low `end` means the window is showing an older point and
probably died in an earlier incident. Anything `LOW` or flagged is skipped by
default.

**3. Resume.** With no window ids it does every window in the plan that is not
flagged:

```
$ scripts/resume.sh /tmp/rescue
  skipping w112 (0a041851) - flagged stale/duplicate
w110 launched
w111 launched
w110 answered resume prompt
w111 answered resume prompt
w110 LIVE 9ad9a799  Onboard the new client account
w111 LIVE 74784e7d  Site redesign approved
all windows live
```

Add `--new` to open a fresh window per session instead of reattaching, for when
the original windows are gone:

```bash
scripts/resume.sh --new /tmp/rescue
```

In `--new` mode you answer each window's resume prompt yourself.

**Choosing full context or summaries.** Claude Code interrupts startup on old or
large sessions to ask whether to resume the full conversation or a summary.
`resume.sh` answers it for you, using `RESUME_CHOICE` at the top of the script:
`2` for full as-is (the default), `1` for summary. Full fidelity across a dozen
300k-token sessions uses a real chunk of your usage limits, so change it to `1`
if that matters more to you than perfect recall.

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

## Requirements and limits

- macOS with Terminal.app. iTerm2 is not supported yet.
- The controlling process needs AppleScript permission for Terminal. macOS
  prompts for this the first time under System Settings, Privacy and Security,
  Automation.
- Claude Code transcripts in the default location,
  `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`.
- **One tab per window.** `survey.sh` lists every tab, but `dump.sh` and
  `resume.sh` act on each window's *selected* tab only. If you keep several
  Claude sessions as tabs inside one window, only the frontmost tab of that
  window is handled. This path is untested; the case it was built from had
  exactly one tab per window.
- Matching needs readable text in the window. If Terminal's scrollback limit has
  already discarded the conversation, or the window was cleared, there is
  nothing left to fingerprint.

## Troubleshooting

**"Terminal got an error: Application isn't running" or every command returns
nothing.** AppleScript permission was denied. Grant it under System Settings,
Privacy and Security, Automation, and enable Terminal for whichever app is
driving the scripts.

**A window stops on "Is this a project you created or one you trust?"** Claude
launched in the wrong directory, which also means it did not find the session.
Check the `cwd` recorded for that window in `plan.json`. Press return to pick
"No, exit" and rerun.

**A window sits on the resume prompt and nothing happens.** `resume.sh` polls
for up to 30 minutes and reports `NEEDS ATTENTION` for any window it could not
settle. Answer that window by hand with `1` or `2`.

**It resumed the wrong conversation.** Type `/exit` in that window, then rerun
`resume.sh` for just that window id after correcting its entry in `plan.json`.
Nothing is lost: resuming does not modify a transcript beyond appending, and the
session you wanted is still on disk.

**A window matched nothing.** Its transcript is probably gone. Claude Code
prunes old sessions, and project directories can end up holding zero `.jsonl`
files. That session is not recoverable.

**How do I confirm it really worked?** For each window, check that `claude` is
in the tab's process list and that the session's transcript file has a fresh
mtime. A new mtime is the real proof that the intended session loaded, rather
than just that some process started.

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
