"""Generate a bounded handoff from files without a model call."""
import json
import os
from pathlib import Path
import re
import sys
from harness import digest, valid_records
from project import knowledge
from freeze import state as freeze_state
from memory import index as memory_index

n = sys.argv[1]
if not n.isdigit():
    sys.exit('iteration must be numeric')
directory = Path(os.environ['ARH_ITERS']) / ('iteration' + n)
if not directory.is_dir():
    sys.exit('iteration does not exist')
readme = directory / 'README.md'
freeze = directory / 'PREDECLARATION.sha256'
report = directory / 'results/report' / ('iteration' + n + '_report.md')
state = dict(iteration=int(n), predeclaration='none', report=str(report) if report.exists() else None,
             reviews=[], latest_run=None, sections={}, truncated=False)
if readme.exists():
    state['predeclaration'] = ('frozen' if freeze.read_text().splitlines()[0] == digest(readme) else 'ALTERED') if freeze.exists() else 'draft'
    for heading, body in re.findall(r'^## ([^\n]+)\n(.*?)(?=^## |\Z)', readme.read_text(), re.M | re.S):
        if any(term in heading.lower() for term in ('question', 'estimand', 'acceptance', 'detection')):
            state['sections'][heading] = body.strip()[:650]
            state['truncated'] |= len(body.strip()) > 650
for record in valid_records(directory)[-2:]:
    data = json.loads(Path(record + '.json').read_text())
    state['reviews'].append({'path': str(Path(record).relative_to(directory)), 'verdict': data['verdict']})
runs = sorted(directory.glob('logs/**/run.json'), key=lambda p: p.stat().st_mtime)
if runs:
    data = json.loads(runs[-1].read_text())
    state['latest_run'] = {key: data.get(key) for key in ('workflow', 'executor', 'runtime', 'resume', 'exit_code')}
    state['latest_run']['record'] = str(runs[-1].relative_to(directory))
root = Path(os.environ['ARH_ROOT'])
claimed = {}
try:
    claimed = json.loads((directory / 'CLAIM.json').read_text()).get('knowledge_sha256') or {}
except (OSError, ValueError, AttributeError):
    pass
# Read these before acting; 'changed' means the file was edited after the iteration was claimed.
state['knowledge'] = {name: {'path': str(path.relative_to(root)) if root in path.parents else str(path),
                             'sha256': digest(path),
                             'since_claim': 'unrecorded' if name not in claimed else
                                            ('unchanged' if claimed[name] == digest(path) else 'changed')}
                      for name, path in knowledge(root).items()}
state['freeze'] = freeze_state(root, directory)[0]
# Findings of concluded iterations (arh memory): an index only; arh memory show ID gives one in full.
state['memory'] = memory_index(root, os.environ['ARH_ITERS'], 20)
# Work that ran outside arh submit (arh note): the last few, so a resuming session sees it.
notes = directory / 'metadata/notes.jsonl'
state['notes'] = [json.loads(line) for line in (notes.read_text().splitlines() if notes.is_file() else [])
                  if line.strip()][-5:]
state['next'] = 'inspect altered plan' if state['predeclaration'] == 'ALTERED' else ('freeze plan' if state['predeclaration'] != 'frozen' else ('execute/write report' if not report.exists() else ('review evidence' if not state['reviews'] else 'check results gate and ledger')))
print(json.dumps(state, ensure_ascii=True, indent=2))
