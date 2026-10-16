"""Which question each iteration addresses, whether it concluded, and how many tries preceded it
(stdlib only).

An agent may run many iterations on one question and conclude the one that worked. Nothing in the
record said how many tries came before a concluded result (external review of v0.3.0, 2026-10-13:
per-session feedback amounted to a search toward the target). An iteration now names its question
when it is claimed (`arh claim --question ID`, or `--continues N`), a passing results gate writes a
conclusion receipt, and the ledger reports each concluded iteration as attempt k of n on its
question, counting every iteration that addressed it, concluded or not.

  attempts.py conclude DIR          append a conclusion receipt (metadata/conclusions.jsonl) when the
                                    results gate passes; nothing when the last one still holds
  attempts.py state DIR             concluded | open
  attempts.py question DIR          the iteration's question id
  attempts.py ledger ITERATIONS     the ledger's questions section (questions tried more than once)
  attempts.py json ITERATIONS       {iteration: {question, state, attempt, of}} for arh status --json
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from harness import result_artifacts, valid_adjudications, valid_records
import sessions

QUESTION_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')


def digest(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def evidence(directory):
    """The hashes a conclusion rests on: declaration, report, result files, eligible reviews and
    their judged rebuttals."""
    directory = Path(directory)
    report = directory / 'results/report' / f'{directory.name}_report.md'
    return dict(predeclaration_sha256=digest(directory / 'README.md'), report_sha256=digest(report),
                result_artifacts=result_artifacts(directory),
                reviews={Path(r).name: digest(r) for r in valid_records(directory)},
                adjudications={Path(r).name: digest(r) for r, _ in valid_adjudications(directory)})


def receipts(directory):
    try:
        lines = (Path(directory) / 'metadata/conclusions.jsonl').read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def holds(receipt, current):
    return all(receipt.get(k) == v for k, v in current.items())


def conclude(directory):
    directory = Path(directory)
    current = evidence(directory)
    past = receipts(directory)
    if past and holds(past[-1], current):
        return
    # Which agent sessions the conclusion came from; recorded, not part of what must still hold.
    record = dict(time=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), question=question(directory),
                  **current, **sessions.as_json(directory))
    (directory / 'metadata').mkdir(exist_ok=True)
    with open(directory / 'metadata/conclusions.jsonl', 'a') as out:
        out.write(json.dumps(record, sort_keys=True) + '\n')


def state(directory):
    """concluded when the last conclusion receipt still matches the evidence on disk."""
    past = receipts(directory)
    return 'concluded' if past and holds(past[-1], evidence(directory)) else 'open'


def question(directory):
    directory = Path(directory)
    try:
        q = json.loads((directory / 'CLAIM.json').read_text()).get('question')
    except (OSError, ValueError, AttributeError):
        q = None
    return q or f'q{directory.name[9:]}'


def iterations(base):
    return sorted((p for p in Path(base).glob('iteration*') if p.name[9:].isdigit()), key=lambda p: int(p.name[9:]))


def grouped(base):
    """{question: [(n, state)]} in iteration order."""
    groups = {}
    for d in iterations(base):
        groups.setdefault(question(d), []).append((int(d.name[9:]), state(d)))
    return groups


def ledger(base):
    tried = {q: its for q, its in grouped(base).items() if len(its) > 1}
    if not tried:
        return
    print('\n| Question | Iterations | Concluded |\n|---|---|---|')
    for q, its in tried.items():
        done = [f'{n} (attempt {k} of {len(its)})' for k, (n, s) in enumerate(its, 1) if s == 'concluded']
        print(f"| {q} | {', '.join(str(n) for n, _ in its)} | {', '.join(done) or 'none yet'} |")
    print('\nIterations not listed here each address their own question.')


def as_json(base):
    out = {}
    for q, its in grouped(base).items():
        for k, (n, s) in enumerate(its, 1):
            out[n] = dict(question=q, state=s, attempt=k, of=len(its))
    print(json.dumps(out))


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'conclude':
        conclude(sys.argv[2])
    elif cmd == 'state':
        print(state(sys.argv[2]))
    elif cmd == 'question':
        print(question(sys.argv[2]))
    elif cmd == 'ledger':
        ledger(sys.argv[2])
    elif cmd == 'json':
        as_json(sys.argv[2])
    elif cmd == 'valid-id':
        sys.exit(0 if QUESTION_ID.match(sys.argv[2]) else 1)
    else:
        sys.exit(f'unknown command: {cmd}')
