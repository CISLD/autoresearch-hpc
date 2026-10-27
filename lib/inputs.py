"""Format-aware integrity checks of declared inputs, recorded so run receipts can cite them (stdlib only).

A truncated ONT CRAM on a shared input volume made a caller write calls for chr1-10 only while
exiting 0, and a study's truth set silently lost 60% of one sample's events (2026-10-04). The file
had no CRAM end-of-file container. Nothing checked the integrity of immutable inputs.

The default checks are constant-time: the end-of-file marker of a BGZF file (BAM, BCF, bgzipped VCF
or BED, .bgz, tabix and CSI indices) and of a CRAM 3 file. `--deep` also decompresses every gzip
file to verify its CRCs. Results are appended to .arh/inputs/checks.jsonl; a file whose size and
modification time match an earlier passing check is not read again unless --force is given.

  inputs.py check ROOT [--deep] [--force] [PATH...]   check PATHs, or every declared input; exit 1 on a failure
  inputs.py summary ROOT                               JSON: the latest result per file, for a run receipt
"""
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import zlib

from project import config

BGZF_EOF = bytes.fromhex('1f8b08040000000000ff0600424302001b0003000000000000000000')
CRAM3_EOF = bytes.fromhex('0f000000ffffffff0fe0454f4600000000010005bdd94f0001000606010001000100ee63014b')
BGZF_SUFFIXES = ('.bam', '.bcf', '.bgz', '.tbi', '.csi')
MAX_FILES = 20000


def declared(root):
    root = Path(root)
    out = []
    for item in config(root / '.arh/config/project.md').get('immutable_inputs', '').split():
        path = Path(item)
        out.append(path if path.is_absolute() else root / path)
    return out


def kind(path):
    name = path.name.lower()
    if name.endswith('.cram'):
        return 'cram'
    if name.endswith(BGZF_SUFFIXES):
        return 'bgzf'
    if name.endswith('.gz'):
        return 'gzip'
    return None


def tail(path, n):
    with open(path, 'rb') as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - n))
        return handle.read()


def is_bgzf(path):
    with open(path, 'rb') as handle:
        head = handle.read(16)
    return len(head) >= 16 and head[:4] == b'\x1f\x8b\x08\x04' and head[12:14] == b'BC'


def check_file(path, deep):
    """(ok, detail) for one file."""
    k = kind(path)
    try:
        if k == 'cram':
            with open(path, 'rb') as handle:
                head = handle.read(6)
            if head[:4] != b'CRAM':
                return False, 'not a CRAM file (no CRAM magic)'
            if head[4] < 3:
                return True, f'CRAM {head[4]}.x: no end-of-file check for this version'
            ok = tail(path, 38) == CRAM3_EOF
            return ok, 'CRAM end-of-file container ' + ('present' if ok else 'missing: truncated')
        if k == 'bgzf' or (k == 'gzip' and is_bgzf(path)):
            ok = tail(path, 28) == BGZF_EOF
            detail = 'BGZF end-of-file block ' + ('present' if ok else 'missing: truncated')
            if ok and deep:
                ok, detail = inflate(path)
            return ok, detail
        if k == 'gzip':
            return inflate(path) if deep else (True, 'plain gzip: no end marker to check (use --deep)')
    except OSError as error:
        return False, f'unreadable: {error.strerror or error}'
    return True, 'no check for this format'


def inflate(path):
    try:
        with gzip.open(path, 'rb') as handle:
            while handle.read(1 << 22):
                pass
        return True, 'decompressed completely; CRCs match'
    except (OSError, EOFError, zlib.error) as error:
        return False, f'decompression failed: {error}'


def candidates(paths):
    out = []
    for path in paths:
        path = Path(path)
        if path.is_file():
            out.append(path)
        elif path.is_dir():
            for dirpath, _, names in os.walk(path):
                out += [Path(dirpath) / n for n in sorted(names) if kind(Path(n))]
                if len(out) >= MAX_FILES:
                    print(f'arh: stopped after {MAX_FILES} files; name narrower paths to check the rest', file=sys.stderr)
                    return out[:MAX_FILES]
    return out


def log_path(root):
    return Path(root) / '.arh/inputs/checks.jsonl'


def history(root):
    """{path: latest record}."""
    latest = {}
    log = log_path(root)
    for line in (log.read_text().splitlines() if log.is_file() else []):
        try:
            record = json.loads(line)
            latest[record['path']] = record
        except (ValueError, KeyError):
            continue
    return latest


def check(root, paths, deep, force):
    root = Path(root)
    files = candidates(paths or declared(root))
    earlier = history(root)
    log = log_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    failed = checked = cached = 0
    with open(log, 'a') as out:
        for f in files:
            real = os.path.realpath(f)
            stat = os.stat(real)
            before = earlier.get(real)
            if (not force and before and before.get('ok') and before.get('size') == stat.st_size
                    and before.get('mtime') == int(stat.st_mtime) and (before.get('deep') or not deep)):
                cached += 1
                continue
            ok, detail = check_file(Path(real), deep)
            checked += 1
            failed += not ok
            out.write(json.dumps(dict(time=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), path=real,
                                      size=stat.st_size, mtime=int(stat.st_mtime), kind=kind(Path(real)),
                                      deep=deep, ok=ok, detail=detail)) + '\n')
            if not ok:
                print(f'FAIL {real}: {detail}')
    print(f'{checked} checked, {cached} unchanged since an earlier pass, {failed} failed'
          + (f' (log: {log.relative_to(root)})' if checked else ''))
    return 1 if failed else 0


def summary(root):
    """For a run receipt: the log's hash, and how many files under the declared (immutable or sealed)
    inputs were checked and which of them failed. Files checked by explicit path elsewhere are left out."""
    latest = history(root)
    log = log_path(root)
    from freeze import sealed_inputs
    bases = [os.path.realpath(p) for p in declared(root)] + [str(p) for p in sealed_inputs(root)]
    mine = {p: r for p, r in latest.items() if any(p == b or p.startswith(b.rstrip('/') + '/') for b in bases)}
    if not mine:
        return None
    return dict(log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(), checked=len(mine),
                failed=sorted(p for p, r in mine.items() if not r.get('ok')))


if __name__ == '__main__':
    if sys.argv[1] == 'check':
        args = sys.argv[3:]
        flags = {a for a in args if a in ('--deep', '--force')}
        sys.exit(check(sys.argv[2], [a for a in args if a not in flags], '--deep' in flags, '--force' in flags))
    elif sys.argv[1] == 'summary':
        print(json.dumps(summary(sys.argv[2])))
    else:
        sys.exit(f'unknown command: {sys.argv[1]}')
