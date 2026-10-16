"""Run an agent CLI with a fresh home directory holding only the files it needs to log in (stdlib only).

A blind replicator must not see the original implementation, and `arh replicate` gives it only the
frozen DAG. But a harness reads its home directory too: Claude Code's auto-memory, Codex's
memories database, plugins such as claude-mem that reload earlier sessions, chat history. Any of
them can carry the original code or its results into a session that is meant to be blind. A fresh
home hides all of them without knowing which tools are installed; the operator lists the
credential files to link in (`replicate_home_files`), as SOURCE or SOURCE:DEST, SOURCE relative to
the real home or absolute, with $VARS expanded. Entries whose source does not exist are skipped.

The links are symbolic, so a harness that refreshes its login writes through to the real file. A
harness that replaces the file instead leaves the real one holding a rotated-out token; that file
is copied back and named, so the operator's own sessions keep working.

  agenthome.py run MODE HOME FILES UNSET RECORD TEMPLATE PROMPT_FILE TIMEOUT
      MODE fresh|inherit. Runs the harness command TEMPLATE ({prompt}, {cwd} substituted, split like
      arh ask does, so quoted arguments survive) with a fresh HOME or the inherited one, for at most
      TIMEOUT seconds; stdout and stderr pass through. Writes RECORD (JSON) either way.
"""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


def links(home, files):
    real = Path(os.path.expanduser('~'))
    out, taken = [], set()
    for entry in files.split():
        source, _, dest = entry.partition(':')
        expanded = Path(os.path.expandvars(os.path.expanduser(source)))
        if not expanded.is_absolute():
            expanded = real / expanded
        if not dest:
            try:
                dest = str(expanded.relative_to(real))
            except ValueError:
                dest = expanded.name
        present = expanded.is_file() and dest not in taken
        if present:
            target = Path(home) / dest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(expanded)
            taken.add(dest)
        out.append(dict(source=source, dest=dest, linked=present))
    return out


def argv(template, prompt_file):
    values = {'{prompt}': Path(prompt_file).read_text(), '{cwd}': os.getcwd()}
    out = [re.sub(r'\{prompt\}|\{cwd\}', lambda m: values[m.group()], arg) for arg in shlex.split(template)]
    if not out:
        raise SystemExit('arh: empty harness command')
    return out, '{prompt}' not in template


def run(mode, home, files, unset, record, template, prompt_file, timeout):
    command, on_stdin = argv(template, prompt_file)
    env, linked = dict(os.environ), []
    home = Path(home)
    if mode == 'fresh':
        home.mkdir(parents=True)
        linked = links(home, files)
        env = {k: v for k, v in os.environ.items() if k not in set(unset.split())}
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'), XDG_DATA_HOME=str(home / '.local/share'),
                   XDG_CACHE_HOME=str(home / '.cache'), XDG_STATE_HOME=str(home / '.local/state'))
    stdin = open(prompt_file, 'rb') if on_stdin else subprocess.DEVNULL
    try:
        rc = subprocess.run(command, env=env, stdin=stdin, timeout=float(timeout) if float(timeout) > 0 else None).returncode
    except subprocess.TimeoutExpired:
        rc = 124
        print(f'arh: the agent ran longer than {timeout} s and was stopped', file=sys.stderr)
    finally:
        if on_stdin:
            stdin.close()
    rotated = []
    real = Path(os.path.expanduser('~'))
    for link in linked:
        target = home / link['dest']
        if link['linked'] and not target.is_symlink() and target.is_file():
            source = Path(os.path.expandvars(os.path.expanduser(link['source'])))
            source = source if source.is_absolute() else real / source
            shutil.copy2(target, source)
            rotated.append(link['source'])
            print(f"arh: the agent replaced its login file {link['source']}; copied it back so your own "
                  "sessions keep a valid token", file=sys.stderr)
    data = dict(home=mode, files=linked, unset=unset.split() if mode == 'fresh' else [], rotated=rotated, exit_code=rc)
    Path(record).write_text(json.dumps(data, indent=2) + '\n')
    return rc


if __name__ == '__main__':
    if sys.argv[1] == 'run' and len(sys.argv) == 10 and sys.argv[2] in ('fresh', 'inherit'):
        sys.exit(run(*sys.argv[2:10]))
    sys.exit('usage: agenthome.py run MODE HOME FILES UNSET RECORD TEMPLATE PROMPT_FILE TIMEOUT')
