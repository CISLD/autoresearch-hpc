"""Small file/config helpers for deterministic AutoResearch HPC adapters."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


def config(path):
    """Read key/value pairs from an ``arh-config`` Markdown block."""
    values, inside = {}, False
    if not Path(path).is_file():
        return values
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line.startswith('```'):
            inside = line[3:].strip() == 'arh-config'
        elif inside and not line.startswith('#') and '=' in line:
            key, value = (part.strip() for part in line.split('=', 1))
            values.setdefault(key, value)
    return values


def guard(path, root, immutable=()):
    path, root = Path(path).resolve(), Path(root).resolve()
    if path != root and root not in path.parents:
        raise ValueError('write outside project: ' + str(path))
    for item in immutable:
        source = Path(item)
        source = (source if source.is_absolute() else root / source).resolve()
        if path == source or source in path.parents:
            raise ValueError('immutable path: ' + str(path))
    return path


def share(path):
    """Give a file or directory made by mkdtemp/mkstemp (0700/0600) the mode the umask gives anything
    else, keeping a directory's setgid bit. In a project shared between two accounts through a group,
    private run directories hid run.json and nextflow.log from the other account (field feedback #88)."""
    path = Path(path)
    mask = os.umask(0)
    os.umask(mask)
    if path.is_dir():
        os.chmod(path, (0o777 & ~mask) | (path.stat().st_mode & stat.S_ISGID))
    else:
        os.chmod(path, 0o666 & ~mask)
    return path


def knowledge(root):
    """{label: path} of the files that carry what outlives a session: the study's directives and
    gotchas, and the site's shared gotchas when site.md names them. Missing files are left out."""
    root = Path(root)
    # The label stays DIRECTIVES.md in records; `directives =` in project.md can name another file.
    directives = config(root / '.arh/config/project.md').get('directives') or 'DIRECTIVES.md'
    found = {name: root / path for name, path in (('DIRECTIVES.md', directives), ('GOTCHAS.md', 'GOTCHAS.md'))
             if (root / path).is_file()}
    shared = config(root / '.arh/config/site.md').get('site_gotchas', '')
    if shared and Path(shared).is_file():
        found['site_gotchas'] = Path(shared)
    return found


def knowledge_hashes(root):
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in knowledge(root).items()}


if __name__ == '__main__':
    if sys.argv[1] == 'knowledge-hashes':     # knowledge-hashes ROOT: JSON object for a record
        print(json.dumps(knowledge_hashes(sys.argv[2]), sort_keys=True))
    else:
        sys.exit(f'unknown command: {sys.argv[1]}')
