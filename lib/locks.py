"""Owner-recorded directory locks for submissions and reviews, and `arh wait` (stdlib only)."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import time


class Held(Exception):
    """The lock is held by a live, remote or unrecorded owner."""


def alive(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError, TypeError, OverflowError):
        return True
    return True


def owner(lock):
    try:
        return json.loads((Path(lock) / 'owner.json').read_text())
    except (OSError, ValueError):
        return None


def state(lock):
    """'live', 'stale' (its owner was a process on this host that no longer exists) or
    'unverifiable' (no owner record, or an owner on another host)."""
    record = owner(lock)
    if not record or record.get('host') != socket.gethostname():
        return 'unverifiable'
    return 'live' if alive(record.get('pid')) else 'stale'


def describe(record):
    return f" (owner pid {record.get('pid')} on {record.get('host')})" if record else ''


def acquire(lock, pid=None, what='lock'):
    """Take LOCK. A lock whose recorded owner is a dead process on this host is reclaimed; a lock
    with no owner record, or a live or remote owner, raises Held."""
    lock = Path(lock)
    try:
        lock.mkdir()
    except FileExistsError:
        record = owner(lock)
        if state(lock) != 'stale':
            raise Held(describe(record))
        stale = lock.with_name(f'{lock.name}.stale-{os.getpid()}')
        try:
            lock.rename(stale)      # atomic: of two reclaimers only one succeeds
        except OSError:
            raise Held('')
        shutil.rmtree(stale, ignore_errors=True)
        print(f"arh: reclaimed a {what} left by dead process {record['pid']} on {record['host']}", file=sys.stderr)
        try:
            lock.mkdir()
        except FileExistsError:
            raise Held('')
    (lock / 'owner.json').write_text(json.dumps({'host': socket.gethostname(), 'pid': pid or os.getpid(),
                                                 'started': datetime.now(timezone.utc).isoformat()}) + '\n')


def release(lock):
    lock = Path(lock)
    (lock / 'owner.json').unlink(missing_ok=True)
    lock.rmdir()


def running(iterations, number=None):
    """Submission and review locks under the given iteration(s): [(label, lock path)]."""
    root = Path(iterations)
    dirs = [root / f'iteration{number}'] if number else sorted(
        (p for p in root.glob('iteration*') if p.name[9:].isdigit()), key=lambda p: int(p.name[9:]))
    found = []
    for d in dirs:
        found += [(f'{d.name}: submission {p.parent.name}', p) for p in sorted(d.glob('metadata/nextflow/*/.launch-lock'))]
        if (d / '.review-lock').is_dir():
            found.append((f'{d.name}: review', d / '.review-lock'))
        # A dispatched controller (arh dispatch); not when the controller itself waits on its iteration.
        if (d / '.dispatch-lock').is_dir() and os.environ.get('ARH_DISPATCH') != d.name[9:]:
            found.append((f'{d.name}: controller', d / '.dispatch-lock'))
    return found


def wait(iterations, number, timeout, interval):
    """Block until no live submission or review lock remains. Exit 124 on timeout."""
    started, shown = time.time(), None
    while True:
        busy, stale = [], []
        for label, lock in running(iterations, number or None):
            if not lock.is_dir():
                continue
            st = state(lock)
            (stale if st == 'stale' else busy).append(
                f'{label}{describe(owner(lock))}' + (' — no owner record, cannot check it' if st == 'unverifiable' and not owner(lock) else ''))
        if (busy, stale) != shown:
            for item in busy:
                print(f'waiting: {item}', flush=True)
            for item in stale:
                print(f'ignored: {item} — its process has exited; the lock is reclaimed on next use', flush=True)
            shown = (busy, stale)
        if not busy:
            print('idle: no running submissions or reviews', flush=True)
            return 0
        if timeout and time.time() - started >= timeout:
            print(f'arh: still running after {timeout:g} s: ' + '; '.join(busy), file=sys.stderr)
            return 124
        time.sleep(interval)


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'acquire':                        # acquire LOCK PID WHAT
        try:
            acquire(sys.argv[2], int(sys.argv[3]), sys.argv[4])
        except Held as held:
            print(f'held{held}', file=sys.stderr)
            sys.exit(1)
    elif cmd == 'busy':                         # busy ITERATIONS N: one line per running submission or review
        for label, lock in running(sys.argv[2], int(sys.argv[3] or 0) or None):
            if lock.is_dir() and state(lock) != 'stale':
                print(label)
    elif cmd == 'wait':                         # wait ITERATIONS N TIMEOUT INTERVAL
        sys.exit(wait(sys.argv[2], int(sys.argv[3] or 0), float(sys.argv[4]), float(sys.argv[5])))
    else:
        sys.exit(f'unknown command: {cmd}')
