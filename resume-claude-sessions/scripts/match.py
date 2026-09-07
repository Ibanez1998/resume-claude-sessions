#!/usr/bin/env python3
"""Match dumped Terminal scrollbacks to Claude Code session transcripts.

Usage: match.py <outdir> [--self <session-id-prefix>]

Reads <outdir>/scroll/w*.txt, indexes ~/.claude/projects/*/*.jsonl, and writes
<outdir>/plan.json mapping window id -> {sid, cwd, model, title, confidence}.

--self / --exclude drop a transcript from consideration. The controlling
session's own transcript contains the scrollback just dumped into it and would
otherwise win every match; it is auto-detected from $CLAUDE_CODE_SESSION_ID.
Transcripts that top-match 3+ windows are auto-excluded as rescue sessions.
"""
import json, glob, os, re, sys

WORD = re.compile(r"[A-Za-z0-9_./:-]+")
WORD_L = re.compile(r"[A-Za-z0-9']+")
UI = re.compile(r'[─│⏺⎿❯✻※⏵•]')
# `claude --resume <uuid>`, printed on clean exit and present in our own launch line
RESUME_ID = re.compile(r'--resume\s+([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}'
                       r'-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})')
TAIL_BYTES = 600_000          # transcript tail scanned first (scrollback = end of session)


def shingles(text, n=8, pat=WORD):
    w = pat.findall(text)
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def unescape(raw):
    return raw.replace('\\n', '\n').replace('\\"', '"').replace('\\t', ' ')


def index_sessions(excl=()):
    """Return [{sid, file, title, cwd (startup), model, last_assistant}]."""
    out = []
    for f in glob.glob(os.path.expanduser('~/.claude/projects/*/*.jsonl')):
        sid = os.path.basename(f)[:-6]
        if any(sid.startswith(x) for x in excl):
            continue
        title = start_cwd = model = last_asst = None
        for line in open(f, errors='replace'):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get('type') == 'ai-title' and o.get('aiTitle'):
                title = o['aiTitle']
            if start_cwd is None and o.get('cwd'):
                start_cwd = o['cwd']          # FIRST cwd: the project dir key
            m = o.get('message')
            if isinstance(m, dict):
                if m.get('model') and not m['model'].startswith('<'):
                    model = m['model']        # skip <synthetic> from compaction
                if o.get('type') == 'assistant':
                    c = m.get('content')
                    txt = c if isinstance(c, str) else ' '.join(
                        b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text'
                    ) if isinstance(c, list) else ''
                    if txt.strip():
                        last_asst = txt.strip()
        out.append(dict(sid=sid, file=f, title=title, cwd=start_cwd,
                        model=model, last_asst=last_asst))
    return out


def score_all(win_shingles, path):
    """Score one transcript against EVERY window in a single read.

    Returns {wid: count of that window's distinct shingles found}.

    One pass per transcript, not one per (window, transcript) pair: the naive
    version re-read every transcript once per window, which on a real machine
    meant 700+ scans of 1.3GB.

    Counts DISTINCT matches via set union. Summing per chunk double-counts,
    because consecutive chunks overlap by `carry`, and can push a ratio above
    100%.
    """
    matched = {w: set() for w in win_shingles}
    with open(path, 'rb') as fh:
        carry = ''
        while True:
            chunk = fh.read(8_000_000)
            if not chunk:
                break
            txt = carry + unescape(chunk.decode('utf8', errors='replace'))
            sh = shingles(txt)
            for w, ws in win_shingles.items():
                matched[w] |= (ws & sh)
            carry = txt[-4000:]
    return {w: len(s) for w, s in matched.items()}


