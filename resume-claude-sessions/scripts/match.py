#!/usr/bin/env python3
"""Match dumped Terminal scrollbacks to Claude Code session transcripts.

Usage: match.py <outdir> [--self <session-id-prefix>]

Reads <outdir>/scroll/w*.txt, indexes ~/.claude/projects/*/*.jsonl, and writes
<outdir>/plan.json mapping window id -> {sid, cwd, model, title, confidence}.

--self excludes the controlling session's own transcript. That transcript
contains the scrollback text just dumped into it and otherwise wins every match.
It is auto-detected from $CLAUDE_SESSION_ID when not supplied.
"""
import json, glob, os, re, sys

WORD = re.compile(r"[A-Za-z0-9_./:-]+")
WORD_L = re.compile(r"[A-Za-z0-9']+")
UI = re.compile(r'[─│⏺⎿❯✻※⏵•]')
TAIL_BYTES = 600_000          # transcript tail scanned first (scrollback = end of session)


def shingles(text, n=8, pat=WORD):
    w = pat.findall(text)
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def unescape(raw):
    return raw.replace('\\n', '\n').replace('\\"', '"').replace('\\t', ' ')


def index_sessions(exclude):
    """Return [{sid, file, title, cwd (startup), model, last_assistant}]."""
    out = []
    for f in glob.glob(os.path.expanduser('~/.claude/projects/*/*.jsonl')):
        sid = os.path.basename(f)[:-6]
        if exclude and sid.startswith(exclude):
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


def score(win_sh, path, full=False):
    """Count DISTINCT window shingles present in the transcript.

    Union, not a per-chunk sum: chunks overlap by `carry`, so summing
    double-counts and can push the ratio above 100%.
    """
    size = os.path.getsize(path)
    matched = set()
    with open(path, 'rb') as fh:
        if not full and size > TAIL_BYTES:
            fh.seek(size - TAIL_BYTES)
        carry = ''
        while True:
            chunk = fh.read(8_000_000)
            if not chunk:
                break
            txt = carry + unescape(chunk.decode('utf8', errors='replace'))
            matched |= (win_sh & shingles(txt))
            carry = txt[-4000:]
            if not full:
                break
    return len(matched)


def main():
    out_dir = sys.argv[1]
    exclude = None
    if '--self' in sys.argv:
        exclude = sys.argv[sys.argv.index('--self') + 1][:8]
    elif os.environ.get('CLAUDE_SESSION_ID'):
        exclude = os.environ['CLAUDE_SESSION_ID'][:8]

    sessions = index_sessions(exclude)
    windows = {}
    for f in sorted(glob.glob(os.path.join(out_dir, 'scroll', 'w*.txt'))):
        wid = os.path.basename(f)[1:-4]
        windows[wid] = open(f, errors='replace').read()

    plan = {}
    print(f"{len(windows)} windows vs {len(sessions)} transcripts"
          + (f" (excluding {exclude})" if exclude else ""))
    for wid, text in windows.items():
        wsh = shingles(text)
        scored = sorted(((score(wsh, s['file']), s) for s in sessions),
                        key=lambda x: -x[0])
        top, second = scored[0], scored[1]
        # weak or contested -> rescan full transcripts, not just the tail
        if top[0] < 100 or (second[0] and top[0] < second[0] * 3):
            scored = sorted(((score(wsh, s['file'], full=True), s) for s in sessions),
                            key=lambda x: -x[0])
            top, second = scored[0], scored[1]

        s = top[1]
        ratio = top[0] / max(1, len(wsh))
        margin = top[0] / max(1, second[0])
        conf = 'HIGH' if ratio > .5 and margin > 5 else ('MED' if ratio > .2 else 'LOW')

        # does the window show the session's CURRENT end?
        tail_sh = shingles(text[-6000:], n=6, pat=WORD_L)
        last_sh = shingles(s['last_asst'] or '', n=6, pat=WORD_L)
        endmatch = len(tail_sh & last_sh) / max(1, len(last_sh))
        stale = endmatch < .15
        restores = text.count('[Restored ')

        plan[wid] = dict(sid=s['sid'], cwd=s['cwd'], model=s['model'],
                         title=s['title'], confidence=conf,
                         overlap=round(ratio * 100, 1), endmatch=round(endmatch * 100, 1),
                         restores=restores, stale=stale, runner_up=second[1]['sid'][:8])
        flag = ''
        if stale:
            flag += '  [STALE? window may show an older point]'
        if restores > 1:
            flag += f'  [restored {restores}x - died in an earlier incident]'
        print(f"w{wid} -> {s['sid'][:8]}  {conf:4} overlap={ratio*100:5.1f}% "
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
