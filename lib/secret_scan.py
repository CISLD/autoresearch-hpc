"""Refuse to send text that looks like a credential to an external model service (stdlib only).

`arh ask`, `arh delegate` and `arh evoke` send a pre-declaration, a report or a task to a provider.
A credential pasted into any of them leaves the site with it, and a provider may log or retain the
request. A 2026 measurement of agents on a production cluster counted 127 exposed API keys in three
weeks. The patterns are high-precision token shapes; a false positive is cleared by removing the
text or, for a project that has a reason, with `secret_scan = off` in harnesses.md.

The built-in patterns are a floor, not a maintained rule set. When gitleaks
(https://github.com/gitleaks/gitleaks) is installed, its maintained rules are applied as well
(`secret_scanner = auto`, the default; `gitleaks` requires it, `builtin` skips it), so a new key
format is caught without ARH tracking it.

  secret_scan.py scan FILE...     one line per finding (file:line: kind: redacted match); exit 1 if any
  secret_scan.py redact FILE...   replace every finding in place with [REDACTED kind]; print the count
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

PATTERNS = (
    ('private key', re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY(?: BLOCK)?-----')),
    ('AWS access key', re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b')),
    ('GitHub token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b')),
    ('Anthropic API key', re.compile(r'\bsk-ant-[A-Za-z0-9_\-]{20,}')),
    ('OpenAI-style API key', re.compile(r'\bsk-(?!ant-)(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,}')),
    ('Google API key', re.compile(r'\bAIza[0-9A-Za-z_\-]{35}\b')),
    ('Slack token', re.compile(r'\bxox[abposr]-[A-Za-z0-9-]{10,}')),
    ('Hugging Face token', re.compile(r'\bhf_[A-Za-z0-9]{30,}\b')),
    ('JSON web token', re.compile(r'\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}')),
    ('assigned secret', re.compile(r'(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd)'
                                   r'\b["\']?\s*[:=]\s*["\'][^"\'\s]{12,}["\']')),
)


def redact(text):
    return text[:6] + '…' + f'({len(text)} chars)'


def gitleaks():
    """The gitleaks executable to use, or None. Exits when secret_scanner = gitleaks and it is missing."""
    mode = os.environ.get('ARH_SECRET_SCANNER', 'auto') or 'auto'
    if mode == 'builtin':
        return None
    found = shutil.which('gitleaks')
    if mode == 'gitleaks' and not found:
        print('arh: secret_scanner = gitleaks, but gitleaks is not on PATH (https://github.com/gitleaks/gitleaks)',
              file=sys.stderr)
        sys.exit(2)
    return found


def leaks(path):
    """[(line, rule, secret)] that gitleaks finds in PATH; [] without gitleaks."""
    exe = gitleaks()
    if not exe:
        return []
    with tempfile.TemporaryDirectory() as work:
        report = os.path.join(work, 'report.json')
        try:
            subprocess.run([exe, 'dir', str(path), '--no-banner', '--report-format', 'json', '--report-path', report,
                            '--exit-code', '0'], capture_output=True, timeout=120)
            data = json.load(open(report))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return []
    return [(f.get('StartLine'), f.get('RuleID', 'gitleaks'), f.get('Secret', '')) for f in data or [] if f.get('Secret')]


def findings(path):
    """[(line, kind, matched text)] from the built-in patterns and, when installed, gitleaks."""
    found = []
    try:
        lines = open(path, errors='replace').read().splitlines()
    except OSError:
        return found
    for number, line in enumerate(lines, 1):
        for kind, pattern in PATTERNS:
            match = pattern.search(line)
            if match:
                found.append((number, kind, match.group(0)))
                break
    seen = {(n, text) for n, _, text in found}
    found += [(n, f'gitleaks: {rule}', text) for n, rule, text in leaks(path) if (n, text) not in seen]
    return sorted(found, key=lambda f: f[0] or 0)


def scan(path):
    return [f'{path}:{number}: {kind}: {redact(text)}' for number, kind, text in findings(path)]


def redact_file(path):
    """Replace every finding in PATH with [REDACTED kind]; return how many were replaced."""
    try:
        text = open(path, errors='replace').read()
    except OSError:
        return 0
    count = 0
    for kind, pattern in PATTERNS:
        text, k = pattern.subn(f'[REDACTED {kind}]', text)
        count += k
    for _, rule, secret in leaks(path):
        if secret in text:
            count += text.count(secret)
            text = text.replace(secret, f'[REDACTED gitleaks: {rule}]')
    if count:
        open(path, 'w').write(text)
    return count


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in ('scan', 'redact'):
        sys.exit(__doc__)
    if sys.argv[1] == 'redact':
        print(sum(redact_file(path) for path in sys.argv[2:]))
        sys.exit(0)
    hits = [hit for path in sys.argv[2:] for hit in scan(path)]
    print('\n'.join(hits))
    sys.exit(1 if hits else 0)
