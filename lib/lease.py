"""Who is working on an iteration, and when it was last touched (stdlib only).

Two agent sessions on two accounts drove one study. The first stopped at a usage limit with GPU jobs
chained; the second learned the state only from the first one's transcript, and nothing would have
stopped the first from resuming later on the same iteration (field feedback #35). Every arh command
that acts on an iteration now touches its lease: the holder (agent, user, host and ARH_SESSION when
set) and the last activity. Activity by anyone else is allowed but warned about, a takeover is
explicit and recorded, and `arh status` shows each open iteration's holder and how long it has been
idle.

  lease.py touch DIR COMMAND AGENT USER HOST SESSION   record activity; warn when someone else holds it
  lease.py take DIR REASON AGENT USER HOST SESSION     become the holder, keeping the old one in history
  lease.py show DIR                                    holder, since, last activity
  lease.py open ITERATIONS HOURS                       one line per iteration not yet concluded

While a dispatched controller holds an iteration (arh dispatch, a live .dispatch-lock), touch refuses
every other session: the main controller reads a dispatched iteration and does not write to it.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys

import locks
from project import config


class Refused(Exception):
    """Another session's controller holds the iteration."""


def dispatched(directory):
    """The owner record of the live controller dispatched to DIRECTORY, or None."""
    lock = Path(directory) / '.dispatch-lock'
    if not lock.is_dir() or locks.state(lock) == 'stale':
        return None
    return locks.owner(lock) or {}


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def age(stamp):
    try:
        then = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


def ago(hours):
    if hours is None:
        return 'at an unknown time'
    if hours < 1:
        return f'{int(hours * 60)} min ago'
    return f'{hours:.1f} h ago' if hours < 48 else f'{hours / 24:.1f} days ago'


def name(who):
    return f"{who.get('agent')}@{who.get('host')}" + (f" session {who['session']}" if who.get('session') else '')


def same(a, b):
    keys = ('agent', 'user', 'host') + (('session',) if a.get('session') and b.get('session') else ())
    return all(a.get(k) == b.get(k) for k in keys)


def owner_label(directory):
    """('iteration', '7') or ('verification', 'recount'): what -n takes for this directory."""
    d = Path(directory)
    return ('iteration', d.name[9:]) if d.name.startswith('iteration') and d.name[9:].isdigit() else ('verification', d.name)


def path(directory):
    return Path(directory) / 'metadata/lease.json'


def load(directory):
    try:
        return json.loads(path(directory).read_text())
    except (OSError, ValueError):
        return None


