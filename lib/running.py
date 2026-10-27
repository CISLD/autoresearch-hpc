"""What is running now: submissions, reviews and noted scheduler jobs (`arh status --running`).

`arh submit` blocks until Nextflow exits, so a session watching a long run read console.log and
trace.tsv by hand (field feedback #11). This reads the launch and review locks, the latest attempt's
trace, and asks the scheduler about job ids recorded with `arh note --job`.

  running.py ROOT ITERATIONS VERIFICATIONS SCHEDULER
"""
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from locks import describe, owner, state
from project import config

# A run that ended badly with nobody watching stays listed this long (field feedback #61, #63).
RECENT_DAYS = 7


def trace_counts(attempt):
    trace = attempt / 'trace.tsv'
    if not trace.is_file():
        return 'no trace yet'
    rows = [line.split('\t') for line in trace.read_text().splitlines()]
    if len(rows) < 2:
        return 'no task finished yet'
    status = rows[0].index('status') if 'status' in rows[0] else 4
    counts = Counter(r[status] for r in rows[1:] if len(r) > status)
    return ', '.join(f'{n} {s.lower()}' for s, n in sorted(counts.items()))


def ago(seconds):
    hours = seconds / 3600
    return f'{int(seconds // 60)} min' if hours < 1 else (f'{hours:.1f} h' if hours < 48 else f'{hours / 24:.1f} days')


def queued(scheduler):
    """[(state, working directory)] of this user's Slurm jobs. A Nextflow task's job runs in its work
    directory, which lies under the submission's own work/, so jobs can be counted per run."""
    if scheduler != 'slurm':
        return []
    try:
        out = subprocess.run(['squeue', '-h', '-u', os.environ.get('USER', ''), '-o', '%T|%Z'],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [tuple(line.split('|', 1)) for line in out.splitlines() if '|' in line]


def queue_note(work, jobs, idle, starve_hours):
    """'3 running, 12 pending in the queue', with STARVED when tasks wait and none has started or
    finished for starve_hours: one iteration's 4-CPU tasks waited 3.5 days behind another's larger
    ones while its driver kept logging and looked live (field feedback #69)."""
    prefix = str(work) + os.sep
    mine = Counter(s for s, wd in jobs if wd.startswith(prefix))
    if not mine:
        return ''
    running, pending = mine.get('RUNNING', 0), mine.get('PENDING', 0)
    note = f'; {running} running, {pending} pending in the queue'
    if pending and not running and idle is not None and idle > starve_hours * 3600:
        note += f' — STARVED: nothing has started or finished for {ago(idle)}'
    return note


def receipt(attempt):
    try:
        return json.loads((attempt / 'run.json').read_text())
    except (OSError, ValueError):
        return {}


def scheduler_states(jobs, scheduler):
    if not jobs or scheduler != 'slurm':
        return {}
    try:
        out = subprocess.run(['squeue', '-h', '-j', ','.join(sorted(jobs)), '-o', '%i %T %M'],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    found = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            found[parts[0].split('_')[0]] = ' '.join(parts[1:])
    return found


def main(root, iterations, verifications, scheduler):
    owners = sorted((p for p in Path(iterations).glob('iteration*') if p.name[9:].isdigit()), key=lambda p: int(p.name[9:]))
    owners += sorted(p for p in Path(verifications).glob('*') if (p / 'PREDECLARATION.md').is_file())
    shown = 0
    noted = {}
    jobs = queued(scheduler)
    starve_hours = float(config(Path(root) / '.arh/config/site.md').get('starve_hours') or 6)
    ended = []
    for d in owners:
        label = f'iteration {d.name[9:]}' if d.name.startswith('iteration') else f'verification {d.name}'
        live = set()
        for lock in sorted(d.glob('metadata/nextflow/*/.launch-lock')):
            if state(lock) == 'stale':
                continue
            name = lock.parent.name
            live.add(name)
            attempts = sorted(d.glob(f'logs/nextflow/{name}/attempt-*'), key=lambda p: p.stat().st_mtime)
            progress = trace_counts(attempts[-1]) if attempts else 'no attempt yet'
            idle = None
            if attempts:
                trace = attempts[-1] / 'trace.tsv'
                idle = time.time() - (trace.stat().st_mtime if trace.is_file() else attempts[-1].stat().st_mtime)
            print(f'{label}: submission {name}{describe(owner(lock))}: {progress}'
                  + queue_note(lock.parent / 'work', jobs, idle, starve_hours)
                  + (f' — {attempts[-1].relative_to(root)}' if attempts else ''))
            shown += 1
        # The newest attempt of each run that is not live: did it end badly?
        for run_dir in sorted(p for p in d.glob('logs/nextflow/*') if p.is_dir() and p.name not in live):
            attempts = sorted(run_dir.glob('attempt-*'), key=lambda p: p.stat().st_mtime)
            if not attempts or time.time() - attempts[-1].stat().st_mtime > RECENT_DAYS * 86400:
                continue
            data = receipt(attempts[-1])
            if not data:
                continue
            if 'exit_code' not in data:
                ended.append(f'{label}: submission {run_dir.name} ENDED WITHOUT AN EXIT CODE (the arh process died; '
                             f'node reboot or kill -9) — {attempts[-1].relative_to(root)}')
            elif data['exit_code']:
                ended.append(f"{label}: submission {run_dir.name} FAILED, exit {data['exit_code']}"
                             + (f" ({data['signal']})" if data.get('signal') else '')
                             + f", {trace_counts(attempts[-1])}, ended {data.get('finished', '?')[:16]}Z"
                             + f' — {attempts[-1].relative_to(root)}')
        if (d / '.review-lock').is_dir() and state(d / '.review-lock') != 'stale':
            print(f'{label}: review running{describe(owner(d / ".review-lock"))}')
            shown += 1
        notes = d / 'metadata/notes.jsonl'
        for line in (notes.read_text().splitlines() if notes.is_file() else []):
            try:
                note = json.loads(line)
            except ValueError:
                continue
            if note.get('job'):
                noted[str(note['job']).split('_')[0]] = (label, note.get('text', ''))
    states = scheduler_states(set(noted), scheduler)
    for job, (label, text) in sorted(noted.items()):
        if job in states:
            print(f'{label}: noted job {job} {states[job]}: {text[:80]}')
            shown += 1
    if not shown:
        print('nothing running: no live submission or review' + (', and no noted job is in the queue' if noted else ''))
    if ended:
        print(f'\nended badly in the last {RECENT_DAYS} days and not run again (arh submit ... --resume, or a new name):')
        for line in ended:
            print('  ' + line)


if __name__ == '__main__':
    main(*sys.argv[1:5])
