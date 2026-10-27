"""Write-once freezes of decision artefacts, and sealed inputs only a frozen confirmation may read.

A confirmation scores held-out data once, with a configuration chosen without it. Studies hand-wrote
the guard for that, and a hand-written guard binds only what its author remembered: one hashed the
model file but not the thresholds file that carried the decision rule (2026-09-12). Nothing stopped
an earlier iteration from opening the held-out data, either.

  freeze.py create ROOT DIR AGENT PATH...   write DIR/FREEZE.json; refuses a second freeze
  freeze.py check ROOT DIR                  exit 0 when every frozen file still matches
  freeze.py list ROOT ITERATIONS            one line per iteration with a freeze, then sealed-input use
  freeze.py sealed ROOT                     the declared sealed paths, one per line
  freeze.py referenced ROOT TEXTFILE...     sealed paths named in the given files (a run that is not
                                            allowed to read them must not name them either)
  freeze.py masks ROOT                      SOURCE:TARGET binds that cover each sealed path with an
                                            empty one, for runs that may not read it
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from project import config

SKIP = ('__pycache__', '.nextflow')


def sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def within(path, base):
    return path == base or base in path.parents


def sealed_groups(root):
    """{group: [paths]} of the declared sealed inputs, absolute and resolved, in declaration order.

    `sealed_inputs` is the group `default`; `sealed_inputs_<group>` declares another, so two held-out
    sets can be released separately: one freeze unsealed every sealed path at once, and a second
    held-out set could not be kept from the first set's confirmation (field feedback #78). Either key
    with the suffix `_file` names a file listing one path per line, for lists too long for one line
    (27 paths, #46)."""
    root = Path(root)
    values = config(root / '.arh/config/project.md')
    groups = {}
    for key, value in values.items():
        match = re.fullmatch(r'sealed_inputs(?:_(\w+?))?(_file)?', key)
        if not match or not value:
            continue
        group = match.group(1) or 'default'
        if match.group(2):
            listed = Path(value) if Path(value).is_absolute() else root / value
            items = [line.split('#', 1)[0].strip() for line in listed.read_text().splitlines()] if listed.is_file() else []
        else:
            items = value.split()
        for item in filter(None, items):
            path = Path(item)
            groups.setdefault(group, []).append(Path(os.path.realpath(path if path.is_absolute() else root / path)))
    return groups


def sealed_inputs(root):
    """Every declared sealed path, absolute and resolved, in declaration order."""
    out = []
    for paths in sealed_groups(root).values():
        out += [p for p in paths if p not in out]
    return out


def unsealed(root, directory):
    """The sealed paths a run of DIRECTORY may read: those of the groups its valid freeze names."""
    if state(root, directory)[0] != 'valid':
        return []
    try:
        named = json.loads((Path(directory) / 'FREEZE.json').read_text()).get('unseals')
    except (OSError, ValueError):
        return []
    groups = sealed_groups(root)
    out = []
    for group in (groups if named is None else named):     # freezes before groups unsealed everything
        out += [p for p in groups.get(group, []) if p not in out]
    return out


def files_under(path):
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob('*') if p.is_file() and not any(part in SKIP for part in p.parts))


def state(root, directory):
    """('none', None, []) without a freeze; ('valid', record sha, []) when every frozen file matches;
    ('changed', record sha, [paths]) otherwise."""
    record = Path(directory) / 'FREEZE.json'
    if not record.is_file():
        return 'none', None, []
    try:
        data = json.loads(record.read_text())
        files = data['files']
    except (ValueError, KeyError, TypeError):
        return 'changed', sha(record), ['FREEZE.json is not a freeze record']
    changed = []
    for rel, want in sorted(files.items()):
        path = Path(root) / rel
        if not path.is_file():
            changed.append(rel + ' (missing)')
        elif sha(path) != want:
            changed.append(rel)
    return ('changed' if changed else 'valid'), sha(record), changed


