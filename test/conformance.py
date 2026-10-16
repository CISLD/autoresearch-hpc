#!/usr/bin/env python3
"""Protocol conformance matrix: inject each protocol violation and check that arh refuses it.

E1-E22 run this checkout's `arh` in a scratch project against a stand-in reviewer, so no model
is called. E5b, E6, E9, E12 and E13 run real tasks and need --site, a configured site.md. A Slurm or PBS
site submits real jobs, so put --workdir on a filesystem the compute nodes can see. Without
--site those five are reported as skipped. The matrix is printed and written as JSON.

    python3 test/conformance.py [--site SITE.md] [--workdir DIR] [--json FILE] [--claims N]
                                [--claim-launcher 'srun -N 4 --ntasks-per-node 8'] [--keep]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
HEADINGS = ('Question', 'Estimand', 'Instrument', 'Acceptance criteria', 'Negative controls',
            'Detection limit', 'Prediction')
DECLARATION = ''.join(f'## {i}. {h}\nDeterministic fixture; one failing check.\n' for i, h in enumerate(HEADINGS, 1))
REPORT = 'Negative controls reject failures. Detection limit: one check. Candidate only.\n'
DAG = """# Discovery DAG

## 1. Inputs
| id | what | identity |
|---|---|---|
| I1 | 100 paired draws | sha256:aa11 |

## 2. The graph, as it ran
```mermaid
flowchart TD
    I1 --> N1
    N1 --> C1
```

## 3. Nodes
| id | operation | parameters | decision? | output |
|---|---|---|---|---|
| N1 | mean difference | none | no | diff |
| C1 | the claim | none | no | diff |

## 4. Branch count
One path; the denominator is 1.

## 5. What falls out of the graph
Nothing.

