"""Per-iteration controllers: a main controller dispatches each iteration to its own agent session
(stdlib only).

With `orchestration = per-iteration` in harnesses.md, the operator talks to a main controller that
plans questions and reads summaries, and each iteration gets a fresh controller session that
pre-declares, calls executors (arh delegate) and validators (arh ask), and reports back. The
controller is started through the configured harness command template, so any agent CLI (Claude
Code, Codex, OpenCode, a meta-harness such as Omnigent) can be one; `dispatch_launcher` can put it
under the site scheduler. ARH keeps only what is protocol-specific:

- one controller per iteration at a time (a lock), and the iteration's lease handed to it;
- while it runs, other sessions cannot change the iteration through arh (lease.py refuses them);
- the controller's session output is kept with the iteration, credential-shaped text removed, and
  hashed: what the agent did between the gates is on record;
- the controller hands back a short summary (arh dispatch report) that the main controller reads
  instead of the transcript.

  dispatch.py start N BRIEF HARNESS DETACH DRY    dispatch iteration N (HARNESS may be empty)
  dispatch.py supervise N SEQ                     run the controller of dispatch SEQ (internal)
  dispatch.py report N OUTCOME SUMMARY            the controller's hand-back
  dispatch.py status [N]                          dispatches and their outcomes
  dispatch.py controller DIR                      harness of the iteration's latest dispatch
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys

import attempts
from findings import summary as verdict_summary
from harness import claimed_terms, cli_version, digest
import lease
import locks
from project import config
from secret_scan import PATTERNS

OUTCOMES = ('concluded', 'unconcluded', 'blocked')


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def iteration(n):
    return Path(os.environ['ARH_ITERS']) / f'iteration{n}'


def records(directory):
    base = Path(directory) / 'metadata/dispatch'
    return sorted((p for p in base.glob('[0-9][0-9][0-9]') if p.is_dir()), key=lambda p: p.name) if base.is_dir() else []


def load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def save(path, data):
    tmp = Path(str(path) + '.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.replace(path)


def controller(directory):
    """The harness of the iteration's latest dispatch, or ''."""
    runs = records(directory)
    return load(runs[-1] / 'run.json').get('harness', '') if runs else ''


def prompt(n, brief):
    home = Path(os.environ['ARH_HOME'])
    context = subprocess.run([str(home / 'bin/arh'), 'context', '-n', str(n)], capture_output=True, text=True,
                             env=dict(os.environ, ARH_PROJECT=os.environ['ARH_ROOT'])).stdout
    return (home / 'skills/dispatch/controller.md').read_text().replace('{N}', str(n)) \
        + f'\n---\n\n## Brief from the main controller\n\n{Path(brief).read_text()}\n' \
        + f'\n---\n\n## The iteration as it stands (arh context -n {n})\n\n```json\n{context.strip()}\n```\n'