def save(directory, data):
    target = path(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.replace(target)


def touch(directory, command, who):
    holder = dispatched(directory)
    if holder is not None and who.get('session') != holder.get('session'):
        n = Path(directory).name[9:]
        raise Refused(f"iteration {n} is held by its dispatched controller ({holder.get('harness', '?')}, "
                      f"session {holder.get('session', '?')}): the main controller reads it and does not change "
                      f"it. See arh dispatch status -n {n}; arh wait -n {n} waits for it to finish.")
    lease = load(directory)
    if lease is None:
        lease = dict(holder=who, since=now())
        if not who.get('session') and owner_label(directory)[0] == 'iteration':
            shared_session_warning(directory, who)
    elif not same(lease['holder'], who):
        last = lease.get('last', {})
        kind, n = owner_label(directory)
        print(f"arh: {kind} {n} is held by {name(lease['holder'])}, last active "
              f"{ago(age(last.get('time')))} ({last.get('command', '?')}). If that session has ended and you are "
              f"taking the {kind} over, run: arh lease take -n {n} --reason TEXT",
              file=sys.stderr)
    lease['last'] = dict(time=now(), command=command, **{k: who[k] for k in ('agent', 'host')})
    save(directory, lease)
    log_activity(directory, command, who)


def shared_session_warning(directory, who):
    """A new iteration claimed without a session id while another open iteration is held by the same
    agent on the same host, also without one: leases cannot tell those agents apart. One overseer ran
    five background agents of one session, all 'claude' with no ARH_SESSION (field feedback #57)."""
    base = Path(directory).parent
    for other in base.glob('iteration*'):
        if other == Path(directory):
            continue
        lease = load(other)
        holder = (lease or {}).get('holder') or {}
        if (holder and not holder.get('session') and same(holder, who)
                and not ((other / 'results/report' / f'{other.name}_report.md').is_file() and reviewed(other))):
            print(f"arh: iteration {other.name[9:]} is open and held by {name(holder)} too, and neither has a session id, "
                  "so the lease cannot tell these agents apart. Give each concurrent agent its own "
                  "ARH_SESSION=<name> before it runs arh.", file=sys.stderr)
            return


def harness_session():
    """A session id the harness reports in an environment variable named in session_env
    (harnesses.md; exported by arh as ARH_SESSION_ENV), or None. Optional: agent_process works
    for every harness."""
    for name in os.environ.get('ARH_SESSION_ENV', '').split():
        if os.environ.get(name):
            return f'{name}={os.environ[name]}'
    return None


# Interpreters and launchers name no harness: a template such as `python3 wrapper.py {prompt}`
# must not make every Python ancestor look like an agent session.
GENERIC = {'python', 'python3', 'bash', 'sh', 'zsh', 'env', 'node', 'npx', 'uv', 'uvx', 'timeout', 'srun', 'nohup'}


def ps(pid, field):
    try:
        out = subprocess.run(['ps', '-o', f'{field}=', '-p', str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return out.stdout.strip() if out.returncode == 0 else ''


def agent_process():
    """The agent session as the nearest ancestor process whose program is a configured harness
    command (the first word of a harness_<name>_cmd): 'name:pid@host:start'. Needs no knowledge of
    any particular harness; None when arh was not started from one."""
    programs = {}
    for key, value in config(os.environ.get('ARH_HARN', '')).items():
        match = re.fullmatch(r'harness_(.+)_cmd', key)
        try:
            program = os.path.basename(shlex.split(value)[0]) if match and value.strip() else ''
        except ValueError:
            continue
        if program and program not in GENERIC:
            programs.setdefault(program[:15], match.group(1))     # ps truncates comm to 15 characters
    pid = os.getppid()
    for _ in range(32):
        if not programs or pid <= 1:
            return None
        # The program itself, or for a script (`node .../gemini`, `bash .../agent`) the script the
        # interpreter runs: the first argument after the interpreter that is not an option.
        words = ps(pid, 'args').split()
        names = [os.path.basename(ps(pid, 'comm'))] + [os.path.basename(w) for w in words[:1]]
        if words and os.path.basename(words[0]) in GENERIC:
            names += [os.path.basename(w) for w in words[1:] if not w.startswith('-')][:1]
        found = next((programs[name[:15]] for name in names if name[:15] in programs), None)
        if found:
            return f"{found}:{pid}@{socket.gethostname()}:{ps(pid, 'lstart')}"
        parent = ps(pid, 'ppid')
        if not parent.isdigit():
            return None
        pid = int(parent)
    return None


def log_activity(directory, command, who):
    """One line per arh command on the iteration: which agent session acted, and when."""
    entry = dict(time=now(), command=command, agent=who.get('agent'), user=who.get('user'), host=who.get('host'),
                 session=who.get('session'), harness_session=harness_session(), agent_process=agent_process())
    with open(Path(directory) / 'metadata/activity.jsonl', 'a') as log:
        log.write(json.dumps(entry) + '\n')


# A takeover summary looks at drafts, not run evidence or arh's own records: results/ only for the report.
NOT_DRAFTS = {'logs', 'metadata', '.nextflow', 'work', '__pycache__'}


def changed_since(directory, stamp, limit=15):
    """[(mtime, relative path)] of files under the iteration modified since STAMP, newest first. A
    replacement session took an iteration over and overwrote the previous holder's draft of the same
    script, because take printed only who had held it (field feedback #79, #65)."""
    try:
        since = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return []
    base = str(directory)
    found = []
    for top, dirs, files in os.walk(base):
        rel = os.path.relpath(top, base)
        dirs[:] = [d for d in dirs if d not in NOT_DRAFTS
                   and not (rel == 'results' and d != 'report') and not (rel == '.' and d.startswith('.'))]
        for f in files:
            path = os.path.join(top, f)
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                continue
            if mtime >= since:
                found.append((mtime, os.path.relpath(path, base)))
    return sorted(found, reverse=True)[:limit]


def take(directory, reason, who):
    lease = load(directory) or {}
    drafts = changed_since(directory, lease.get('since')) if lease.get('holder') else []
    with open(Path(directory) / 'metadata/lease-history.jsonl', 'a') as history:
        history.write(json.dumps(dict(time=now(), previous=lease.get('holder'), previous_last=lease.get('last'),
                                      holder=who, reason=reason,
                                      changed_under_previous=[rel for _, rel in drafts])) + '\n')
    save(directory, dict(holder=who, since=now(), last=dict(time=now(), command='arh lease take',
                                                             agent=who['agent'], host=who['host'])))
    print("{} {} is now held by ".format(*owner_label(directory)) + name(who)
          + (f"; it was held by {name(lease['holder'])}" if lease.get('holder') else ''))
    if drafts:
        print(f"files changed since {name(lease['holder'])} took it ({lease.get('since')}), newest first; "
              "read them before writing over them:")
        for mtime, rel in drafts:
            print(f"  {datetime.fromtimestamp(mtime, timezone.utc).strftime('%Y-%m-%d %H:%M')}Z  {rel}")


def show(directory):
    lease = load(directory)
    if not lease:
        print('no lease recorded (claimed before leases existed)')
        return
    last = lease.get('last', {})
    print(f"holder: {name(lease['holder'])} (user {lease['holder'].get('user')}) since {lease.get('since')}")
    print(f"last:   {last.get('command', '?')} by {last.get('agent')}@{last.get('host')}, {ago(age(last.get('time')))}")


def reviewed(directory):
    """A successful review record exists (cheap: status already validates reviews in full)."""
    for record in Path(directory).glob('CROSSCHECK_*.md.json'):
        try:
            data = json.loads(record.read_text())
        except (OSError, ValueError):
            continue
        if data.get('exit_code') == 0 and data.get('verdict'):
            return True
    return False


def open_iterations(base, hours):
    """Iterations not yet concluded (no report, or no review of it): who holds them and how long
    they have been idle."""
    base = Path(base)
    for d in sorted((p for p in base.glob('iteration*') if p.name[9:].isdigit()), key=lambda p: int(p.name[9:])):
        if (d / 'results/report' / f'{d.name}_report.md').is_file() and reviewed(d):
            continue
        lease = load(d)
        if not lease:
            continue
        idle = age(lease.get('last', {}).get('time'))
        stale = idle is not None and idle > hours
        print(f"  {d.name[9:]:<5} held by {name(lease['holder'])}, last active {ago(idle)} "
              f"({lease.get('last', {}).get('command', '?')})" + ('  STALE' if stale else ''))


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd in ('touch', 'take'):
        directory, arg = sys.argv[2], sys.argv[3]
        who = dict(zip(('agent', 'user', 'host', 'session'), sys.argv[4:8]))
        who['session'] = who.get('session') or None
        try:
            (touch if cmd == 'touch' else take)(directory, arg, who)
        except Refused as refused:
            print(f'arh: {refused}', file=sys.stderr)
            sys.exit(3)
    elif cmd == 'show':
        show(sys.argv[2])
    elif cmd == 'open':
        open_iterations(sys.argv[2], float(sys.argv[3]))
    else:
        sys.exit(f'unknown command: {cmd}')
