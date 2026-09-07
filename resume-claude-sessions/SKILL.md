---
name: resume-claude-sessions
description: "Recover Claude Code sessions after a crash, battery death, or reboot. Identifies which sessions were open, matches them back to the Terminal windows they were running in, and resumes them in bulk. Use when someone has many dead Terminal windows sitting at a shell prompt after Claude Code exited, or wants to bulk-resume prior sessions into fresh windows."
allowed-tools:
  - Read
  - Write
  - Bash
  - Grep
  - Glob
  - AskUserQuestion
---

# Resume Claude Code sessions in bulk

Recovers many Claude Code sessions at once after the app dies (battery, crash,
reboot) while the Terminal windows stay open. Two modes:

- **reattach**: the original windows are still open. Fingerprint each window's
  scrollback, match it to its transcript, and resume that session *in that same
  window*. Preserves the window layout and the scrollback the user can read.
- **fresh**: the windows are gone. Pick the sessions worth resuming and open a
  new window per session.

Prefer **reattach** when the windows still exist. Opening new windows instead
leaves the user with two sets of windows and loses the visible history.

## Why matching is needed at all

"Just resume everything" does not work. A machine accumulates far more
transcripts than were actually open (35 on disk vs 20 open, in the case this
skill was built from). Recency does not separate them either: idle sessions get
their metadata rewritten at shutdown, so file mtime can be hours newer than the
last real message. The only reliable signal for *which sessions were open* is
the text sitting in each window.

## Requirements

- macOS, Terminal.app, and AppleScript permission for the controlling process.
- Transcripts under `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`.

## Procedure

### 1. Survey

```bash
scripts/survey.sh
```

Lists every Terminal window with its id, tty, and running processes. A window
whose processes are only `login, -zsh` is dead and a candidate. Skip the window
running the current Claude session.

### 2. Dump scrollbacks and match

```bash
scripts/dump.sh <outdir> <winid>...       # capture each window's scrollback
python3 scripts/match.py <outdir>         # index transcripts, match, report
```

`match.py` writes `plan.json` (window to session id, startup cwd, model) and
prints a table with a confidence column. It works in two stages:

**Fast path first.** A clean `/exit` prints `Resume this session with: claude
--resume <id>` into the window. When that line is present the id is read straight
out of the scrollback, but it is **corroborated, not trusted**: only that one
transcript is read and scored against the window, and the claim is accepted as
`EXACT` only if at least `CLAIM_MIN` (15%) of the window's text is actually in
it. Everything falls back to scrollback matching:

| Situation | What happens |
|---|---|
| No id printed (crash, battery kill, `kill -9`) | Full fingerprinting |
| Id printed, transcript pruned off disk | Reported, then full fingerprinting |
| Id printed but wrong (stale, forked, resumed twice) | Claim rejected, next claimed id tried, then full fingerprinting |
| Id printed and corroborated | `EXACT`, no further scanning |

A window that named the wrong session scored 2.8% and was rejected; correct
claims scored 19% to 86%.

**Then fingerprinting**, for every window the fast path could not resolve. It:

- indexes every transcript (title, startup cwd, model, last message)
- scores window text against transcript text using 8-word shingles
- **excludes the current session's own transcript**, which contains the scrollback
  you just dumped into it, and will otherwise win every match (auto-detected from
  `$CLAUDE_CODE_SESSION_ID`; add more with `--exclude <id>`)
- **auto-excludes rescue transcripts**: any transcript that is the top hit for 3
  or more windows is a previous rescue session that quoted those windows into
  its own transcript, not a real match
- flags windows whose *last visible message* differs from the session's *last*
  message

Review the table before acting. Anything below high confidence, or flagged, gets
resolved by hand (see Ambiguity below).

### 3. Resume

```bash
scripts/resume.sh <outdir> <winid>...     # reattach mode
scripts/resume.sh --new <outdir> <winid>... # fresh windows instead
```

Per window it sends `cd '<startup cwd>' && claude --resume <id>`, answers the
"resume from summary vs full" prompt, and verifies the session came up live.

Ask the user which resume mode they want **before** running it: full-as-is on a
dozen 300k+ token sessions consumes a real chunk of usage limits, and it is
their call, not yours. Edit `RESUME_CHOICE` at the top of `resume.sh` (`2` =
full as-is, `1` = from summary).

## Gotchas (all of these were hit for real)

**The `cd` is mandatory.** Restored shells start in `~`, not the project
directory. Claude Code looks up a session id inside the project directory keyed
to the *current* cwd, so `claude --resume <id>` from the wrong directory will
not find the session. It silently starts a new session and, in an untrusted
directory, stops on a "trust this folder" prompt. Always take the startup cwd
from the **first** `cwd` field in the transcript, not the last: a session that
`cd`s mid-conversation still belongs to the project directory it started in.

**Never detect state by grepping the whole scrollback.** The buffer still holds
the *old* status bar from before the crash, including `bypass permissions on
(shift+tab to cycle)`. Grepping the whole buffer reports "loaded" instantly and
you will walk away leaving every window parked on an unanswered prompt. Detect
with the tab's process list (is `claude` running?) plus the last ~12 non-blank
lines only.

**Old or large sessions interrupt startup** with `1. Resume from summary /
2. Resume full session as-is / 3. Don't ask me again`. There is no CLI flag for
this; it must be answered per window. `do script "2"` writes into the running
process and selects it.

**The title in the divider is not the `aiTitle`.** Windows show a custom title
that does not appear in the transcript. Match on conversation text, not titles.

**A 0% last-message match does not always mean stale.** A session that was
`/compact`ed right before dying ends with `No response requested.` as its last
assistant message. Confirm with a distinctive tool call or file path instead.

**Genuinely stale windows exist.** A window restored more than once (grep the
buffer for `[Restored `) died in an *earlier* incident and may be showing an old
point of a session that is already live in another window. Never resume the same
session id in two windows, because that is two processes writing one transcript. Leave the
stale window alone and tell the user.

**Some transcripts are gone.** Project directories can hold zero `.jsonl` files.
If no phrase from a window appears in any transcript, that session is
unrecoverable. Say so plainly rather than resuming the closest match.

**Markdown breaks exact-phrase verification.** Rendered scrollback text differs
from the raw transcript (`**bold**`, list markers). Exact grep will miss; the
shingle score is the primary signal and grep is only corroboration.

**The self-exclusion env var is `CLAUDE_CODE_SESSION_ID`.** Not
`CLAUDE_SESSION_ID`. Getting it wrong fails silently: the matcher simply never
excludes itself, and then wins its own matches.

**A previous rescue's transcript poisons the next run.** Once a session has
dumped 20 windows' scrollback into its own transcript, it contains verbatim text
from every one of them and outscores the real sessions. Excluding only "self" is
not enough once you have done this more than once.

**Do not apply the staleness heuristic to an id-confirmed window.** A cleanly
exited window ends with exit output rather than its last message, so `endmatch`
reads near zero even on a perfect match and every window gets falsely flagged
for review. That check exists only to catch a *fingerprint* landing on a session
whose current end the window is not showing.

**Pilot one window first.** Run a single low-stakes window end to end and
confirm it comes up live before touching the other twenty.

## Ambiguity

For a window that is unclear, in order of strength:

1. Grep a distinctive plain-prose phrase (no markdown) from the window across
   all transcripts.
2. Compare the window's last visible assistant message to each candidate's last
   message.
3. Compare the status bar's cwd and model against the transcript's.

If it stays ambiguous, present the candidates to the user with
`AskUserQuestion`. Do not guess: resuming the wrong session in a window is
confusing and can collide with a session live elsewhere.