def start(n, brief, harness, detach, dry):
    harn = config(os.environ['ARH_HARN'])
    directory = iteration(n)
    if harn.get('orchestration', 'single') != 'per-iteration':
        sys.exit("arh: arh dispatch needs orchestration = per-iteration in .arh/config/harnesses.md; with "
                 "single, one producer session does the whole iteration")
    if not (directory / 'CLAIM.json').is_file():
        sys.exit(f'arh: no claimed iteration {n} (the main controller claims it first: arh claim -t ...)')
    if attempts.state(directory) == 'concluded':
        sys.exit(f'arh: iteration {n} is concluded; another attempt at its question is a new iteration '
                 f'(arh claim -t ... --continues {n})')
    claimed = claimed_terms(directory)
    if claimed and claimed != digest(os.environ['ARH_HARN']):
        sys.exit(f'arh: .arh/config/harnesses.md changed since iteration {n} was claimed; the roles it would run '
                 'under are not the ones it was claimed under. Restore the file or claim a new iteration.')
    harness = harness or harn.get('iteration_controller') or harn.get('producer') or ''
    command = harn.get(f'harness_{harness}_cmd', '')
    if not command:
        sys.exit(f"arh: no command configured for the iteration controller '{harness}' (harnesses.md)")
    if not Path(brief).is_file():
        sys.exit(f'arh: brief not found: {brief}')
    leaked = [f'{kind}' for kind, pattern in PATTERNS if pattern.search(Path(brief).read_text(errors='replace'))]
    if leaked:
        sys.exit(f"arh: the brief carries what looks like a credential ({', '.join(leaked)}); nothing was sent")
    text = prompt(n, brief)
    if dry:
        print(f'# dry run — would start {harness} as the controller of iteration {n}\n')
        print(text)
        return 0
    holder = lease.dispatched(directory)
    if holder is not None:
        sys.exit(f"arh: iteration {n} already has a running controller ({holder.get('harness', '?')}, session "
                 f"{holder.get('session', '?')}); arh dispatch status -n {n}")
    limit = int(harn.get('max_parallel_iterations') or 2)
    busy = [d.name for d in Path(os.environ['ARH_ITERS']).glob('iteration*') if lease.dispatched(d) is not None]
    if len(busy) >= limit:
        sys.exit(f"arh: {len(busy)} controller(s) already running ({', '.join(sorted(busy))}); "
                 f'max_parallel_iterations is {limit}. arh wait, or arh dispatch status')
    lock = directory / '.dispatch-lock'
    try:
        locks.acquire(lock, os.getpid(), 'dispatch lock')
    except locks.Held as held:
        sys.exit(f'arh: iteration {n} already has a running controller{held}; arh dispatch status -n {n}')
    seq = f'{len(records(directory)) + 1:03d}'
    session = f'dispatch-{n}-{seq}'
    owner = locks.owner(lock)
    owner.update(session=session, harness=harness, dispatch=seq)
    (lock / 'owner.json').write_text(json.dumps(owner) + '\n')
    record = directory / 'metadata/dispatch' / seq
    record.mkdir(parents=True)
    (record / 'brief.md').write_text(Path(brief).read_text())
    (record / 'prompt.md').write_text(text)
    save(record / 'run.json', dict(
        iteration=int(n), dispatch=seq, session=session, harness=harness,
        family=harn.get(f'harness_{harness}_family', 'unknown'), command_template=command,
        launcher=harn.get('dispatch_launcher', ''), harness_version=cli_version(
            harn.get(f'harness_{harness}_version_cmd', ''), os.environ['ARH_ROOT']),
        brief_sha256=digest(record / 'brief.md'), prompt_sha256=digest(record / 'prompt.md'),
        dispatched_by=dict(agent=os.environ.get('ARH_LEASE_AGENT', ''), user=os.environ.get('USER', ''),
                           session=os.environ.get('ARH_SESSION') or None),
        started=now(), state='running'))
    lease.take(directory, f'dispatched to {harness} (dispatch {seq})',
               dict(agent=harness, user=os.environ.get('USER', 'unknown'), host=socket.gethostname(), session=session))
    if detach:
        with open(record / 'supervisor.log', 'w') as log:
            child = subprocess.Popen([sys.executable, __file__, 'supervise', str(n), seq], start_new_session=True,
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        owner['pid'] = child.pid
        (lock / 'owner.json').write_text(json.dumps(owner) + '\n')
        print(f'dispatched iteration {n} to {harness} (session {session}), detached. '
              f'Follow it with: arh dispatch status -n {n}; arh wait -n {n}')
        return 0
    print(f'dispatched iteration {n} to {harness} (session {session}); waiting for it to finish', file=sys.stderr)
    return supervise(n, seq)


def redact(path):
    """Replace credential-shaped text in PATH; return how many were removed."""
    try:
        text = Path(path).read_text(errors='replace')
    except OSError:
        return 0
    count = 0
    for kind, pattern in PATTERNS:
        text, k = pattern.subn(f'[REDACTED {kind}]', text)
        count += k
    if count:
        Path(path).write_text(text)
    return count


def supervise(n, seq):
    harn = config(os.environ['ARH_HARN'])
    directory = iteration(n)
    record = directory / 'metadata/dispatch' / seq
    run = load(record / 'run.json')
    values = {'{prompt}': (record / 'prompt.md').read_text(), '{cwd}': os.environ['ARH_ROOT']}
    argv = shlex.split(harn.get('dispatch_launcher', '')) + [
        re.sub(r'\{prompt\}|\{cwd\}', lambda m: values[m.group()], arg) for arg in shlex.split(run['command_template'])]
    env = dict(os.environ, ARH_SESSION=run['session'], ARH_DISPATCH=str(n), ARH_PROJECT=os.environ['ARH_ROOT'])
    for assignment in shlex.split(harn.get('dispatch_env', '')):
        key, _, value = assignment.partition('=')
        if key:
            env[key] = value
    timeout = float(harn.get('dispatch_timeout') or 0)
    on_stdin = '{prompt}' not in run['command_template']
    with open(record / 'session.log', 'wb') as out, open(record / 'stderr.log', 'wb') as err, \
            open(record / 'prompt.md', 'rb') if on_stdin else open(os.devnull, 'rb') as stdin:
        try:
            rc = subprocess.run(argv, cwd=os.environ['ARH_ROOT'], env=env, stdin=stdin, stdout=out, stderr=err,
                                timeout=timeout or None).returncode
        except subprocess.TimeoutExpired:
            rc = 124
            err.write(f'\narh: the controller ran longer than dispatch_timeout ({timeout:g} s) and was stopped\n'.encode())
        except OSError as error:
            rc = 127
            err.write(f'\narh: could not start the controller: {error}\n'.encode())
    removed = redact(record / 'session.log') + redact(record / 'stderr.log')
    summary = load(record / 'summary.json')
    run.update(finished=now(), state='finished', exit_code=rc, redactions=removed,
               session_log_sha256=digest(record / 'session.log'), session_log_bytes=(record / 'session.log').stat().st_size,
               stderr_sha256=digest(record / 'stderr.log'), outcome=summary.get('outcome'))
    save(record / 'run.json', run)
    try:
        locks.release(directory / '.dispatch-lock')
    except OSError:
        pass
    print(f"iteration {n}: controller exited {rc}; outcome {summary.get('outcome') or 'not reported'}"
          f" (metadata/dispatch/{seq})", file=sys.stderr)
    return rc


def report(n, outcome, text):
    directory = iteration(n)
    if os.environ.get('ARH_DISPATCH') != str(n):
        sys.exit(f'arh: only the controller dispatched to iteration {n} reports on it (arh dispatch report runs '
                 'inside a dispatched session)')
    if outcome not in OUTCOMES:
        sys.exit(f"arh: --outcome must be one of {', '.join(OUTCOMES)}")
    if len(text.split()) < 5:
        sys.exit('arh: the summary is what the main controller reads instead of your transcript: give the result, '
                 'the review and what remains, in a few sentences')
    holder = lease.dispatched(directory) or {}
    seq = holder.get('dispatch') or (records(directory)[-1].name if records(directory) else None)
    if not seq:
        sys.exit(f'arh: iteration {n} has no dispatch record')
    data = dict(outcome=outcome, summary=text, time=now(), state=attempts.state(directory),
                verdicts=verdict_summary(directory) or None, question=attempts.question(directory))
    if outcome == 'concluded' and data['state'] != 'concluded':
        sys.exit(f'arh: iteration {n} has not passed arh gate results; report it as unconcluded or blocked')
    save(directory / 'metadata/dispatch' / seq / 'summary.json', data)
    print(f'reported iteration {n}: {outcome}')


def status(number=None):
    base = Path(os.environ['ARH_ITERS'])
    dirs = [iteration(number)] if number else sorted(
        (p for p in base.glob('iteration*') if p.name[9:].isdigit()), key=lambda p: int(p.name[9:]))
    shown = False
    for directory in dirs:
        live = lease.dispatched(directory)
        for record in records(directory):
            run, summary = load(record / 'run.json'), load(record / 'summary.json')
            running = live is not None and live.get('dispatch') == record.name
            state = 'running' if running else (f"exited {run.get('exit_code')}" if run.get('state') == 'finished'
                                               else 'interrupted')
            print(f"{directory.name[9:]:<5} {record.name}  {run.get('harness', '?'):<12} {state:<11} "
                  f"{summary.get('outcome') or '-':<12} {(summary.get('summary') or '')[:100]}")
            shown = True
    if not shown:
        print('no dispatches' + (f' for iteration {number}' if number else ''))


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'start':
        sys.exit(start(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] == '1', sys.argv[6] == '1'))
    elif cmd == 'supervise':
        sys.exit(supervise(sys.argv[2], sys.argv[3]))
    elif cmd == 'report':
        report(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == 'status':
        status(sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None)
    elif cmd == 'controller':
        print(controller(sys.argv[2]))
    else:
        sys.exit(f'unknown command: {cmd}')