def main():
    out_dir = sys.argv[1]
    excl = set()
    for flag in ('--self', '--exclude'):
        while flag in sys.argv:
            i = sys.argv.index(flag)
            excl.add(sys.argv[i + 1][:8])
            del sys.argv[i:i + 2]
    # Claude Code exports CLAUDE_CODE_SESSION_ID (not CLAUDE_SESSION_ID).
    for var in ('CLAUDE_CODE_SESSION_ID', 'CLAUDE_SESSION_ID'):
        if os.environ.get(var):
            excl.add(os.environ[var][:8])

    windows = {}
    for f in sorted(glob.glob(os.path.join(out_dir, 'scroll', 'w*.txt'))):
        wid = os.path.basename(f)[1:-4]
        windows[wid] = open(f, errors='replace').read()

    sessions = index_sessions(excl)
    by_sid = {s['sid']: s for s in sessions}
    plan = {}

    # ---- Fast path -------------------------------------------------------
    # A clean `/exit` prints "Resume this session with: claude --resume <id>",
    # and our own launch line carries the id too. That is authoritative, so use
    # it instead of scanning gigabytes. A crash never prints it, which is why
    # fingerprinting still exists below.
    for wid, text in list(windows.items()):
        ids = RESUME_ID.findall(text)
        for sid in reversed(ids):           # last mention = most recent
            if sid in by_sid:
                s = by_sid[sid]
                plan[wid] = dict(sid=sid, cwd=s['cwd'], model=s['model'],
                                 title=s['title'], confidence='EXACT',
                                 overlap=100.0, endmatch=100.0,
                                 restores=text.count('[Restored '),
                                 stale=False, runner_up=None,
                                 source='resume-line')
                print(f"w{wid} -> {sid[:8]}  EXACT (session id printed in window)"
                      f"  {str(s['title'])[:44]}")
                del windows[wid]
                break

    # ---- Fingerprint whatever is left ------------------------------------
    if windows:
        print(f"fingerprinting {len(windows)} window(s) against {len(sessions)} "
              f"transcripts" + (f", excluding {sorted(excl)}" if excl else ""))
        win_sh = {w: shingles(t) for w, t in windows.items()}
        matrix = {}                          # sid -> {wid: hits}
        for s in sessions:
            matrix[s['sid']] = score_all(win_sh, s['file'])

        # A transcript that is the top hit for many windows is not a real match:
        # it is a rescue/meta session that quoted those windows' scrollback into
        # its own transcript. Drop it and rescore from the same matrix.
        for _ in range(3):
            tops = {}
            for wid in windows:
                best = max(matrix, key=lambda sid: matrix[sid][wid])
                tops.setdefault(best, []).append(wid)
            meta = [sid for sid, wids in tops.items() if len(wids) >= 3]
            if not meta:
                break
            for sid in meta:
                print(f"!! {sid[:8]} is top match for {len(tops[sid])} windows; "
                      f"treating it as a rescue transcript and excluding it")
                del matrix[sid]

        for wid, text in windows.items():
            ranked = sorted(matrix, key=lambda sid: -matrix[sid][wid])
            sid, runner = ranked[0], (ranked[1] if len(ranked) > 1 else None)
            s = by_sid[sid]
            ratio = matrix[sid][wid] / max(1, len(win_sh[wid]))
            margin = matrix[sid][wid] / max(1, matrix[runner][wid] if runner else 1)
            conf = 'HIGH' if ratio > .5 and margin > 5 else ('MED' if ratio > .2 else 'LOW')

            # does the window show the session's CURRENT end?
            tail_sh = shingles(text[-6000:], n=6, pat=WORD_L)
            last_sh = shingles(s['last_asst'] or '', n=6, pat=WORD_L)
            endmatch = len(tail_sh & last_sh) / max(1, len(last_sh))
            stale = endmatch < .15
            restores = text.count('[Restored ')

            plan[wid] = dict(sid=sid, cwd=s['cwd'], model=s['model'],
                             title=s['title'], confidence=conf,
                             overlap=round(ratio * 100, 1), endmatch=round(endmatch * 100, 1),
                             restores=restores, stale=stale,
                             runner_up=runner[:8] if runner else None,
                             source='fingerprint')
            flag = ''
            if stale:
                flag += '  [STALE? window may show an older point]'
            if restores > 1:
                flag += f'  [restored {restores}x - died in an earlier incident]'
            print(f"w{wid} -> {sid[:8]}  {conf:4} overlap={ratio*100:5.1f}% "
                  f"end={endmatch*100:5.1f}%  {str(s['title'])[:44]}{flag}")

    # Duplicate session ids across windows: never resume both, because that is two processes
    # writing one transcript. Keep the window showing the session's current end
    # and quarantine the rest so resume.sh skips them.
    seen = {}
    for wid, p in plan.items():
        seen.setdefault(p['sid'], []).append(wid)
    for sid, wids in seen.items():
        if len(wids) > 1:
            keep = max(wids, key=lambda w: plan[w]['endmatch'])
            for w in wids:
                if w != keep:
                    plan[w]['stale'] = True
                    plan[w]['confidence'] = 'LOW'
                    plan[w]['note'] = f'collides with w{keep} on {sid[:8]}; needs manual review'
            print(f"\n!! {sid[:8]} matched windows {wids}: keeping w{keep}, "
                  f"quarantining {[w for w in wids if w != keep]} (resume ONE only)")

    low = [w for w, p in plan.items() if p['confidence'] == 'LOW' or p.get('stale')]
    if low:
        print(f"!! review before resuming: {sorted(low, key=int)}")

    json.dump(plan, open(os.path.join(out_dir, 'plan.json'), 'w'), indent=1)
    print(f"\nwrote {os.path.join(out_dir, 'plan.json')}")


if __name__ == '__main__':
    main()
