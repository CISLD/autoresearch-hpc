"""`arh context` without -n: the session-start brief, bounded and read-only (no model call).

The contract used to send every session to PROGRESS.md, DIRECTIVES.md and GOTCHAS.md in full. In a
63-iteration field study that was 329 kB (about 80k tokens by a bytes/4 estimate) before any work,
and the ledger alone grows with every iteration. The brief prints what a session needs to start:

  1. PROGRESS.md's `## Current state` section (kept by the agents), or its heading index if absent;
  2. the iterations still open, with their holders;
  3. the directives: binding, so in full, unless the file has a `## Current directives` section
     (then that section in full, and an index of the rest);
  4. an index of GOTCHAS.md: each entry's heading and its Assertion line, opened on demand.

  brief.py ROOT ITERATIONS LIMIT_BYTES
"""
import re
import sys
from pathlib import Path

from lease import open_iterations
from project import config, knowledge


def section(text, title):
    """The body of the `## <title>` section, or None."""
    found = re.search(rf'(?ms)^## {re.escape(title)}[ \t]*\n(.*?)(?=^## |\Z)', text)
    return found.group(1).strip() if found else None


def current_directives(text):
    """The `## Current directives` section when it states something. The template ships the heading
    with a placeholder; an unfilled one must not hide the dated directives under it, so it counts
    as absent and the whole file stays a required read."""
    body = section(text, 'Current directives')
    if body is None:
        return None
    body = re.sub(r'(?ms)<!--.*?-->|^\s*<[^>]*>[ \t]*$', '', body).strip()   # comments and <placeholder> blocks
    return body or None


def headings(text, levels='##', fields=()):
    """One line per heading of the given levels, with the first line of each named field under it."""
    out = []
    pattern = rf'(?ms)^({levels}) (.+?)\n(.*?)(?=^#{{2,3}} |\Z)'
    for _, title, body in re.findall(pattern, text):
        if title.startswith(('<', 'Example')):
            continue
        extra = []
        for name in fields:
            hit = re.search(rf'(?mi)^\*\*{name}:?\*\*:?\s*(.+)$', body)
            if hit and not hit.group(1).startswith('```'):
                extra.append(f'{name}: {hit.group(1).strip()[:140]}')
        out.append(f'- {title.strip()[:100]}' + (f' — {"; ".join(extra)}' if extra else ''))
    return out


def main(root, iterations, limit):
    root, limit = Path(root), int(limit)
    files = knowledge(root)
    parts = []

    ledger = root / config(root / '.arh/config/project.md').get('ledger', 'PROGRESS.md')
    text = ledger.read_text(errors='replace') if ledger.is_file() else ''
    state = section(text, 'Current state')
    if state:
        parts.append(f'## Current state ({ledger.name})\n\n{state}')
    else:
        parts.append(f'## {ledger.name} has no "## Current state" section\n\nAdd one and keep it current: '
                     'it is what a resuming session reads. Its headings, for opening what you need:\n'
                     + '\n'.join(headings(text, '#{2,3}')))

    parts.append('## Open iterations (arh status for all; arh context -n N for one)\n')
    from io import StringIO
    import contextlib
    held = StringIO()
    with contextlib.redirect_stdout(held):
        open_iterations(iterations, float(config(root / '.arh/config/project.md').get('lease_stale_hours') or 24))
    parts[-1] += held.getvalue().rstrip() or '  none'

    directives = files.get('DIRECTIVES.md')
    if directives:
        body = directives.read_text(errors='replace')
        current = current_directives(body)
        name = directives.name
        if current:
            parts.append(f'## Current directives ({name}; binding)\n\n{current}\n\nOther entries in {name} '
                         '(reference; open the ones your task touches):\n'
                         + '\n'.join(headings(body, '###', ('Applies to', 'Directive'))))
        else:
            # Directives are binding, so they are never cut or indexed away: without a current section the
            # whole file is a required read. A `## Current directives` section keeps that read short.
            parts.append(f'## Directives: read {directives} in full before designing anything ({len(body)} bytes; '
                         'binding). A "## Current directives" section that states every directive still in force '
                         'would let this brief carry it instead.')

    gotchas = files.get('GOTCHAS.md')
    if gotchas:
        body = gotchas.read_text(errors='replace')
        parts.append(f'## Gotchas index ({gotchas.name}: open every entry about a tool, input or step your task '
                     'uses)\n\n' + '\n'.join(headings(body, '##', ('Assertion', 'Symptom'))))

    out = '\n\n'.join(parts) + '\n'
    if len(out.encode()) > limit:          # never inside the current directives: they come before the indexes
        cut = out.encode()[:limit].decode(errors='ignore')
        out = cut + f'\n\n[brief truncated at context_max_bytes = {limit}; the files above are complete on disk]\n'
    sys.stdout.write(out)


if __name__ == '__main__':
    if sys.argv[1] == 'current-directives':         # current-directives FILE: the section, or exit 1
        found = current_directives(Path(sys.argv[2]).read_text(errors='replace'))
        if not found:
            sys.exit(1)
        print(found)
    else:
        main(*sys.argv[1:4])
