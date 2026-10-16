"""Which agent sessions acted on an iteration (stdlib only).

Receipts record runs and reviews, not the agent sessions that wrote the plan, the code and the
report. The record now names them from three sources, without capturing transcripts itself:

- metadata/activity.jsonl: every arh command on the iteration, with ARH_SESSION, the agent process
  it ran under (the nearest ancestor that is a configured harness program, for any harness) and,
  optionally, a session id the harness reports in a variable named in session_env;
- metadata/dispatch/*/run.json: controllers started by arh dispatch, whose output arh keeps;
- Entire CLI checkpoints, when the project is a git repository that Entire records: commits that
  touched the iteration carry an `Entire-Checkpoint: <id>` trailer, and the checkpoint holds the
  session's transcript, prompts and tool calls (https://github.com/entireio/cli).

  sessions.py show DIR      the sessions that acted on DIR
  sessions.py json DIR      the same as JSON, for the conclusion receipt
"""
import json
from pathlib import Path
import subprocess
import sys


def activity(directory):
    out = []
    try:
        lines = (Path(directory) / 'metadata/activity.jsonl').read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def grouped(directory):
    """[{id, agent, host, first, last, commands}] by session, in order of first appearance."""
    groups = {}
    for entry in activity(directory):
        key = (entry.get('session') or entry.get('harness_session') or entry.get('agent_process')
               or f"{entry.get('agent')}@{entry.get('host')}")
        group = groups.setdefault(key, dict(id=key, agent=entry.get('agent'), host=entry.get('host'),
                                            first=entry.get('time'), commands=0))
        group['last'] = entry.get('time')
        group['commands'] += 1
    return list(groups.values())


def checkpoints(directory):
    """[(commit, [checkpoint ids])] for commits touching DIRECTORY that carry Entire-Checkpoint
    trailers; [] when the project is not a git repository."""
    directory = Path(directory).resolve()
    try:
        top = subprocess.run(['git', '-C', str(directory), 'rev-parse', '--show-toplevel'],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if top.returncode:
        return None
    log = subprocess.run(['git', '-C', top.stdout.strip(), 'log',
                          '--format=%H%x1f%(trailers:key=Entire-Checkpoint,valueonly,separator=%x2C)',
                          '--', str(directory)], capture_output=True, text=True, timeout=60)
    out = []
    for line in log.stdout.splitlines():
        commit, _, ids = line.partition('\x1f')
        ids = [i.strip() for i in ids.split(',') if i.strip()]
        if ids:
            out.append((commit, ids))
    return out


def dispatches(directory):
    out = []
    for run in sorted((Path(directory) / 'metadata/dispatch').glob('[0-9][0-9][0-9]/run.json')):
        try:
            data = json.loads(run.read_text())
        except (OSError, ValueError):
            continue
        out.append(dict(session=data.get('session'), harness=data.get('harness'), started=data.get('started'),
                        log_sha256=data.get('session_log_sha256'), record=str(run.parent.relative_to(directory))))
    return out


def as_json(directory):
    found = checkpoints(directory)
    return dict(sessions=[g['id'] for g in grouped(directory)], dispatches=[d['session'] for d in dispatches(directory)],
                entire_checkpoints=sorted({i for _, ids in found or [] for i in ids}))


def show(directory):
    groups = grouped(directory)
    print('sessions that ran arh commands on this iteration (metadata/activity.jsonl):')
    for g in groups:
        print(f"  {g['id']:<48} {g['agent']}@{g['host']}  {g['first']} .. {g['last']}  ({g['commands']} commands)")
    if not groups:
        print('  none recorded (activity is logged from v0.4 on)')
    for d in dispatches(directory):
        print(f"dispatched controller {d['session']} ({d['harness']}), output kept in {d['record']}/session.log")
    found = checkpoints(directory)
    if found is None:
        print('Entire checkpoints: not in use (the project is not a git repository)')
    elif not found:
        print('Entire checkpoints: none (no commit touching this iteration carries an Entire-Checkpoint trailer)')
    else:
        print('Entire checkpoints (transcripts, prompts and tool calls; https://github.com/entireio/cli):')
        for commit, ids in found:
            print(f"  {', '.join(ids)}  in commit {commit[:12]}")


if __name__ == '__main__':
    if sys.argv[1] == 'show':
        show(sys.argv[2])
    elif sys.argv[1] == 'json':
        print(json.dumps(as_json(sys.argv[2])))
    else:
        sys.exit(f'unknown command: {sys.argv[1]}')
