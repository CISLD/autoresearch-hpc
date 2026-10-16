"""Findings carried into later work, taken only from concluded iterations (stdlib only).

Agent memory tools (Claude Code auto-memory, claude-mem, mem0, beads' `bd remember`) keep whatever
the agent saw, unchecked, in a store only that harness reads. A finding a later iteration builds on
should instead be one an earlier iteration established: frozen plan, review, passing results gate.
`arh memory add` accepts a finding only from a concluded iteration and writes it as a plain
Markdown file with YAML front matter under knowledge/, citing the hashes and verdicts it rests on,
so any harness, reviewer, Markdown knowledge tool or grep can read it. A later finding may
supersede an earlier one; both stay on disk. An entry whose iteration no longer holds its
conclusion (the evidence changed) is shown as stale.

  memory.py add ROOT ITERDIR TEXT SUPERSEDES   record a finding of a concluded iteration
  memory.py list ROOT ITERS [all]              index: current findings (all: superseded and stale too)
  memory.py show ROOT ID                       one finding in full
  memory.py index ROOT ITERS LIMIT             JSON index for arh context
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

import attempts
from findings import summary as verdict_summary
from secret_scan import PATTERNS

ID = re.compile(r'^F\d+\.\d+$')


def base(root):
    return Path(root) / 'knowledge'


def parse(path):
    text = Path(path).read_text(errors='replace')
    match = re.match(r'^---\n(.*?)\n---\n(.*)$', text, re.S)
    if not match:
        return None
    meta = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(':')
        value = value.strip()
        meta[key.strip()] = json.loads(value) if value.startswith(('"', '[')) else value
    meta['text'] = match.group(2).strip()
    meta['path'] = str(path)
    if str(meta.get('iteration', '')).isdigit():
        meta['iteration'] = int(meta['iteration'])
    return meta


def entries(root):
    out = [parse(p) for p in sorted(base(root).glob('F*.md'))]
    return sorted((e for e in out if e and ID.match(e.get('id', ''))),
                  key=lambda e: tuple(int(x) for x in e['id'][1:].split('.')))


def status(root, iterations, entry, superseded):
    if entry['id'] in superseded:
        return f"superseded by {superseded[entry['id']]}"
    directory = Path(iterations) / f"iteration{entry['iteration']}"
    last = (attempts.receipts(directory) or [{}])[-1]
    if attempts.state(directory) != 'concluded' or last.get('report_sha256') != entry.get('report_sha256'):
        return 'stale: its iteration no longer holds this conclusion'
    return 'current'


def superseding(found):
    return {e['supersedes']: e['id'] for e in found if e.get('supersedes')}


def add(root, directory, text, supersedes):
    directory = Path(directory)
    n = directory.name[9:]
    if attempts.state(directory) != 'concluded':
        sys.exit(f'arh: iteration {n} has not concluded (arh gate results -n {n} must pass first): only a '
                 'concluded iteration\'s findings are carried into later work')
    if len(text.split()) < 5:
        sys.exit('arh: state the finding in a sentence or more, in the units of its estimand')
    leaked = [kind for kind, pattern in PATTERNS if pattern.search(text)]
    if leaked:
        sys.exit(f"arh: the finding carries what looks like a credential ({', '.join(leaked)}); nothing was recorded")
    found = entries(root)
    if supersedes and supersedes not in {e['id'] for e in found}:
        sys.exit(f'arh: no finding {supersedes} to supersede (arh memory list --all)')
    if supersedes and supersedes in superseding(found):
        sys.exit(f'arh: {supersedes} is already superseded by {superseding(found)[supersedes]}')
    k = 1 + max([int(e['id'].split('.')[1]) for e in found if e['id'].startswith(f'F{n}.')] or [0])
    receipt = attempts.receipts(directory)[-1]
    try:
        title = json.loads((directory / 'CLAIM.json').read_text()).get('title', '')
    except (OSError, ValueError):
        title = ''
    meta = dict(id=f'F{n}.{k}', iteration=int(n), question=attempts.question(directory), title=json.dumps(title),
                recorded=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), concluded=receipt.get('time'),
                verdicts=json.dumps(verdict_summary(directory)),
                predeclaration_sha256=receipt.get('predeclaration_sha256'), report_sha256=receipt.get('report_sha256'),
                reviews=json.dumps(sorted(receipt.get('reviews', {}))))
    if supersedes:
        meta['supersedes'] = supersedes
    base(root).mkdir(exist_ok=True)
    target = base(root) / f"{meta['id']}.md"
    with open(target, 'x') as out:
        out.write('---\n' + ''.join(f'{key}: {value}\n' for key, value in meta.items()) + '---\n\n' + text.strip() + '\n')
    print(f"recorded {meta['id']} ({target.relative_to(root)})" + (f'; {supersedes} is now superseded' if supersedes else ''))


def listing(root, iterations, everything):
    found = entries(root)
    replaced = superseding(found)
    shown = 0
    for e in found:
        state = status(root, iterations, e, replaced)
        if state != 'current' and not everything:
            continue
        print(f"{e['id']:<8} it.{e['iteration']:<4} {e.get('question', ''):<16} {state if state != 'current' else '':<10} "
              f"{e['text'].splitlines()[0][:100]}")
        shown += 1
    if not shown:
        print('no findings recorded' + ('' if everything else ' that are current (arh memory list --all)'))


def show(root, ident):
    path = base(root) / f'{ident}.md'
    if not ID.match(ident) or not path.is_file():
        sys.exit(f'arh: no finding {ident}')
    print(path.read_text(), end='')


def index(root, iterations, limit):
    """The newest LIMIT current findings, one line each: the layer arh context shows first."""
    found = entries(root)
    replaced = superseding(found)
    current = [dict(id=e['id'], iteration=e['iteration'], question=e.get('question'),
                    finding=e['text'].splitlines()[0][:160])
               for e in found if status(root, iterations, e, replaced) == 'current']
    return dict(findings=current[-limit:], omitted=max(0, len(current) - limit),
                details='arh memory show ID' if current else None)


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'add':
        add(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    elif cmd == 'list':
        listing(sys.argv[2], sys.argv[3], len(sys.argv) > 4 and sys.argv[4] == 'all')
    elif cmd == 'show':
        show(sys.argv[2], sys.argv[3])
    elif cmd == 'index':
        print(json.dumps(index(sys.argv[2], sys.argv[3], int(sys.argv[4]))))
    else:
        sys.exit(f'unknown command: {cmd}')