def create(root, directory, agent, paths, unseal=None):
    root, directory = Path(root).resolve(), Path(directory).resolve()
    readme, frozen = directory / 'README.md', directory / 'PREDECLARATION.sha256'
    if not frozen.is_file() or frozen.read_text().splitlines()[0] != sha(readme):
        sys.exit('arh: freeze the pre-declaration first (arh gate predeclare); a freeze applies a declared plan')
    record = directory / 'FREEZE.json'
    if record.exists():
        sys.exit(f'arh: {record.relative_to(root)} already exists; a freeze is written once. '
                 'A different configuration is a new iteration.')
    sealed = sealed_inputs(root)
    groups = sealed_groups(root)
    if unseal is None:
        if len(groups) > 1:
            sys.exit('arh: several sealed groups are declared (' + ', '.join(groups) + '); name the one(s) this '
                     'confirmation may read with --unseal GROUP[,GROUP]')
        unseal = list(groups)
    unknown = [g for g in unseal if g not in groups]
    if unknown:
        sys.exit('arh: no sealed group ' + ', '.join(unknown) + ' (declared: ' + (', '.join(groups) or 'none') + ')')
    files = {}
    for given in paths:
        path = Path(os.path.realpath(given))
        if not path.exists():
            sys.exit(f'arh: no such file or directory: {given}')
        if any(within(path, s) or within(s, path) for s in sealed):
            sys.exit(f'arh: {given} is or contains a sealed input; a freeze binds decisions, not held-out data')
        if not within(path, root):
            sys.exit(f'arh: {given} is outside the project; copy the decision artefact into an iteration first')
        for f in files_under(path):
            files[str(f.relative_to(root))] = sha(f)
    if not files:
        sys.exit('arh: nothing to freeze: name the files (or directories) the confirmation applies')
    data = dict(schema='arh-freeze-v1', iteration=int(directory.name[9:]) if directory.name[9:].isdigit() else None,
                frozen=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), agent=agent,
                predeclaration_sha256=sha(readme), files=files,
                sealed_inputs=[str(s) for s in sealed], unseals=unseal)
    with open(record, 'x') as handle:          # write-once, even against a concurrent freeze
        json.dump(data, handle, indent=2)
        handle.write('\n')
    print(f'froze {len(files)} file(s) in {record.relative_to(root)} ({sha(record)[:12]})')
    for rel in files:
        print(f'  {files[rel][:12]}  {rel}')
    if unseal:
        print('A run of this iteration may now read the sealed group(s) ' + ', '.join(unseal)
              + '; each read is recorded in .arh/unseals.tsv.')


def unseals(root):
    log = Path(root) / '.arh/unseals.tsv'
    if not log.is_file():
        return []
    rows = [line.split('\t') for line in log.read_text().splitlines()[1:] if line.strip()]
    return [r for r in rows if len(r) >= 6]


def listing(root, iterations):
    root, base = Path(root), Path(iterations)
    dirs = sorted((p for p in base.glob('iteration*') if p.name[9:].isdigit()), key=lambda p: int(p.name[9:]))
    shown = False
    for d in dirs:
        st, digest, changed = state(root, d)
        if st == 'none':
            continue
        shown = True
        try:
            data = json.loads((d / 'FREEZE.json').read_text())
        except ValueError:
            data = {}
        print(f"{d.name[9:]:<5} {data.get('frozen', '?'):<21} {len(data.get('files', {})):>4} file(s)  "
              f"{'frozen' if st == 'valid' else 'CHANGED: ' + ', '.join(changed[:3])}")
    if not shown:
        print('(no freezes yet — arh freeze -n N FILE...)')
    groups = sealed_groups(root)
    if groups:
        print('\nsealed inputs:')
        rows = unseals(root)
        for group, paths in groups.items():
            for s in paths:
                print(f"  {s}{'' if len(groups) == 1 else f' [{group}]'}  — {reads_text(rows, s)}")


def reads_text(rows, path):
    """'read by iteration(s) 34, 55; before the seal by 9, 27' or 'never read'."""
    rows = [r for r in rows if r[4] == str(path)]
    after = sorted({r[1] for r in rows if r[2] != PRESEAL}, key=int)
    before = sorted({r[1] for r in rows if r[2] == PRESEAL}, key=int)
    parts = ([f"read by iteration(s) {', '.join(after)}"] if after else []) + (
        [f"read before the seal by iteration(s) {', '.join(before)}"] if before else [])
    return '; '.join(parts) or 'never read'


PRESEAL = 'pre-seal'


def record_preseal(root, iteration, reason, paths):
    """Reads that happened before a path was sealed. The HG002 truth set was sealed after six
    iterations had read it, and every listing said 'never read' (field feedback #45). The operator
    records them; the row says when it was recorded and why."""
    sealed = sealed_inputs(root)
    chosen = [Path(os.path.realpath(p)) for p in paths] if paths else sealed
    unknown = [str(p) for p in chosen if p not in sealed]
    if unknown:
        sys.exit('arh: not a sealed input: ' + ', '.join(unknown))
    if len(reason.split()) < 3:
        sys.exit('arh: give the reason: which read, when, and how it is known')
    log = Path(root) / '.arh/unseals.tsv'
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(log, 'a') as handle:
        if handle.tell() == 0:
            handle.write('time\titeration\trun\tattempt\tpath\tfreeze_sha256\n')
        for path in chosen:
            handle.write(f"{stamp}\t{iteration}\t{PRESEAL}\t-\t{path}\t-\t{reason.replace(chr(9), ' ')}\n")
    print(f'recorded {len(chosen)} read(s) before the seal by iteration {iteration}')


