"""The integrity of the iteration record itself: declared sections, the freeze journal, the claim
registry and the run receipts (stdlib only).

An external review of v0.3.0 (2026-10-13) showed four gaps a fallible agent could fall into without
trying to: a pre-declaration whose seven headings were all present and all empty froze; deleting
PREDECLARATION.sha256 while results/ was moved aside let a plan written after the result be frozen
again and concluded; deleting a concluded iteration's directory left `arh ledger check` passing,
because the claim registry that still listed it was never read; and nothing said when the scripts a
completed run used were edited and run again. This module closes them by detection, inside the
cooperative trust model: a process that rewrites the journal's whole hash chain is out of scope.

  record.py sections README TEMPLATE REQUIRED   each required heading present and with content
  record.py frozen ROOT N                       the journal row that froze iteration N, if any
  record.py era DIR                             exit 0 if the iteration was claimed under the journal
  record.py append ROOT N SHA AT [ANCHOR]       append a freeze to the journal (under a lock)
  record.py verify ROOT ITERS                   journal chain intact and consistent with the disk
  record.py backfill ROOT ITERS [AT]            journal rows for frozen iterations that have none
  record.py registry ROOT ITERS                 claimed iteration numbers with no directory
  record.py runs DIR                            run counts, and scripts edited after a completed run
"""
import fcntl
import hashlib
import json
from pathlib import Path
import re
import sys

JOURNAL = 'freezes.tsv'
HEADER = ['iteration', 'sha256', 'frozen', 'anchor', 'prev', 'entry']
GENESIS = '0' * 64
HEADING = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')
FENCE = re.compile(r'^\s*(```|~~~)')


# ---- sections ---------------------------------------------------------------------------------

def _strip_comments(text):
    return re.sub(r'<!--.*?-->', '', text, flags=re.S)


def section_bodies(readme):
    """[(heading text, level, [body lines])] in order; a body runs to the next heading of the same
    or a higher level, so numbered sub-headings belong to their section."""
    lines = _strip_comments(Path(readme).read_text(errors='replace')).splitlines()
    out, fenced = [], False
    for line in lines:
        if FENCE.match(line):
            fenced = not fenced
        match = None if fenced else HEADING.match(line)
        if match:
            out.append([match.group(2), len(match.group(1)), []])
        elif out:
            out[-1][2].append(line)
    merged = []
    for i, (text, level, body) in enumerate(out):
        lines = list(body)
        for _, sub_level, sub_body in out[i + 1:]:
            if sub_level <= level:
                break
            lines += sub_body           # a sub-heading alone is not content
        merged.append((text, level, lines))
    return merged


def content(body, boilerplate):
    """Lines of BODY that carry text the author wrote: not blank, not a fence marker, not a line
    the iteration template already holds."""
    keep = []
    for line in body:
        s = line.strip()
        if not s or FENCE.match(s) or s in boilerplate or not re.search(r'\w', s):
            continue
        keep.append(s)
    return keep


def sections(readme, template, required):
    boilerplate = set()
    if template and Path(template).is_file():
        boilerplate = {l.strip() for l in _strip_comments(Path(template).read_text()).splitlines() if l.strip()}
    bodies = section_bodies(readme)
    fails = 0
    for name in [s.strip() for s in required.split(',') if s.strip()]:
        found = next((b for b in bodies if name.lower() in b[0].lower()), None)
        if found is None:
            print(f'  FAIL section missing: {name}')
            fails += 1
        elif not content(found[2], boilerplate):
            print(f'  FAIL section empty: {name} (a heading with nothing under it declares nothing)')
            fails += 1
        else:
            print(f'  OK   section: {name}')
    return fails


# ---- freeze journal ---------------------------------------------------------------------------

def _entry(prev, iteration, sha, frozen, anchor):
    return hashlib.sha256('\t'.join((prev, str(iteration), sha, frozen, anchor)).encode()).hexdigest()


def journal_rows(root):
    path = Path(root) / '.arh' / JOURNAL
    if not path.is_file():
        return None
    rows = []
    for line in path.read_text().splitlines()[1:]:
        if line.strip():
            fields = line.split('\t')
            rows.append(dict(zip(HEADER, fields + [''] * (len(HEADER) - len(fields)))))
    return rows


def frozen(root, n):
    rows = journal_rows(root) or []
    row = next((r for r in rows if r['iteration'] == str(n)), None)
    if row:
        print('\t'.join(row[k] for k in HEADER))
    return row


