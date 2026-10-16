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
  memory.py search ROOT ITERS QUERY            current findings containing every word of QUERY

Searching is not ARH's job beyond that: `memory_search_cmd` in harnesses.md can name a Markdown
knowledge tool instead (basic-memory: `bm tool search-notes {query} --project <name>`, with
disable_permalinks and ensure_frontmatter_on_sync = false so it never rewrites a finding).
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

import attempts
from findings import summary as verdict_summary
from secret_scan import findings as secret_findings
import tempfile

ID = re.compile(r'^F\d+\.\d+$')


def base(root):
    return Path(root) / 'knowledge'


def parse(path):
    text = Path(path).read_text(errors='replace')
    match = re.match(r'^---\n(.*?)\n---\n(.*)$', text, re.S)
    if not match:
        return None
    meta, key = {}, None
    for line in match.group(1).splitlines():
        # A block list item, as a Markdown tool that reformats front matter writes lists.
        if line.startswith('- ') and key and isinstance(meta.get(key), list):
            meta[key].append(line[2:].strip())
            continue
        key, _, value = line.partition(':')
        key, value = key.strip(), value.strip()
        try:
            meta[key] = json.loads(value) if value.startswith(('"', '[')) else (value if value else [])
        except ValueError:
            meta[key] = value
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
    with tempfile.NamedTemporaryFile('w', suffix='.md') as probe:
        probe.write(text); probe.flush()
        leaked = sorted({kind for _, kind, _ in secret_findings(probe.name)})
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


def search(root, iterations, query):
    words = [w.lower() for w in query.split()]
    found = entries(root)
    replaced = superseding(found)
    hits = [e for e in found if status(root, iterations, e, replaced) == 'current'
            and all(w in (e['text'] + ' ' + str(e.get('title', ''))).lower() for w in words)]
    for e in hits:
        print(f"{e['id']:<8} it.{e['iteration']:<4} {e['text'].splitlines()[0][:110]}")
    if not hits:
        print('no current finding contains all of: ' + ' '.join(words))


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'add':
        add(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    elif cmd == 'list':
        listing(sys.argv[2], sys.argv[3], len(sys.argv) > 4 and sys.argv[4] == 'all')
    elif cmd == 'show':
        show(sys.argv[2], sys.argv[3])
    elif cmd == 'search':
        search(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == 'index':
        print(json.dumps(index(sys.argv[2], sys.argv[3], int(sys.argv[4]))))
    else:
        sys.exit(f'unknown command: {cmd}')