## 6. Terminal claim
The mean difference is 0.0184 raw units.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--site', type=Path, help='site.md for the cases that run tasks (E5b, E6, E9, E12, E13)')
    parser.add_argument('--workdir', type=Path, help='where the scratch project is created (default: $TMPDIR)')
    parser.add_argument('--json', type=Path, default=Path('conformance.json'), help='result file')
    parser.add_argument('--claims', type=int, default=8, help='concurrent claims in E4')
    parser.add_argument('--claim-launcher', help="run E4's claims through a launcher, e.g. 'srun -N 4 --ntasks-per-node 8', so they race from several nodes on a shared --workdir")
    parser.add_argument('--keep', action='store_true', help='keep the scratch project')
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix='arh-conformance-', dir=args.workdir)).resolve()
    project, inputs = work / 'project', work / 'inputs'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CLAUDE', 'CODEX', 'OPENCODE', 'ARH_'))}
    env.update(ARH_HOME=str(ROOT), ARH_PROJECT=str(project), PATH=f"{ROOT / 'bin'}{os.pathsep}{env['PATH']}")
    results = []

    def arh(*argv, cwd=None, timeout=1800):
        return subprocess.run([str(ROOT / 'bin/arh'), *argv], cwd=cwd or project, env=env,
                              capture_output=True, text=True, timeout=timeout)

    def must(*argv):
        result = arh(*argv, cwd=work)
        if result.returncode:
            sys.exit(f"setup failed: arh {' '.join(argv)}\n{result.stdout}{result.stderr}")
        return result.stdout.strip()

    def case(cid, violation, expected, passed, detail=''):
        # Details go into a shareable record, so the scratch location on this host is elided.
        lines = [line.strip() for line in str(detail).replace(str(work), '<scratch>').splitlines() if line.strip()]
        refusal = [line for line in lines if line.startswith(('FAIL', 'arh:'))]
        results.append(dict(id=cid, violation=violation, expected=expected, passed=passed,
                            detail=(refusal or lines or [''])[0 if refusal else -1][:240]))

    def iteration(title, frozen=True, report=True):
        n = must('claim', '-t', title).splitlines()[0]
        it = project / 'iterations' / f'iteration{n}'
        must('new', '-n', n)
        if frozen:
            (it / 'README.md').write_text(DECLARATION)
            must('gate', 'predeclare', '-n', n)
        if report:
            (it / 'results/report').mkdir(parents=True, exist_ok=True)
            (it / f'results/report/iteration{n}_report.md').write_text(REPORT)
        return n, it

    reviewer = work / 'reviewer.py'
    reviewer.write_text("print('VERDICT: SOUND')\n")
    harnesses = project / '.arh/config/harnesses.md'

    def terms(verifier_family='anthropic', extra=''):
        harnesses.write_text('```arh-config\nproducer = source\nverifier = reviewer\n'
                             'harness_source_family = openai\n'
                             f'harness_reviewer_family = {verifier_family}\n'
                             f'harness_reviewer_cmd = python3 "{reviewer}" {{prompt}}\n{extra}```\n')

    must('init', str(project), '--scheduler', 'local')
    if args.site:
        (project / '.arh/config/site.md').write_text(args.site.read_text())
    inputs.mkdir()
    (inputs / 'data.tsv').write_text('id\tvalue\n1\t2\n')
    (project / 'raw').mkdir()
    cfg = project / '.arh/config/project.md'
    cfg.write_text(cfg.read_text().replace('immutable_inputs  =', f'immutable_inputs  = raw {inputs}', 1))
    terms()

    unreviewed = set()                  # iterations the matrix leaves without a valid review

    # E1, E2: the pre-declaration gate.
    n, it = iteration('E1 unfilled pre-declaration', frozen=False, report=False)
    r = arh('gate', 'predeclare', '-n', n)
    case('E1', 'pre-declaration template left unfilled', 'predeclare gate refuses',
         r.returncode != 0 and not (it / 'PREDECLARATION.sha256').exists(), r.stdout)

    n, it = iteration('E2 result before the plan', frozen=False, report=False)
    (it / 'results/observed.txt').write_text('the result existed first\n')
    (it / 'README.md').write_text(DECLARATION)
    r = arh('gate', 'predeclare', '-n', n)
    case('E2', 'result written before the plan is frozen', 'predeclare gate refuses',
         r.returncode != 0 and not (it / 'PREDECLARATION.sha256').exists(), r.stdout)

    # E14: every required heading present, every body empty (v0.3.0 froze this).
    n, it = iteration('E14 empty sections', frozen=False, report=False)
    (it / 'README.md').write_text(''.join(f'## {i}. {h}\n\n' for i, h in enumerate(HEADINGS, 1)))
    r = arh('gate', 'predeclare', '-n', n)
    case('E14', 'required sections present but empty', 'predeclare gate refuses',
         r.returncode != 0 and 'section empty' in r.stdout and not (it / 'PREDECLARATION.sha256').exists(), r.stdout)

    # E15: results moved aside, the freeze deleted, the plan edited to fit and frozen again (v0.3.0
    # accepted it in three file operations). The second freeze is refused; a hand-made one is caught.
    n, it = iteration('E15 plan frozen again after the result', report=False)
    (it / 'results/observed.txt').write_text('the result\n')
    aside = work / 'aside'
    shutil.move(str(it / 'results'), aside)
    (it / 'results').mkdir()
    freeze = (it / 'PREDECLARATION.sha256').read_text()
    (it / 'PREDECLARATION.sha256').unlink()
    (it / 'README.md').write_text(DECLARATION + 'Prediction revised to fit the result.\n')
    refreeze = arh('gate', 'predeclare', '-n', n)
    (it / 'PREDECLARATION.sha256').write_text(hashlib.sha256((it / 'README.md').read_bytes()).hexdigest() + '\n')
    shutil.rmtree(it / 'results'); shutil.move(str(aside), it / 'results')
    (it / 'results/report').mkdir(parents=True, exist_ok=True)
    (it / f'results/report/iteration{n}_report.md').write_text(REPORT)
    must('ask', '-n', n)
    forged = arh('gate', 'results', '-n', n)
    case('E15', 'plan re-frozen after the result (freeze file deleted)', 'second freeze refused; forged freeze fails',
         refreeze.returncode != 0 and 'frozen once' in refreeze.stderr
         and forged.returncode != 0 and 'frozen again' in forged.stdout,
         f'second freeze refused {refreeze.returncode != 0}; hand-made freeze fails the results gate '
         f'{forged.returncode != 0 and "frozen again" in forged.stdout}')
    (it / 'README.md').write_text(DECLARATION)
    (it / 'PREDECLARATION.sha256').write_text(freeze)
    unreviewed.add(int(n))              # its review was of the forged plan

    # A reviewed iteration that passes its results gate, for E3 and E8.
    n, it = iteration('reviewed iteration')
    must('ask', '-n', n)
    must('gate', 'results', '-n', n)

    (it / 'README.md').write_text(DECLARATION + 'Edited after the result.\n')
    r = arh('gate', 'results', '-n', n)
    case('E3', 'frozen plan edited after the result', 'results gate refuses the changed hash',
         r.returncode != 0 and 'CHANGED' in r.stdout, r.stdout)
    (it / 'README.md').write_text(DECLARATION)

    # E4: claims that race each other, from this host or, through --claim-launcher, from many nodes.
    before = len(list((project / 'iterations').glob('iteration*')))
    if args.claim_launcher:
        loop = f'for i in 1 2 3; do "{ROOT}/bin/arh" claim -t race 2>/dev/null || exit 1; done'
        r = subprocess.run(shlex.split(args.claim_launcher) + ['bash', '-c', loop], cwd=project, env=env,
                           capture_output=True, text=True, timeout=1800)
        got, launched = r.stdout.split(), r.returncode == 0
    else:
        procs = [subprocess.Popen([str(ROOT / 'bin/arh'), 'claim', '-t', f'concurrent {i}'], cwd=project, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                 for i in range(args.claims)]
        got = [p.communicate(timeout=300)[0].strip() for p in procs]
        launched = all(p.returncode == 0 for p in procs)
    created = len(list((project / 'iterations').glob('iteration*'))) - before
    case('E4', f'{len(got)} claims race each other' + (' across nodes' if args.claim_launcher else ''),
         'distinct iteration numbers', launched and len(got) > 1 and all(g.isdigit() for g in got)
         and len(set(got)) == len(got) == created,
         f'{len(got)} claims, {len(set(got))} distinct numbers, {created} directories created'
         + (f' ({args.claim_launcher})' if args.claim_launcher else ''))

    r = arh('guard', str(project / 'raw/injected.txt'))
    case('E5', 'write to a declared immutable input (arh guard)', 'write refused',
         r.returncode != 0 and 'immutable' in r.stderr, r.stderr)

    # E5b, E6, E9: real tasks through Nextflow and the site's scheduler.
    task_cases = [('E5b', 'task writes to a declared immutable input', 'write refused inside the task'),
                  ('E6', 'task exits with an error', 'failure reported; receipt and logs kept'),
                  ('E9', 'submission interrupted while its task runs', 'signal recorded; launch lock released'),
                  ('E12', 'held-out data read before a freeze', 'named path refused; hidden path unreadable'),
                  ('E13', 'frozen decision changed before the confirmation', 'confirmation refused')]
    if not args.site:
        for cid, violation, expected in task_cases:
            case(cid, violation, expected, None, 'skipped: needs --site')
    else:
        scheduler = next((line.split('=', 1)[1].strip() for line in args.site.read_text().splitlines()
                          if line.strip().startswith('scheduler') and '=' in line), 'local')
        n, it = iteration('task cases', report=False)

        def submit(name, body):
            script = it / 'scripts' / f'it{n}_{name}.sh'
            script.write_text(body)
            return script

        def receipt(name, key):
            found = sorted((it / 'logs/nextflow' / name).glob('attempt-*/run.json'))
            return json.loads(found[-1].read_text()).get(key) if found else None

        r = arh('submit', str(submit('write_input', f'set -eu\necho injected > {inputs}/injected.txt\n')), '-n', 'write_input')
        # The task must have tried and been stopped by the read-only mount, not failed for another reason.
        readonly = any('Read-only file system' in e.read_text(errors='replace')
                       for e in (it / 'metadata/nextflow/write_input/work').glob('*/*/.command.err'))
        case(*task_cases[0], r.returncode != 0 and readonly and not (inputs / 'injected.txt').exists(),
             f"submit exit {r.returncode}; task stopped by a read-only mount {readonly}; "
             f"input unchanged {not (inputs / 'injected.txt').exists()}")

        r = arh('submit', str(submit('fail', 'exit 23\n')), '-n', 'fail')
        case(*task_cases[1], r.returncode != 0 and receipt('fail', 'exit_code') not in (None, 0),
             f"submit exit {r.returncode}; receipt exit {receipt('fail', 'exit_code')}")

        proc = subprocess.Popen([str(ROOT / 'bin/arh'), 'submit', str(submit('slow', 'sleep 300\n')), '-n', 'slow'],
                                cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        begun = lambda: bool(list((it / 'metadata/nextflow/slow/work').glob('*/*/.command.begin')))
        deadline = time.time() + 1200
        while proc.poll() is None and time.time() < deadline and not begun():
            time.sleep(1)
        started = proc.poll() is None and begun()
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=600)
        released = not (it / 'metadata/nextflow/slow/.launch-lock').exists()
        # On a real scheduler the task's job must not outlive the interrupted submission.
        cancelled = True
        if scheduler == 'slurm':
            for _ in range(60):
                queue = subprocess.run(['squeue', '-h', '-u', os.environ.get('USER', ''), '-o', '%Z'],
                                       capture_output=True, text=True).stdout
                cancelled = str(project) not in queue
                if cancelled:
                    break
                time.sleep(2)
        case(*task_cases[2], started and proc.returncode != 0 and receipt('slow', 'signal') == 'SIGTERM'
             and released and cancelled,
             f"task started {started}; signal {receipt('slow', 'signal')}; lock released {released}"
             + (f'; job gone from queue {cancelled}' if scheduler == 'slurm' else ''))

        # E12, E13: sealed inputs. The held-out file sits inside a declared immutable input, so only the
        # seal stands between a task and it; the second script builds the path so no text names it.
        held = inputs / 'heldout'
        held.mkdir()
        (held / 'truth.txt').write_text('held-out truth\n')
        before_seal = cfg.read_text()
        cfg.write_text(before_seal.replace('sealed_inputs     =', f'sealed_inputs     = {held}', 1))
        n, it = iteration('sealed confirmation', report=False)
        named_script = submit('named', f'cat {held}/truth.txt\n')
        named = arh('submit', str(named_script), '-n', 'named')
        named_script.unlink()           # every script of the iteration is scanned for sealed paths
        built = submit('built', f'set -eu\ncat "{inputs}/held""out/truth.txt" > "{it}/results/seen.txt"\n')
        hidden = arh('submit', str(built), '-n', 'hidden')
        leaked = (it / 'results/seen.txt').is_file() and 'held-out' in (it / 'results/seen.txt').read_text()
        decision = it / 'scripts/model.txt'
        decision.write_text('threshold = 0.5\n')
        must('freeze', '-n', n, str(decision), str(built))
        confirmed = arh('submit', str(built), '-n', 'confirm')
        read = (it / 'results/seen.txt').is_file() and 'held-out' in (it / 'results/seen.txt').read_text()
        logged = (project / '.arh/unseals.tsv').is_file() and str(held) in (project / '.arh/unseals.tsv').read_text()
        case(*task_cases[3], named.returncode != 0 and 'sealed input' in named.stderr
             and hidden.returncode != 0 and not leaked and confirmed.returncode == 0 and read and logged,
             f'named path refused {named.returncode != 0}; hidden path leaked {leaked}; '
             f'confirmation after freeze read it {read}; read logged {logged}')
        decision.write_text('threshold = 0.4\n')
        changed = arh('submit', str(built), '-n', 'confirm2')
        case(*task_cases[4], changed.returncode != 0 and 'changed since the freeze' in changed.stderr, changed.stderr)
        cfg.write_text(before_seal)

    # E7: claimed under terms that name a same-family verifier, so only the family rule applies.
    terms(verifier_family='openai')
    n, it = iteration('E7 same-family review')
    unreviewed.add(int(n))
    r = arh('ask', '-n', n)
    case('E7', "review requested from the producer's own family", 'refused by default',
         r.returncode != 0 and 'same model family' in r.stderr and not list(it.glob('CROSSCHECK_*')), r.stderr)
    terms()

    n, it = iteration('E8 evidence changed after review')
    unreviewed.add(int(n))
    must('ask', '-n', n)
    report = it / f'results/report/iteration{n}_report.md'
    report.write_text(REPORT + 'Changed after the review.\n')
    r = arh('gate', 'results', '-n', n)
    case('E8', 'evidence changed after a review', 'review becomes ineligible',
         r.returncode != 0 and 'INELIGIBLE' in r.stdout, r.stdout)

    # E16: the only review says UNSOUND. v0.3.0 concluded the iteration anyway, and a rebuttal on its
    # own still let the producer judge its own case; the reviewer now judges the rebuttal.
    def judging(answer):
        reviewer.write_text("import sys\n"
                            f"if 'ADJUDICATION:' in sys.argv[1]:\n    print('ADJUDICATION: {answer}')\n"
                            "else:\n    print('VERDICT: UNSOUND')\n    print('F1: the instrument double counts')\n")
    rebuttal = ('Verdict: rebutted, because the double count is outside the claim.\n'
                'F1: rejected; the counted records do not overlap\n')
    judging('MAINTAINED')
    n, it = iteration('E16 unsound review')
    must('ask', '-n', n)
    unanswered = arh('gate', 'results', '-n', n)
    (it / 'REVIEW_RESPONSE.md').write_text('Verdict: accepted\nF1: accepted; corrected in a new iteration\n')
    accepted = arh('gate', 'results', '-n', n)
    (it / 'REVIEW_RESPONSE.md').write_text(rebuttal)
    unjudged = arh('gate', 'results', '-n', n)
    must('ask', '--rebuttal', '-n', n)
    maintained = arh('gate', 'results', '-n', n)
    judging('WITHDRAWN')
    n, it = iteration('E16 unsound review withdrawn on rebuttal')
    must('ask', '-n', n)
    (it / 'REVIEW_RESPONSE.md').write_text(rebuttal)
    must('ask', '--rebuttal', '-n', n)
    withdrawn = arh('gate', 'results', '-n', n)
    reviewer.write_text("print('VERDICT: SOUND')\n")
    refused = {'unanswered': unanswered, 'accepted': accepted, 'unjudged': unjudged, 'maintained': maintained}
    case('E16', 'the only review returns UNSOUND', 'conclusion refused until a reviewer withdraws it on a rebuttal',
         all(r.returncode != 0 for r in refused.values()) and withdrawn.returncode == 0,
         '; '.join(f'refused {k} {r.returncode != 0}' for k, r in refused.items())
         + f'; concludes when the reviewer withdraws it {withdrawn.returncode == 0}')

    # E18: the review policy is bound at claim; relaxing project.md afterwards changes nothing.
    reviewer.write_text("print('VERDICT: UNSOUND')\n")
    n, it = iteration('E18 review policy relaxed after the claim')
    must('ask', '-n', n)
    policy = project / '.arh/config/project.md'
    original = policy.read_text()
    policy.write_text(re.sub(r'(?m)^unsound_review[ \t]*=.*$', 'unsound_review = allow', original))
    relaxed = arh('gate', 'results', '-n', n)
    policy.write_text(original)
    reviewer.write_text("print('VERDICT: SOUND')\n")
    case('E18', 'review policy relaxed after the claim', 'the policy recorded at claim applies',
         relaxed.returncode != 0 and 'the claimed value applies' in relaxed.stderr,
         next((l.strip() for l in relaxed.stderr.splitlines() if 'claimed value' in l), relaxed.stderr[-300:]))

    # E19: a blind replicator must not see what the operator's home holds: an agent's memory store
    # can carry the original implementation into a session meant to be blind.
    operator = work / 'operator-home'
    for rel, text in (('.claude-mem/memory.db', 'the original code'), ('.codex/memories_1.sqlite', 'its results'),
                      ('.claude/.credentials.json', 'token')):
        (operator / rel).parent.mkdir(parents=True, exist_ok=True)
        (operator / rel).write_text(text)
    replicator = work / 'replicator.py'
    replicator.write_text("import os\nfrom pathlib import Path\nh = Path(os.environ['HOME'])\nprint('VERDICT: SOUND')\n"
                          "print('memory_visible', (h / '.claude-mem/memory.db').exists() or (h / '.codex/memories_1.sqlite').exists())\n"
                          "c = h / '.claude/.credentials.json'\nprint('login_visible', c.is_file() and c.read_text() == 'token')\n")
    terms(extra=f'harnesses = replicator\nharness_replicator_family = anthropic\n'
                f'harness_replicator_cmd = python3 "{replicator}" {{prompt}}\n'
                'replicate_home = fresh\nfresh_home_files = .claude/.credentials.json\n')
    n, it = iteration('E19 blind replication', report=False)
    must('dag', 'init', '-n', n)
    (it / 'DAG.md').write_text(DAG)
    must('dag', 'freeze', '-n', n)
    saved = env.get('HOME')
    env['HOME'] = str(operator)
    r = arh('replicate', '-n', n, '--agents', '1')
    env['HOME'] = saved
    out = project / f'verification/replication_it{n}/agent1/REPORT.md'
    seen = out.read_text() if out.is_file() else ''
    case('E19', "memory stores in the operator's home during blind replication",
         'the replicator sees its login file and no memory store',
         r.returncode == 0 and 'memory_visible False' in seen and 'login_visible True' in seen,
         ' '.join(l for l in seen.splitlines() if 'visible' in l) or (r.stdout + r.stderr)[-240:])
    terms()

    # E20-E22: per-iteration controllers (orchestration = per-iteration). A controller that waits
    # for a release file holds its iteration while the main controller tries to change it.
    controller = work / 'controller.py'
    controller.write_text("import os, time\nfrom pathlib import Path\n"
                          "while not Path(os.environ['WAIT_FOR']).exists():\n    time.sleep(0.2)\n")
    terms(extra=f'orchestration = per-iteration\niteration_controller = ctl\nharness_ctl_family = openai\n'
                f'harness_ctl_cmd = python3 "{controller}" {{prompt}}\n')
    brief = work / 'brief.md'
    brief.write_text('Find out whether the fixture passes its one check.\n')
    release = work / 'release'
    env['WAIT_FOR'] = str(release)
    n, it = iteration('E20 dispatched iteration', frozen=False, report=False)
    started = arh('dispatch', '-n', n, '--brief', str(brief), '--detach')
    changed = arh('note', '-n', n, 'written by the main controller')
    second = arh('dispatch', '-n', n, '--brief', str(brief))
    release.touch()
    waited = arh('wait', '-n', n, '--timeout', '120', '--interval', '1')
    freed = arh('note', '-n', n, 'the controller has finished')
    case('E20', 'main controller changes an iteration its dispatched controller holds', 'refused until the controller exits',
         started.returncode == 0 and changed.returncode == 3 and waited.returncode == 0 and freed.returncode == 0,
         f'dispatched {started.returncode == 0}; change refused {changed.returncode == 3}; '
         f'allowed after the controller exited {freed.returncode == 0}')
    case('E21', 'a second controller dispatched to the same iteration', 'refused',
         second.returncode != 0 and 'already has a running controller' in second.stderr, second.stderr)
    env.pop('WAIT_FOR')
    terms(extra=f'orchestration = per-iteration\niteration_controller = ctl\nharness_ctl_family = openai\n'
                f'harness_ctl_cmd = python3 "{controller}" {{prompt}}\n'
                'executor = twin\nharness_twin_family = anthropic\nharness_twin_cmd = true\n')
    n, it = iteration('E22 executor of the verifier\'s family')
    unreviewed.add(int(n))
    r = arh('ask', '-n', n)
    case('E22', "review from the executor's model family", 'refused',
         r.returncode != 0 and 'the executor (twin/anthropic)' in r.stderr, r.stderr)
    terms()

    # E11: the review terms were bound at claim; changing them needs a recorded reason.
    n, it = iteration('E11 review terms changed after the claim')
    unreviewed.add(int(n))              # its reason is removed at the end of the case
    terms(extra='ask_max_input_bytes = 60000\n')
    r = arh('ask', '-n', n)
    refused = r.returncode != 0 and 'changed since iteration' in r.stderr and not list(it.glob('CROSSCHECK_*'))
    must('ask', '-n', n, '--terms-changed', 'conformance run: raised the input budget')
    g = arh('gate', 'results', '-n', n)
    shown = g.returncode == 0 and 'review terms changed since the claim (ask_max_input_bytes)' in g.stdout
    record = next(it.glob('CROSSCHECK_*.md.json'))
    data = json.loads(record.read_text())
    data['terms_changed'] = None
    record.write_text(json.dumps(data))
    stripped = arh('gate', 'results', '-n', n).returncode != 0
    case('E11', 'review configuration changed after the claim',
         'review refused unless the change and its reason are recorded', refused and shown and stripped,
         f'refused without reason {refused}; accepted and shown with reason {shown}; '
         f'refused once the reason is removed {stripped}')
    terms()

    # E10 last: from a fresh shell, the files alone must say where every iteration stands.
    fresh = work / 'fresh-shell'
    fresh.mkdir()
    status, nxt = arh('status', '--json', cwd=fresh), arh('next', cwd=fresh)
    render, check = arh('ledger', 'render', cwd=fresh), arh('ledger', 'check', cwd=fresh)
    try:
        listed = len(json.loads(status.stdout)['iterations'])
    except (ValueError, KeyError):
        listed = 0
    claimed = len(list((project / 'iterations').glob('iteration*')))
    flagged = {int(m) for m in re.findall(r'FAIL iteration (\d+) . no valid cross-check', check.stdout)}
    case('E10', 'fresh shell with no chat history', 'ledger and status name the next action',
         status.returncode == nxt.returncode == render.returncode == 0 and listed == claimed
         and 'arh ' in nxt.stdout and flagged == unreviewed,
         f'status lists {listed}/{claimed} iterations; ledger check flags {sorted(flagged)}, '
         f'expected {sorted(unreviewed)}; next names an arh command {"arh " in nxt.stdout}')

    # E17 after E10: a concluded iteration's directory deleted and the ledger re-rendered.
    n, it = iteration('E17 concluded iteration deleted')
    must('ask', '-n', n)
    must('gate', 'results', '-n', n)
    shutil.rmtree(it)
    render = arh('ledger', 'render')
    check = arh('ledger', 'check')
    case('E17', 'concluded iteration deleted, ledger re-rendered', 'ledger check fails',
         render.returncode == 0 and check.returncode != 0 and f'iteration {n} — in the claim registry' in check.stdout,
         next((l for l in check.stdout.splitlines() if 'claim registry' in l), check.stdout))

    results.sort(key=lambda r: (int(re.match(r'E(\d+)', r['id']).group(1)), r['id']))
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if commit and subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        commit += '-dirty'                # uncommitted changes: not evidence for the commit alone
    version = subprocess.run([str(ROOT / 'bin/arh'), '--version'], env=env, capture_output=True, text=True).stdout.strip()
    fs = subprocess.run(['stat', '-f', '-c', '%T', str(work)], capture_output=True, text=True).stdout.strip()
    payload = dict(kind='arh protocol conformance matrix', commit=commit or None, version=version,
                   python=platform.python_version(), filesystem=fs or None,
                   site=args.site.name if args.site else None,
                   passed=sum(r['passed'] is True for r in results), failed=sum(r['passed'] is False for r in results),
                   skipped=sum(r['passed'] is None for r in results), results=results)
    args.json.write_text(json.dumps(payload, indent=2) + '\n')
    for r in results:
        mark = {True: 'PASS', False: 'FAIL', None: 'SKIP'}[r['passed']]
        print(f"{mark}  {r['id']:<4} {r['violation']:<48} {r['detail']}")
    print(f"\n{payload['passed']} passed, {payload['failed']} failed, {payload['skipped']} skipped "
          f"({version}, {(commit[:12] + '-dirty' * commit.endswith('-dirty')) or 'no git checkout'}); "
          f"written to {args.json}")
    if args.keep:
        print(f'kept: {work}')
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if payload['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