def references(root, files, only=None):
    """[(file, sealed path)] for each sealed input a file names, as declared or as resolved."""
    sealed = only if only is not None else sealed_inputs(root)
    root = Path(root)
    declared = [item for key, value in config(root / '.arh/config/project.md').items()
                if re.fullmatch(r'sealed_inputs(_\w+?)?', key) for item in value.split()]
    declared = [d for d in declared if Path(os.path.realpath(d if Path(d).is_absolute() else root / d)) in sealed]
    names = set(declared) | {str(s) for s in sealed}
    found = []
    for f in files:
        try:
            text = Path(f).read_text(errors='replace')
        except (OSError, UnicodeDecodeError):
            continue
        found += [(str(f), name) for name in sorted(names) if name and name in text]
    return found


def record_unseal(root, iteration, run, attempt, paths, freeze_sha):
    """Append one row per sealed path a confirmation run is about to read."""
    log = Path(root) / '.arh/unseals.tsv'
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(log, 'a') as handle:
        if handle.tell() == 0:
            handle.write('time\titeration\trun\tattempt\tpath\tfreeze_sha256\n')
        for path in paths:
            handle.write(f'{stamp}\t{iteration}\t{run}\t{attempt}\t{path}\t{freeze_sha}\n')


def masks(root, only=None):
    """(source, target) binds that cover each existing sealed path (or each of ONLY) with an empty one."""
    base = Path(root) / '.arh/sealed'
    empty_dir, empty_file = base / 'empty', base / 'empty-file'
    out = []
    for s in (sealed_inputs(root) if only is None else only):
        if not s.exists():
            continue
        if s.is_dir():
            empty_dir.mkdir(parents=True, exist_ok=True)
            out.append((empty_dir, s))
        else:
            base.mkdir(parents=True, exist_ok=True)
            empty_file.touch()
            out.append((empty_file, s))
    return out


def doctor(root):
    """OK|, WARN| and FAIL| lines about the sealed-input declaration."""
    root = Path(root).resolve()
    out = []
    immutable = []
    for item in config(root / '.arh/config/project.md').get('immutable_inputs', '').split():
        path = Path(item)
        immutable.append(Path(os.path.realpath(path if path.is_absolute() else root / path)))
    for s in sealed_inputs(root):
        if within(root, s):
            out.append(f'FAIL|sealed input {s} contains the project itself')
        elif any(within(i, s) for i in immutable):
            out.append(f'FAIL|an immutable input lies inside sealed input {s}; its mount would be hidden. '
                       'Declare the immutable input more narrowly')
        elif not s.exists():
            out.append(f'WARN|sealed input {s} does not exist')
        else:
            out.append(f"OK|sealed: {s} ({reads_text(unseals(root), s)})")
    return out


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'create':                          # create ROOT DIR AGENT UNSEAL|- PATH...
        create(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[6:],
               None if sys.argv[5] == '-' else [g for g in sys.argv[5].split(',') if g])
    elif cmd == 'preseal':                       # preseal ROOT ITERATION REASON [PATH...]
        record_preseal(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:])
    elif cmd == 'has-sealed':
        sys.exit(0 if sealed_groups(sys.argv[2]) else 1)
    elif cmd == 'check':
        st, digest, changed = state(sys.argv[2], sys.argv[3])
        if st == 'none':
            sys.exit('arh: no FREEZE.json')
        if st == 'changed':
            print('frozen file(s) changed since the freeze: ' + ', '.join(changed))
            sys.exit(1)
        print(f'every frozen file matches FREEZE.json ({digest[:12]})')
    elif cmd == 'list':
        listing(sys.argv[2], sys.argv[3])
    elif cmd == 'sealed':
        print('\n'.join(map(str, sealed_inputs(sys.argv[2]))))
    elif cmd == 'referenced':
        for f, name in references(sys.argv[2], sys.argv[3:]):
            print(f'{f}\t{name}')
    elif cmd == 'doctor':
        print('\n'.join(doctor(sys.argv[2])))
    elif cmd == 'masks':                         # masks ROOT: SOURCE:TARGET per sealed path
        for source, target in masks(sys.argv[2]):
            print(f'{source}:{target}')
    else:
        sys.exit(f'unknown command: {cmd}')
