"""`arh stop`: end a project's running submissions and dispatched controllers, and optionally its noted
scheduler jobs (security plan S8: a stop switch). Only processes on this host are signalled.

  stop.py ITERATIONS VERIFICATIONS SCHEDULER JOBS(0|1) [OWNER_DIR]
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys

from locks import owner, state


def owners(iterations, verifications, only):
    if only:
        return [Path(only)]
    found = sorted((p for p in Path(iterations).glob('iteration*') if p.name[9:].isdigit()), key=lambda p: int(p.name[9:]))
    return found + sorted(p for p in Path(verifications).glob('*') if (p / 'PREDECLARATION.md').is_file())


def signal_lock(lock, what):
    record = owner(lock) or {}
    if state(lock) == 'stale':
        return None
    if record.get('host') != socket.gethostname():
        return f"{what}: owner pid {record.get('pid')} runs on {record.get('host')}; stop it there (kill -TERM {record.get('pid')})"
    try:
        os.kill(int(record['pid']), signal.SIGTERM)
    except (KeyError, ValueError, ProcessLookupError):
        return None
    except PermissionError:
        return f"{what}: owner pid {record['pid']} belongs to another user; not signalled"
    return f"{what}: sent SIGTERM to pid {record['pid']}"


def noted_jobs(directory):
    notes = directory / 'metadata/notes.jsonl'
    out = set()
    for line in (notes.read_text().splitlines() if notes.is_file() else []):
        try:
            job = json.loads(line).get('job')
        except ValueError:
            continue
        if job:
            out.add(str(job))
    return out


def main(iterations, verifications, scheduler, jobs, only=None):
    done = []
    for d in owners(iterations, verifications, only):
        label = f'iteration {d.name[9:]}' if d.name.startswith('iteration') else f'verification {d.name}'
        for lock in sorted(d.glob('metadata/nextflow/*/.launch-lock')):
            said = signal_lock(lock, f'{label}: submission {lock.parent.name}')
            if said:
                done.append(said)
        if (d / '.dispatch-lock').is_dir():
            said = signal_lock(d / '.dispatch-lock', f'{label}: dispatched controller')
            if said:
                done.append(said)
        if jobs == '1':
            ids = sorted(noted_jobs(d))
            if ids and scheduler == 'slurm':
                live = subprocess.run(['squeue', '-h', '-j', ','.join(ids), '-o', '%i'], capture_output=True,
                                      text=True).stdout.split()
                live = sorted({j.split('_')[0] for j in live})
                if live:
                    subprocess.run(['scancel', *live], check=False)
                    done.append(f"{label}: cancelled noted job(s) {', '.join(live)}")
            elif ids:
                done.append(f"{label}: noted job(s) {', '.join(ids)} not cancelled: scheduler is {scheduler}")
    print('\n'.join(done) if done else 'nothing to stop: no live submission or controller'
          + ('' if jobs == '1' else ' (noted scheduler jobs are left alone without --jobs)'))


if __name__ == '__main__':
    main(*sys.argv[1:6])
