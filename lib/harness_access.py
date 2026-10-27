"""Harness-side access for a project: reach the declared inputs, and web tools as declared (stdlib only).

A harness may enforce its own boundary at the project root while the declared immutable inputs
sit outside it. Headless, OpenCode rejected such a read instead of asking, so a producer could
not read its own data and nothing named the cause (2026-09-16). Web tools are the other side of
the same boundary: with web_access = deny, a producer must not be able to look results up.

  harness_access.py write ROOT HARNESS WEB_ACCESS [INPUT...]   add entries to the harness config
  harness_access.py check ROOT WEB_ACCESS [INPUT...]           print FAIL|... / WARN|... lines
"""
import json
import os
from pathlib import Path
import re
import sys

WEB = ('WebFetch', 'WebSearch')


def outside(root, inputs):
    """Declared inputs that resolve outside the project root."""
    root = os.path.realpath(root)
    for p in inputs:
        p = os.path.realpath(p if os.path.isabs(p) else os.path.join(root, p))
        if p != root and not p.startswith(root + os.sep):
            yield p


def load(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')


def within(path, base):
    base = base.rstrip('/')
    return path == base or path.startswith(base + '/')


def sealed(root):
    """Declared sealed inputs, resolved; the harness should not read them either."""
    from freeze import sealed_inputs
    return [str(p) for p in sealed_inputs(root)]


def write(root, harness, web, inputs):
    root = Path(root)
    ext = sorted(set(outside(root, inputs)))
    held = sealed(root)
    if harness == 'claude':
        path = root / '.claude/settings.json'
        cfg = load(path)
        perm = cfg.setdefault('permissions', {})
        if ext:
            perm['additionalDirectories'] = sorted(set(perm.get('additionalDirectories', [])) | set(ext))
        if web == 'deny':   # a bare tool name removes the tool from the session entirely
            perm['deny'] = sorted(set(perm.get('deny', [])) | set(WEB))
        if held:            # `//` anchors a Claude Code path rule at the filesystem root
            perm['deny'] = sorted(set(perm.get('deny', [])) | {f'Read(/{p}/**)' for p in held} | {f'Read(/{p})' for p in held})
        if perm:
            save(path, cfg)
    elif harness == 'opencode':
        path = root / 'opencode.json'
        cfg = load(path)
        perm = cfg.setdefault('permission', {})
        if ext or held:
            allowed = perm.setdefault('external_directory', {})
            for p in ext:
                allowed[p] = allowed[p + '/**'] = 'allow'
            for p in held:
                allowed[p] = allowed[p + '/**'] = 'deny'
        if web == 'deny':
            perm.update(webfetch='deny', websearch='deny')
        if not perm:
            del cfg['permission']
        save(path, cfg)
    # Codex: its workspace-write sandbox reads anywhere, and web search is off unless enabled.


def check(root, web, inputs):
    root = Path(root)
    ext = sorted(set(outside(root, inputs)))
    out = []
    oc = root / 'opencode.json'
    if oc.is_file():
        perm = load(oc).get('permission', {})
        allowed = perm.get('external_directory', {})
        allowed = allowed if isinstance(allowed, dict) else {'*': allowed}
        bases = [re.sub(r'/\*\*?$', '', k) for k, v in allowed.items() if v == 'allow']
        for p in ext:
            if not any(b == '*' or within(p, b) for b in bases):
                out.append(f'FAIL|opencode.json does not allow the declared input {p}: a headless '
                           'session rejects the read instead of asking')
        if web == 'deny':
            out += [f'FAIL|opencode.json leaves {t} on although web_access = deny'
                    for t in ('webfetch', 'websearch') if perm.get(t) != 'deny']
        out += [f'WARN|opencode.json does not deny reading the sealed input {p}'
                for p in sealed(root) if allowed.get(p + '/**') != 'deny']
    held = sealed(root)
    if (root / '.claude').is_dir():
        perm = load(root / '.claude/settings.json').get('permissions', {})
        out += [f'WARN|.claude/settings.json does not deny reading the sealed input {p}'
                for p in held if f'Read(/{p}/**)' not in perm.get('deny', [])]
        dirs = perm.get('additionalDirectories', [])
        out += [f'WARN|.claude/settings.json does not list the declared input {p} in additionalDirectories'
                for p in ext if not any(within(p, d) for d in dirs)]
        if web == 'deny':
            missing = [t for t in WEB if t not in perm.get('deny', [])]
            if missing:
                out.append(f"FAIL|.claude/settings.json does not deny {' or '.join(missing)} although web_access = deny")
    cx = root / '.codex/config.toml'
    if web == 'deny' and cx.is_file() and re.search(r'web_search\w*\s*=\s*(true|"(live|cached)")', cx.read_text()):
        out.append('FAIL|.codex/config.toml turns web search on although web_access = deny')
    if web == 'deny' and not (oc.is_file() or (root / '.claude').is_dir() or cx.is_file()):
        out.append('WARN|web_access = deny, but no harness configuration is installed to check')
    return out


if __name__ == '__main__':
    if sys.argv[1] == 'write':
        write(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:])
    else:
        print('\n'.join(check(sys.argv[2], sys.argv[3], sys.argv[4:])))
