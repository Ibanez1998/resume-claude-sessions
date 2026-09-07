#!/bin/bash
# Usage: resume.sh [--new] <outdir> [winid...]
#
#   reattach (default) : resume each session in the window it came from
#   --new              : open a fresh Terminal window per session instead
#
# Reads <outdir>/plan.json produced by match.py. With no winids, does every
# window in the plan that is not flagged stale.
#
# RESUME_CHOICE answers Claude Code's startup prompt on old/large sessions:
#   2 = resume full session as-is   1 = resume from summary
# Ask the user which they want first: full-as-is across many large sessions
# consumes a substantial chunk of usage limits.
RESUME_CHOICE=2

set -u
NEW=0
[ "${1:-}" = "--new" ] && { NEW=1; shift; }
OUT="${1:-}"; shift || true
[ -z "$OUT" ] && { echo "usage: resume.sh [--new] <outdir> [winid...]" >&2; exit 1; }
PLAN="$OUT/plan.json"

field() { python3 -c "import json;print(json.load(open('$PLAN'))['$1']['$2'])"; }

if [ "$#" -gt 0 ]; then WINS="$*"; else
  WINS=$(python3 -c "
import json
p=json.load(open('$PLAN'))
print(' '.join(w for w,d in p.items() if not d.get('stale')))")
fi

python3 - "$PLAN" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
for w,d in p.items():
    if d.get('stale'): print(f"  skipping w{w} ({d['sid'][:8]}) - flagged stale/duplicate")
PY

exec python3 - "$PLAN" "$NEW" "$RESUME_CHOICE" $WINS <<'PY'
import subprocess, json, sys, time
plan=json.load(open(sys.argv[1])); new=sys.argv[2]=='1'; choice=sys.argv[3]
wins=sys.argv[4:]

def osa(s):
    try: return subprocess.run(['osascript','-e',s],capture_output=True,text=True,timeout=20).stdout
    except Exception: return ''
def procs(w): return osa(f'tell application "Terminal" to get processes of selected tab of (first window whose id is {w})')
def tail(w,n=12):
    t=osa(f'tell application "Terminal" to get contents of selected tab of (first window whose id is {w})')
    return '\n'.join([l for l in t.split('\n') if l.strip()][-n:])
def esc(c): return c.replace('\\','\\\\').replace('"','\\"')
def send(w,c): osa(f'tell application "Terminal" to do script "{esc(c)}" in selected tab of (first window whose id is {w})')
def cmd(d):
    m=f"--model {d['model']} " if d.get('model') else ''
    return f"cd '{d['cwd']}' && claude --dangerously-skip-permissions {m}--resume {d['sid']}"

if new:                                     # fresh windows: fire and report
    for w in wins:
        osa(f'tell application "Terminal" to do script "{esc(cmd(plan[w]))}"')
        print(f"opened new window for {plan[w]['sid'][:8]}", flush=True)
        time.sleep(1)
    print("NOTE: answer the resume prompt in each new window yourself.")
    sys.exit()

live=set(); answered=set(); deadline=time.time()+1800
while time.time()<deadline and len(live)<len(wins):
    for w in wins:
        if w in live: continue
        if 'claude' not in procs(w):
            send(w, cmd(plan[w])); print(f"w{w} launched", flush=True); continue
        t=tail(w)
        if 'Enter to confirm' in t:
            if 'Resume full session as-is' in t and w not in answered:
                send(w, choice); answered.add(w); print(f"w{w} answered resume prompt", flush=True)
            elif 'trust this folder' in t:
                print(f"w{w} !! TRUST PROMPT - wrong cwd?", flush=True)
            continue
        live.add(w); print(f"w{w} LIVE {plan[w]['sid'][:8]}  {plan[w].get('title')}", flush=True)
    time.sleep(3)

missing=[w for w in wins if w not in live]
print(("all windows live" if not missing else f"NEEDS ATTENTION: {missing}"), flush=True)
PY
