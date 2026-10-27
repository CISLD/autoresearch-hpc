"""Code an iteration imports from other iterations: declared, frozen with the plan, checked at submit.

Iterations routinely import a helper from an earlier iteration's scripts/. A run receipt hashed only
the submitting iteration's own scripts, so a pre-declaration that promised "the shared library is
unchanged" could not be checked, and the review found it unchecked (2026-09-29). A plan now declares
its imports in an arh-config block:

    ```arh-config
    imports = iterations/iteration1/scripts/it1_00_lib.py
    ```

`arh gate predeclare` (and `arh verify gate`) append one `import <sha256> <path>` line per file to
PREDECLARATION.sha256, after the plan's own hash and timestamp. `arh submit` refuses a run whose
declared imports changed since, and records them, plus any other iteration's scripts the workflow or
scripts name without declaring them, in the run receipt.

  imports.py freeze ROOT PLAN       print the import lines for a plan being frozen; exit 1 if one is unusable
  imports.py scripts ROOT DIR       print a `script <sha256> <path>` line per file already in DIR/scripts/

The iteration's own scripts that exist when the plan is frozen are pinned the same way (`script`
lines). A gating script written with the plan was edited after the freeze and nothing in the record
showed it (field feedback #74; external review of v0.3.0: scripts are not frozen at declaration).
`arh submit` reports a pinned script that changed since, or refuses with frozen_scripts = refuse.
"""
import hashlib
import os
from pathlib import Path
import re
import sys

from project import config

MAX_FILES = 200


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def files(path):
    path = Path(path)
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob('*') if p.is_file() and '__pycache__' not in p.parts)[:MAX_FILES]


def declared(plan):
    return config(plan).get('imports', '').split()


def resolve(root, item):
    path = Path(item)
    return Path(os.path.realpath(path if path.is_absolute() else Path(root) / path))


def freeze_lines(root, plan):
    root = Path(root).resolve()
    lines, problems = [], []
    for item in declared(plan):
        path = resolve(root, item)
        if root not in path.parents:
            problems.append(f'{item} is outside the project')
        elif not path.exists():
            problems.append(f'{item} does not exist')
        else:
            lines += [f'import {sha(f)} {f.relative_to(root)}' for f in files(path)]
    return lines, problems


def script_lines(root, owner):
    """`script <sha256> <path>` for every file under OWNER/scripts/ at the freeze."""
    root, scripts = Path(root).resolve(), Path(owner).resolve() / 'scripts'
    return [f'script {sha(f)} {f.relative_to(root)}' for f in (files(scripts) if scripts.is_dir() else [])]


def pinned_changes(root, owner):
    """Pinned scripts that changed or vanished since the freeze: [relative path (+ ' (missing)')]."""
    record = Path(owner) / 'PREDECLARATION.sha256'
    out = []
    for line in (record.read_text().splitlines()[2:] if record.is_file() else []):
        parts = line.split(' ', 2)
        if len(parts) == 3 and parts[0] == 'script':
            path = Path(root) / parts[2]
            if not path.is_file():
                out.append(parts[2] + ' (missing)')
            elif sha(path) != parts[1]:
                out.append(parts[2])
    return out


def frozen(record):
    """{relative path: sha256} from the import lines of a PREDECLARATION.sha256."""
    out = {}
    for line in Path(record).read_text().splitlines()[2:]:
        parts = line.split(' ', 2)
        if len(parts) == 3 and parts[0] == 'import':
            out[parts[2]] = parts[1]
    return out


def check(root, owner, plan):
    """(hashes now, problems). Declared imports must match their frozen hashes; a plan frozen before
    imports were recorded is hashed now and says so."""
    root = Path(root).resolve()
    record = Path(owner) / 'PREDECLARATION.sha256'
    want = frozen(record)
    now, problems = {}, []
    if declared(plan) and not want:
        problems.append('warn:the plan declares imports but was frozen before their hashes were recorded; '
                        'they are hashed now, not at the freeze')
    for item in declared(plan):
        path = resolve(root, item)
        for f in (files(path) if path.exists() else []):
            now[str(f.relative_to(root))] = sha(f)
        if not path.exists():
            problems.append(f'declared import {item} no longer exists')
    for rel, digest in want.items():
        if now.get(rel) != digest:
            problems.append(f'declared import {rel} changed since the pre-declaration was frozen')
    return now, problems


def referenced(root, owner, texts, iterations_dir, verification_dir):
    """{relative path: sha256} of other owners' scripts that the given texts name."""
    root, owner = Path(root).resolve(), Path(owner).resolve()
    pattern = re.compile(r'(?:%s/iteration\d+|%s/[\w.\-]+)/scripts(?:/[\w.\-/]+)?'
                         % (re.escape(iterations_dir), re.escape(verification_dir)))
    found = {}
    for text in texts:
        try:
            body = Path(text).read_text(errors='replace')
        except (OSError, UnicodeDecodeError):
            continue
        for match in sorted(set(pattern.findall(body))):
            path = Path(os.path.realpath(root / match.rstrip('/.')))
            if root not in path.parents or owner in path.parents or not path.exists():
                continue
            for f in files(path):
                found[str(f.relative_to(root))] = sha(f)
    return found


if __name__ == '__main__':
    if sys.argv[1] == 'scripts':
        print('\n'.join(script_lines(sys.argv[2], sys.argv[3])))
    elif sys.argv[1] == 'changed':                # changed ROOT DIR: pinned scripts edited since the freeze
        print('\n'.join(pinned_changes(sys.argv[2], sys.argv[3])))
    elif sys.argv[1] == 'freeze':
        lines, problems = freeze_lines(sys.argv[2], sys.argv[3])
        if problems:
            print('\n'.join('declared import ' + p for p in problems), file=sys.stderr)
            sys.exit(1)
        print('\n'.join(lines))
    else:
        sys.exit(f'unknown command: {sys.argv[1]}')