def append(root, n, sha, at, anchor=''):
    state = Path(root) / '.arh'
    path = state / JOURNAL
    with open(state / (JOURNAL + '.lock'), 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not path.is_file():
            path.write_text('\t'.join(HEADER) + '\n')
        rows = journal_rows(root)
        if any(r['iteration'] == str(n) for r in rows):
            sys.exit(f'iteration {n} is already in the freeze journal; a plan is frozen once')
        prev = rows[-1]['entry'] if rows else GENESIS
        anchor = ' '.join(anchor.split())[:200]
        entry = _entry(prev, n, sha, at, anchor)
        with path.open('a') as out:
            out.write('\t'.join((str(n), sha, at, anchor, prev, entry)) + '\n')
    return entry


def _frozen_dirs(iters):
    out = {}
    for d in sorted(Path(iters).glob('iteration*')):
        m = re.fullmatch(r'iteration(\d+)', d.name)
        if m and d.is_dir():
            out[int(m.group(1))] = d
    return out


def verify(root, iters):
    """Problems with the journal, one per line: a broken chain, a frozen iteration without a row, a
    row whose hash is not the iteration's frozen hash, a row whose iteration is gone."""
    rows = journal_rows(root)
    dirs = _frozen_dirs(iters)
    problems = []
    if rows is None:
        if any((d / 'PREDECLARATION.sha256').is_file() for d in dirs.values()):
            problems.append('no freeze journal (.arh/freezes.tsv); run: arh migrate --apply')
        return problems
    prev = GENESIS
    seen = set()
    for i, r in enumerate(rows, 1):
        if r['prev'] != prev or r['entry'] != _entry(prev, r['iteration'], r['sha256'], r['frozen'], r['anchor']):
            problems.append(f'freeze journal row {i} (iteration {r["iteration"]}) does not chain: '
                            'the journal was edited, or a row removed or reordered')
        prev = r['entry']
        if r['iteration'] in seen:
            problems.append(f'iteration {r["iteration"]} is frozen twice in the journal')
        seen.add(r['iteration'])
        n = int(r['iteration']) if r['iteration'].isdigit() else None
        if n not in dirs:
            problems.append(f'iteration {r["iteration"]} was frozen (journal row {i}) but its directory is gone')
            continue
        freeze = dirs[n] / 'PREDECLARATION.sha256'
        current = freeze.read_text().split('\n', 1)[0].strip() if freeze.is_file() else None
        if current is None:
            problems.append(f'iteration {n} was frozen at {r["frozen"]} but PREDECLARATION.sha256 is gone')
        elif current != r['sha256']:
            problems.append(f'iteration {n} carries a different frozen hash than the one journalled at '
                            f'{r["frozen"]}: the plan was frozen again')
    for n, d in dirs.items():
        if (d / 'PREDECLARATION.sha256').is_file() and str(n) not in seen:
            problems.append(f'iteration {n} has PREDECLARATION.sha256 but no freeze journal row')
    return problems


def journal_era(directory):
    try:
        return json.loads((Path(directory) / 'CLAIM.json').read_text()).get('freeze_journal') is True
    except (OSError, ValueError, AttributeError):
        return False


def backfill(root, iters, at=''):
    rows = journal_rows(root) or []
    have = {r['iteration'] for r in rows}
    added = []
    for n, d in _frozen_dirs(iters).items():
        freeze = d / 'PREDECLARATION.sha256'
        # An iteration claimed under the journal had its row written at the freeze; a missing row is
        # a removed one, and backfilling it would launder a second freeze.
        if freeze.is_file() and str(n) not in have and not journal_era(d):
            lines = freeze.read_text().splitlines()
            sha = lines[0].strip() if lines else ''
            when = lines[1].strip() if len(lines) > 1 else at
            append(root, n, sha, when, 'backfilled by arh migrate' + (f' {at}' if at else ''))
            added.append(n)
    return added


# ---- claim registry ---------------------------------------------------------------------------

def registry(root, iters):
    path = Path(root) / '.arh/registry.tsv'
    if not path.is_file():
        return []
    claimed = sorted({int(l.split('\t', 1)[0]) for l in path.read_text().splitlines()[1:]
                      if l.split('\t', 1)[0].isdigit()})
    dirs = _frozen_dirs(iters)
    return [n for n in claimed if n not in dirs]


# ---- run receipts -----------------------------------------------------------------------------

def runs(directory):
    """Attempts per named workflow, and files a completed run used that a later run used edited.
    Re-running after a fix is legitimate; doing it silently is what the record should not allow."""
    receipts = []
    for path in Path(directory).glob('logs/nextflow/*/attempt-*/run.json'):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        receipts.append((data.get('started') or '', path.parts[-3], data))
    receipts.sort(key=lambda r: r[0])
    completed = sum(1 for *_, d in receipts if d.get('exit_code') == 0)
    names = {name for _, name, _ in receipts}
    used, changed = {}, []
    for _, name, d in receipts:
        files = dict(d.get('script_sha256') or {})
        if d.get('workflow'):
            files[d['workflow']] = d.get('workflow_sha256')
        if d.get('params_sha256'):
            files[f'params of {name}'] = d['params_sha256']
        for path, digest in files.items():
            if path in used and used[path] != digest and path not in changed:
                changed.append(path)
        if d.get('exit_code') == 0:
            used.update(files)
    if receipts:
        print(f'  runs: {len(receipts)} attempt(s) of {len(names)} named workflow(s), {completed} completed, '
              f'{len(receipts) - completed} failed or interrupted')
    if changed:
        shown = ', '.join(changed[:4]) + (f' and {len(changed) - 4} more' if len(changed) > 4 else '')
        print(f'  WARN {len(changed)} file(s) a completed run used were edited and run again: {shown}. '
              'Each run has its receipt; the report must say which run each result comes from and why '
              'the analysis changed after the plan was frozen')
    return 0


if __name__ == '__main__':
    command, args = sys.argv[1], sys.argv[2:]
    if command == 'sections':
        sys.exit(1 if sections(*args) else 0)
    elif command == 'era':
        sys.exit(0 if journal_era(*args) else 1)
    elif command == 'frozen':
        sys.exit(0 if frozen(*args) else 1)
    elif command == 'append':
        print(append(*args))
    elif command == 'verify':
        problems = verify(*args)
        print('\n'.join(problems))
        sys.exit(1 if problems else 0)
    elif command == 'backfill':
        print(' '.join(map(str, backfill(*args))))
    elif command == 'registry':
        print(' '.join(map(str, registry(*args))))
    elif command == 'runs':
        sys.exit(runs(*args))
    else:
        sys.exit(f'unknown command: {command}')
