"""Behavioral regressions for the protocol boundaries; no live model required."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


# Submission tests need a configured controller and task runtime; without one they
# would fail for reasons unrelated to the protocol (and, on a Slurm host, submit real jobs).
needs_site = unittest.skipUnless(os.environ.get('ARH_TEST_SITE'),
                                 'set ARH_TEST_SITE to a configured local site.md (see README)')
# A Slurm or PBS site.md makes submission tests submit real jobs and fail for reasons unrelated
# to the protocol (142 of 143 with a Slurm site.md, 2026-09-16), so refuse it outright.
_site = os.environ.get('ARH_TEST_SITE')
_scheduler = re.findall(r'(?m)^[ \t]*scheduler[ \t]*=[ \t]*(\S*)', Path(_site).read_text()) if _site else []
if _scheduler and _scheduler[0] != 'local':
    sys.exit(f'ARH_TEST_SITE must set scheduler = local, not {_scheduler[0]}: {_site}')
needs_network = unittest.skipUnless(os.environ.get('ARH_TEST_NETWORK'), 'set ARH_TEST_NETWORK=1 to solve real packages')
needs_gitleaks = unittest.skipUnless(shutil.which('gitleaks'), 'gitleaks is not on PATH')
REFUSE = ("import sys; sys.stderr.write('This content was flagged for possible biological risk. "
          "If this seems wrong, try rephrasing your request.\\n'); raise SystemExit(1)")


class Protocol(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='arh-hardening-')
        self.root = Path(self.temp.name) / 'project'
        self.env = dict(os.environ, ARH_HOME=str(ROOT), ARH_PROJECT=str(self.root),
                        PATH=str(ROOT / 'bin') + os.pathsep + os.environ['PATH'])
        subprocess.run([str(ROOT / 'bin/arh'), 'init', str(self.root)], check=True, capture_output=True)
        if os.environ.get('ARH_TEST_SITE'):
            (self.root / '.arh/config/site.md').write_text(Path(os.environ['ARH_TEST_SITE']).read_text())
        self.call('claim', '-t', 'validation')
        self.call('new', '-n', '1')
        self.it = self.root / 'iterations/iteration1'
        headings = ['Question', 'Estimand', 'Instrument', 'Acceptance criteria', 'Negative controls', 'Detection limit', 'Prediction']
        (self.it / 'README.md').write_text('\n'.join(f'## {i}. {h}\nDeterministic fixture; one failing check.\n' for i, h in enumerate(headings, 1)))
        self.call('gate', 'predeclare', '-n', '1')
        self.report = self.it / 'results/report/iteration1_report.md'
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.report.write_text('Negative controls reject failures. Detection limit: one check. Candidate only.\n')
        self.config = self.root / '.arh/config/harnesses.md'
        self.mock = self.root / 'mock.py'
        self.configure()

    def tearDown(self):
        self.temp.cleanup()

    def call(self, *args, good=True, timeout=90):
        result = subprocess.run([str(ROOT / 'bin/arh'), *args], env=self.env, cwd=self.root,
                                capture_output=True, text=True, timeout=timeout)
        if good is True:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        elif good is False:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def configure(self, body="print('VERDICT: SOUND')", family='anthropic', timeout=5, version=None,
                  cmd_extra='', extra_config='', bind=True):
        self.mock.write_text(body + '\n')
        extra = f'harness_reviewer_version_cmd = {version}\n' if version else ''
        self.config.write_text(f'''```arh-config
producer = source
verifier = reviewer
harness_source_family = openai
harness_reviewer_family = {family}
harness_reviewer_cmd = python3 "{self.mock}" {{prompt}}{cmd_extra}
{extra}ask_timeout = {timeout}
{extra_config}```
''')
        if bind:
            self.bind_terms()

    def bind_terms(self):
        """Fixture shortcut: iteration 1 counts as claimed under whatever harnesses.md now says.
        bind=False, or editing the file directly, is a change made after the claim."""
        shutil.copy(self.config, self.it / 'metadata/harnesses.claimed.md')
        claim = json.loads((self.it / 'CLAIM.json').read_text())
        claim['harness_config_sha256'] = hashlib.sha256(self.config.read_bytes()).hexdigest()
        (self.it / 'CLAIM.json').write_text(json.dumps(claim, indent=2) + '\n')

    def set_config(self, name, **values):
        """Set keys in the arh-config block of .arh/config/NAME, adding any the file lacks (the test
        site's site.md can predate a key)."""
        path = self.root / '.arh/config' / name
        text = path.read_text()
        for key, value in values.items():
            line = f'{key} = {value}'
            text, n = re.subn(rf'(?m)^[ \t]*{re.escape(key)}[ \t]*=.*$', lambda m: line, text)
            if not n:
                text = re.sub(r'(?ms)(^```arh-config\n.*?)(^```)', lambda m: m.group(1) + line + '\n' + m.group(2), text, count=1)
        path.write_text(text)

    def ask(self, good=True):
        return self.call('ask', '-n', '1', good=good)

    def gate(self, good=True):
        return self.call('gate', 'results', '-n', '1', good=good)

    def test_closed_output_still_times_out(self):
        self.configure("import os,time; os.close(1); os.close(2); time.sleep(10)", timeout=1)
        self.ask(good=False)
        record = next(self.it.glob('CROSSCHECK_*.md.json'))
        self.assertEqual(json.loads(record.read_text())['exit_code'], 124)
        self.gate(good=False)

    def test_complete_review(self):
        self.ask(); self.gate()

    def test_failed_review_rejected(self):
        self.configure("print('VERDICT: SOUND'); raise SystemExit(7)")
        self.ask(good=False); self.gate(good=False)

    def test_missing_verdict_rejected(self):
        self.configure("print('looks fine')")
        self.ask(good=False); self.gate(good=False)

    def test_multiple_verdicts_rejected(self):
        self.configure("print('VERDICT: SOUND\\nVERDICT: UNSOUND')")
        self.ask(good=False); self.gate(good=False)

    def test_same_family_override_not_foreign(self):
        self.configure(family='openai')
        self.ask(good=False)
        self.call('ask', '-n', '1', '--same-family')
        self.gate(good=False)

    def test_unknown_family_rejected(self):
        self.configure(family='unknown'); self.ask(good=False)

    def test_mixed_family_rejected(self):
        self.configure(family='mixed'); self.ask(good=False)

    def test_stale_report_rejected(self):
        self.ask(); self.report.write_text(self.report.read_text() + 'Changed.\n'); self.gate(good=False)

    def test_modified_review_rejected(self):
        self.ask()
        record = next(self.it.glob('CROSSCHECK_*.md'))
        record.write_text(record.read_text() + 'Changed.\n'); self.gate(good=False)

    def test_legacy_filename_is_not_evidence(self):
        (self.it / 'CROSSCHECK_fake.md').write_text('VERDICT: SOUND\n'); self.gate(good=False)

    def test_repeated_reviews_unique(self):
        self.ask()
        self.call('ask', '-n', '1', '--note', 'Check a distinct concrete issue.')
        self.assertEqual(len(list(self.it.glob('CROSSCHECK_*.md.json'))), 2)

    def test_timeout_is_failure(self):
        self.configure('import time; time.sleep(10)', timeout=0.1)
        # A timeout is an unavailable verifier (exit 75, fallback tried); the record keeps exit 124 (#51).
        result = self.ask(good=False); self.assertEqual(result.returncode, 75); self.gate(good=False)
        record = json.loads(next(self.it.glob('CROSSCHECK_*.md.json')).read_text())
        self.assertEqual((record['exit_code'], record['provider_error_kind']), (124, 'timeout'))

    def test_quotes_and_cwd(self):
        self.configure("import os,sys; assert os.getcwd() == " + repr(str(self.root)) + "; assert len(sys.argv)==2; print('VERDICT: SOUND')")
        self.ask(); self.gate()

    def test_refreeze_rejected_without_results(self):
        self.report.unlink()
        frozen=(self.it / 'PREDECLARATION.sha256').read_bytes()
        (self.it / 'README.md').write_text((self.it / 'README.md').read_text() + 'Changed\n')
        self.call('gate', 'predeclare', '-n', '1', good=False)
        self.assertEqual((self.it / 'PREDECLARATION.sha256').read_bytes(), frozen)

    def test_missing_rule_rejected(self):
        (self.root / 'rules/detection-limit-stated.md').unlink(); self.gate(good=False)

    @needs_site
    def test_local_failure_propagates(self):
        script=self.it / 'scripts/it1_01_fail.sh'; script.write_text('set -euo pipefail\nexit 9\n')
        result=self.call('submit', str(script), '-w', good=False)
        self.assertNotEqual(result.returncode, 0)
        records=list((self.it/'logs').glob('nextflow/*/attempt-*/run.json'))
        self.assertNotEqual(json.loads(records[0].read_text())['exit_code'], 0)

    def test_submit_unfrozen_rejected(self):
        script=self.it / 'scripts/it1_01_no.sh'; script.write_text('exit 0\n')
        (self.it/'PREDECLARATION.sha256').unlink()
        self.call('submit', str(script), '-w', good=False)

    def test_relative_immutable_guard(self):
        p=self.root / '.arh/config/project.md'; p.write_text(p.read_text().replace('immutable_inputs  =', 'immutable_inputs  = raw'))
        self.call('guard', str(self.root/'raw/x'), good=False)

    def test_image_digest(self):
        image=self.root/'image.sif'; image.write_bytes(b'fixture')
        fake=self.root/'apptainer'; fake.write_text('#!/bin/sh\nexit 0\n'); fake.chmod(0o755)
        self.env['PATH']=str(self.root)+os.pathsep+self.env['PATH']
        site=self.root/'.arh/config/site.md'
        site.write_text(f'```arh-config\ncontainer_runtime = apptainer\nimage_test = {image}\nimage_test_sha256 = {hashlib.sha256(image.read_bytes()).hexdigest()}\n```\n')
        self.call('run', 'test', '--', 'true')
        image.write_bytes(b'changed'); self.call('run', 'test', '--', 'true', good=False)

    def test_remote_tag_rejected(self):
        (self.root/'.arh/config/site.md').write_text('```arh-config\ncontainer_runtime = docker\nimage_test = docker://python:latest\n```\n')
        self.call('run', 'test', '--', 'true', good=False)

    def test_result_snapshot_change_rejected(self):
        snapshot=self.it/'results/design.md'; snapshot.write_text('reviewed design')
        self.ask(); snapshot.write_text('changed design'); self.gate(good=False)

    def test_literal_prompt_placeholders_preserved(self):
        self.configure("import sys; assert '{cwd}' in sys.argv[1] and '{prompt}' in sys.argv[1]; print('VERDICT: SOUND')")
        self.call('ask', '-n', '1', '--note', 'Keep literal {cwd} and {prompt} in this source sample.')

    def test_local_digest_shaped_filename_is_hashed(self):
        image=self.root/('image@sha256:'+'a'*64); image.write_bytes(b'fixture')
        (self.root/'.arh/config/site.md').write_text(f'```arh-config\ncontainer_runtime = apptainer\nimage_test = {image}\n```\n')
        self.call('run', 'test', '--', 'true', good=False)

    JUDGE = ("import sys\n"
             "if 'ADJUDICATION:' in sys.argv[1]:\n    print('ADJUDICATION: {answer}')\n"
             "else:\n    print('VERDICT: UNSOUND')")
    REBUTTAL = 'Verdict: rebutted, because the flagged step changes no reported value.\n'

    def bind_policy(self, **policy):
        """Fixture shortcut: iteration 1 counts as claimed under this review policy."""
        claim = json.loads((self.it / 'CLAIM.json').read_text())
        claim.setdefault('review_policy', {}).update(policy)
        (self.it / 'CLAIM.json').write_text(json.dumps(claim, indent=2) + '\n')

    def test_unsound_verdict_needs_a_recorded_rebuttal(self):
        self.configure("print('VERDICT: UNSOUND')")
        self.ask(); result=self.gate(good=False); self.assertIn('UNSOUND, with no recorded answer', result.stdout)
        response = self.it / 'REVIEW_RESPONSE.md'
        response.write_text('Verdict: accepted\n')
        self.assertIn('the response accepts it', self.gate(good=False).stdout)
        response.write_text('Verdict: rebutted\n')
        self.assertIn('gives no reason', self.gate(good=False).stdout)
        response.write_text(self.REBUTTAL)
        self.assertIn('no reviewer has judged the rebuttal: arh ask --rebuttal -n 1', self.gate(good=False).stdout)
        self.call('ledger', 'render')
        self.assertIn('UNSOUND (rebutted, unadjudicated)', (self.root / 'PROGRESS.md').read_text())
        self.assertIn('Verdict: <rebutted', self.call('gate', 'results', '-n', '1', '--skeleton').stdout)

    def test_a_rebuttal_the_reviewer_withdraws_concludes(self):
        self.configure(self.JUDGE.format(answer='WITHDRAWN'))
        self.ask(); (self.it / 'REVIEW_RESPONSE.md').write_text(self.REBUTTAL)
        out = self.call('ask', '--rebuttal', '-n', '1').stdout
        self.assertIn('ADJUDICATION: WITHDRAWN', out)
        record = next(self.it.glob('REBUTTAL_reviewer_*.md'))
        data = json.loads(Path(str(record) + '.json').read_text())
        self.assertEqual((data['kind'], data['adjudication']), ('adjudication', 'WITHDRAWN'))
        self.assertTrue(data['adjudicates'].startswith('CROSSCHECK_adversary_reviewer_'))
        prompt = Path(str(record) + '.prompt').read_text()
        self.assertIn('VERDICT: UNSOUND', prompt); self.assertIn('changes no reported value', prompt)
        self.assertIn('the reviewer withdrew it', self.gate().stdout)
        self.call('ledger', 'render')
        self.assertIn('UNSOUND (rebutted, withdrawn)', (self.root / 'PROGRESS.md').read_text())
        # Nothing left to judge, and a judgment is not a review round.
        self.assertIn('no rebutted UNSOUND review waiting', self.call('ask', '--rebuttal', '-n', '1', good=False).stderr)
        self.assertEqual(len(list(self.it.glob('CROSSCHECK_*.md'))), 1)

    def test_a_maintained_unsound_blocks_and_cannot_be_asked_again(self):
        self.configure(self.JUDGE.format(answer='MAINTAINED'))
        self.ask(); response = self.it / 'REVIEW_RESPONSE.md'; response.write_text(self.REBUTTAL)
        self.call('ask', '--rebuttal', '-n', '1')
        self.assertIn('the reviewer maintained it over the rebuttal', self.gate(good=False).stdout)
        # Rewording the rebuttal voids the judgment but does not buy a second one.
        response.write_text('Verdict: rebutted, because on reflection the step is harmless.\n')
        self.gate(good=False)
        self.assertIn('ask_max_adjudications is 1', self.call('ask', '--rebuttal', '-n', '1', good=False).stderr)
        # A maintained verdict blocks under require-rebuttal too; only allow lets it through.
        response.write_text(self.REBUTTAL)
        self.bind_policy(unsound_review='require-rebuttal')
        self.assertIn('maintained', self.gate(good=False).stdout)
        self.bind_policy(unsound_review='allow')
        self.assertIn('WARN', self.gate().stdout)

    def test_editing_the_rebuttal_voids_its_judgment(self):
        self.configure(self.JUDGE.format(answer='WITHDRAWN'))
        self.ask(); response = self.it / 'REVIEW_RESPONSE.md'; response.write_text(self.REBUTTAL)
        self.call('ask', '--rebuttal', '-n', '1'); self.gate()
        response.write_text(self.REBUTTAL + 'Also the reviewer misread the table.\n')
        self.assertIn('no reviewer has judged the rebuttal', self.gate(good=False).stdout)

    def test_require_rebuttal_accepts_an_unjudged_rebuttal(self):
        self.bind_policy(unsound_review='require-rebuttal')
        self.configure("print('VERDICT: UNSOUND')")
        self.ask(); (self.it / 'REVIEW_RESPONSE.md').write_text(self.REBUTTAL)
        self.assertIn('not put to a reviewer', self.gate().stdout)

    def test_a_rebuttal_is_judged_under_the_family_rule(self):
        self.configure(self.JUDGE.format(answer='WITHDRAWN'),
                       extra_config=f'harness_twin_family = openai\nharness_twin_cmd = python3 "{self.mock}" {{prompt}}\n')
        self.ask(); (self.it / 'REVIEW_RESPONSE.md').write_text(self.REBUTTAL)
        self.assertIn('same model family', self.call('ask', '--rebuttal', '-n', '1', '--harness', 'twin', good=False).stderr)
        self.assertFalse(list(self.it.glob('REBUTTAL_*')))

    def test_rebuttal_dry_run_sends_nothing(self):
        self.configure(self.JUDGE.format(answer='WITHDRAWN'))
        self.ask(); (self.it / 'REVIEW_RESPONSE.md').write_text(self.REBUTTAL)
        out = self.call('ask', '--rebuttal', '-n', '1', '--dry-run').stdout
        self.assertIn('ADJUDICATION: WITHDRAWN | MAINTAINED', out); self.assertIn('changes no reported value', out)
        self.assertFalse(list(self.it.glob('REBUTTAL_*')))

    def test_unsound_verdict_is_only_reported_when_the_project_allows_it(self):
        self.bind_policy(unsound_review='allow')
        self.configure("print('VERDICT: UNSOUND')")
        self.ask(); self.assertIn('WARN', self.gate().stdout)

    def test_the_review_policy_is_read_from_the_claim(self):
        self.assertEqual(json.loads((self.it / 'CLAIM.json').read_text())['review_policy'],
                         {'require_crosscheck': 'true', 'review_response': 'require',
                          'unsound_review': 'require-adjudication'})
        self.set_config('project.md', unsound_review='allow', require_crosscheck='false')
        self.configure("print('VERDICT: UNSOUND')")
        self.ask(); result = self.gate(good=False)
        self.assertIn('FAIL', result.stdout); self.assertIn('the claimed value applies', result.stderr)
        # An iteration claimed after the edit is judged by the new policy.
        n = self.call('claim', '-t', 'after the edit').stdout.split()[0]
        policy = json.loads((self.root / f'iterations/iteration{n}/CLAIM.json').read_text())['review_policy']
        self.assertEqual(policy['unsound_review'], 'allow')

    def test_claim_records_its_question(self):
        self.assertEqual(json.loads((self.it / 'CLAIM.json').read_text())['question'], 'q1')
        n = self.call('claim', '-t', 'again', '--continues', '1').stdout.split()[0]
        self.assertEqual(json.loads((self.root / f'iterations/iteration{n}/CLAIM.json').read_text())['question'], 'q1')
        m = self.call('claim', '-t', 'named', '--question', 'deg-count').stdout.split()[0]
        self.assertEqual(json.loads((self.root / f'iterations/iteration{m}/CLAIM.json').read_text())['question'], 'deg-count')
        self.assertIn('invalid question id', self.call('claim', '-t', 'bad', '--question', 'a b', good=False).stderr)
        self.assertIn('no claimed iteration 99', self.call('claim', '-t', 'bad', '--continues', '99', good=False).stderr)
        self.call('claim', '-t', 'both', '--continues', '1', '--question', 'x', good=False)

    def test_a_passing_gate_records_the_conclusion(self):
        self.ask(); self.assertIn('is concluded', self.gate().stdout)
        receipts = (self.it / 'metadata/conclusions.jsonl').read_text().splitlines()
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0])
        self.assertEqual(receipt['report_sha256'], hashlib.sha256(self.report.read_bytes()).hexdigest())
        self.assertEqual(len(receipt['reviews']), 1)
        self.gate()          # an unchanged conclusion is not recorded twice
        self.assertEqual(len((self.it / 'metadata/conclusions.jsonl').read_text().splitlines()), 1)
        self.call('ledger', 'render')
        self.assertIn('| 1 | ', (self.root / 'PROGRESS.md').read_text())
        self.assertRegex((self.root / 'PROGRESS.md').read_text(), r'\| 1 \| [^|]+\| frozen \| concluded \|')
        # Evidence changed after the conclusion: the receipt no longer holds.
        self.report.write_text(self.report.read_text() + 'Edited after the conclusion.\n')
        self.call('ledger', 'render')
        self.assertRegex((self.root / 'PROGRESS.md').read_text(), r'\| 1 \| [^|]+\| frozen \| report \|')

    def test_the_ledger_counts_attempts_per_question(self):
        headings = ['Question', 'Estimand', 'Instrument', 'Acceptance criteria', 'Negative controls', 'Detection limit', 'Prediction']
        body = ''.join(f'## {h}\nA second try, with the counting corrected.\n' for h in headings)
        self.ask()           # iteration 1 is reviewed but never passes the gate: open, not concluded
        tries = []
        for title in ('second try', 'third try'):
            n = self.call('claim', '-t', title, '--continues', '1').stdout.split()[0]
            self.call('new', '-n', n)
            (self.root / f'iterations/iteration{n}/README.md').write_text(body)
            self.call('gate', 'predeclare', '-n', n)
            tries.append(n)
        # Only the third try concludes; the first two stay open.
        last = self.root / f'iterations/iteration{tries[1]}'
        report = last / f'results/report/iteration{tries[1]}_report.md'
        report.parent.mkdir(parents=True, exist_ok=True); report.write_text(self.report.read_text())
        self.call('ask', '-n', tries[1]); self.call('gate', 'results', '-n', tries[1])
        self.call('ledger', 'render')
        ledger = (self.root / 'PROGRESS.md').read_text()
        self.assertIn(f'| q1 | 1, {tries[0]}, {tries[1]} | {tries[1]} (attempt 3 of 3) |', ledger)
        self.call('ledger', 'check')
        status = json.loads(self.call('status', '--json').stdout)
        attempt = {i['iteration']: i['attempt'] for i in status['iterations']}
        self.assertEqual(attempt[int(tries[1])], {'question': 'q1', 'state': 'concluded', 'attempt': 3, 'of': 3})
        self.assertEqual(attempt[1]['state'], 'open')

    DAG = """# Discovery DAG — iteration 1

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
    REPLICATOR = ("import os, sys\nfrom pathlib import Path\nh = Path(os.environ['HOME'])\n"
                  "print('VERDICT: SOUND')\n"
                  "print('memory_visible', (h / '.claude-mem/memory.db').exists() or (h / '.codex/memories_1.sqlite').exists())\n"
                  "c = h / '.claude/.credentials.json'\n"
                  "print('login_visible', c.is_file() and c.read_text() == 'token')\n"
                  "print('config_dir_set', 'CLAUDE_CONFIG_DIR' in os.environ)\n")

    def replication_fixture(self, mode):
        operator = Path(self.temp.name) / 'operator-home'
        for path, text in (('.claude-mem/memory.db', 'the original code'), ('.codex/memories_1.sqlite', 'results'),
                           ('.claude/.credentials.json', 'token')):
            (operator / path).parent.mkdir(parents=True, exist_ok=True); (operator / path).write_text(text)
        self.env.update(HOME=str(operator), CLAUDE_CONFIG_DIR=str(operator / '.claude'))
        self.mock.write_text(self.REPLICATOR)
        self.config.write_text(f'''```arh-config
producer = source
verifier = reviewer
harnesses = reviewer
harness_source_family = openai
harness_reviewer_family = anthropic
harness_reviewer_cmd = python3 "{self.mock}" {{prompt}}
replicate_home = {mode}
fresh_home_files = .claude/.credentials.json
fresh_home_env_unset = CLAUDE_CONFIG_DIR
```
''')
        self.bind_terms()
        self.call('dag', 'init', '-n', '1')
        (self.it / 'DAG.md').write_text(self.DAG)
        self.call('dag', 'freeze', '-n', '1')
        self.call('replicate', '-n', '1', '--agents', '1')
        work = self.root / 'verification/replication_it1/agent1'
        return (work / 'REPORT.md').read_text(), work, self.call('replicate', 'report', '-n', '1').stdout

    def test_a_blind_replicator_cannot_see_the_operators_memory(self):
        report, work, summary = self.replication_fixture('fresh')
        self.assertIn('memory_visible False', report)
        self.assertIn('login_visible True', report)
        self.assertIn('config_dir_set False', report)
        record = json.loads((work / 'HOME.json').read_text())
        self.assertEqual(record['home'], 'fresh')
        self.assertEqual(record['files'], [{'source': '.claude/.credentials.json', 'dest': '.claude/.credentials.json', 'linked': True}])
        self.assertTrue((work / 'home/.claude/.credentials.json').is_symlink())
        self.assertIn('Every agent ran with a fresh home directory', summary)

    def test_an_inherited_home_is_named_in_the_replication_report(self):
        report, _, summary = self.replication_fixture('inherit')
        self.assertIn('memory_visible True', report)
        self.assertIn('treat its blindness as unverified', summary)

    CONTROLLER = """import os, subprocess, sys, time
from pathlib import Path
n, root = os.environ['ARH_DISPATCH'], Path(os.environ['ARH_PROJECT'])
it = root / f'iterations/iteration{n}'
def arh(*a):
    r = subprocess.run(['arh', *a], capture_output=True, text=True)
    print('$ arh', *a, '->', r.returncode)
    return r
if os.environ.get('WAIT_FOR'):
    while not Path(os.environ['WAIT_FOR']).exists():
        time.sleep(0.2)
    sys.exit(0)
arh('new', '-n', n)
it.joinpath('README.md').write_text(''.join(f'## {h}\\nDispatched fixture; one failing check.\\n' for h in
    ('Question', 'Estimand', 'Instrument', 'Acceptance criteria', 'Negative controls', 'Detection limit', 'Prediction')))
arh('gate', 'predeclare', '-n', n)
(it / 'results/report').mkdir(parents=True, exist_ok=True)
(it / f'results/report/iteration{n}_report.md').write_text('Negative controls reject failures. Detection limit: one check. Candidate only.\\n')
arh('ask', '-n', n)
arh('gate', 'results', '-n', n)
print('the key I found: sk-ant-' + 'a' * 40)
arh('dispatch', 'report', '-n', n, '--outcome', 'concluded', '--summary', 'The fixture concluded under a SOUND review; nothing remains open.')
"""

    def dispatch_config(self, extra=''):
        controller = self.root / 'controller.py'
        controller.write_text(self.CONTROLLER)
        self.configure(extra_config=f'orchestration = per-iteration\niteration_controller = ctl\n'
                                    f'harness_ctl_family = openai\nharness_ctl_cmd = python3 "{controller}" {{prompt}}\n'
                                    'dispatch_env = FIXTURE=1\n' + extra)
        brief = self.root / 'brief.md'
        brief.write_text('Find out whether the fixture passes its one check.\n')
        n = self.call('claim', '-t', 'dispatched iteration').stdout.split()[0]
        return n, self.root / f'iterations/iteration{n}', brief

    def test_dispatch_needs_per_iteration_mode(self):
        brief = self.root / 'brief.md'; brief.write_text('anything\n')
        self.assertIn('orchestration = per-iteration', self.call('dispatch', '-n', '1', '--brief', str(brief), good=False).stderr)

    def test_a_dispatched_controller_runs_its_iteration_and_hands_back(self):
        n, it, brief = self.dispatch_config()
        self.assertIn('Find out whether the fixture passes', self.call('dispatch', '-n', n, '--brief', str(brief), '--dry-run').stdout)
        self.assertFalse((it / 'metadata/dispatch').exists())
        self.call('dispatch', '-n', n, '--brief', str(brief), timeout=180)
        record = it / 'metadata/dispatch/001'
        run = json.loads((record / 'run.json').read_text())
        self.assertEqual((run['harness'], run['state'], run['exit_code'], run['session']), ('ctl', 'finished', 0, f'dispatch-{n}-001'))
        log = (record / 'session.log').read_text()
        self.assertIn('[REDACTED Anthropic API key]', log); self.assertNotIn('sk-ant-aaaa', log)
        self.assertGreaterEqual(run['redactions'], 1)
        self.assertEqual(run['session_log_sha256'], hashlib.sha256((record / 'session.log').read_bytes()).hexdigest())
        summary = json.loads((record / 'summary.json').read_text())
        self.assertEqual((summary['outcome'], summary['state']), ('concluded', 'concluded'))
        self.assertIn('concluded', self.call('dispatch', 'status', '-n', n).stdout)
        lease = json.loads((it / 'metadata/lease.json').read_text())
        self.assertEqual(lease['holder']['session'], f'dispatch-{n}-001')
        review = json.loads(next(it.glob('CROSSCHECK_*.md.json')).read_text())
        self.assertEqual(review['producer_family'], 'openai')
        self.assertFalse((it / '.dispatch-lock').exists())

    def test_a_dispatched_iteration_is_held_by_its_controller(self):
        n, it, brief = self.dispatch_config('max_parallel_iterations = 1\n')
        release = self.root / 'release'
        self.env['WAIT_FOR'] = str(release)
        self.call('dispatch', '-n', n, '--brief', str(brief), '--detach')
        try:
            # E20: the main controller cannot change the iteration while its controller holds it.
            refused = self.call('new', '-n', n, good=False)
            self.assertEqual(refused.returncode, 3)
            self.assertIn('held by its dispatched controller', refused.stderr)
            self.assertIn('held by its dispatched controller', self.call('note', '-n', n, 'a note', good=False).stderr)
            # E21: one controller per iteration.
            self.assertIn('already has a running controller', self.call('dispatch', '-n', n, '--brief', str(brief), good=False).stderr)
            # The parallel limit.
            m = self.call('claim', '-t', 'another').stdout.split()[0]
            self.assertIn('max_parallel_iterations is 1', self.call('dispatch', '-n', m, '--brief', str(brief), good=False).stderr)
            # Only the controller hands back.
            self.assertIn('only the controller', self.call('dispatch', 'report', '-n', n, '--outcome', 'blocked',
                                                            '--summary', 'one two three four five', good=False).stderr)
            self.assertIn('running', self.call('dispatch', 'status', '-n', n).stdout)
        finally:
            release.touch()
        self.call('wait', '-n', n, '--timeout', '60', '--interval', '1', timeout=90)
        self.assertFalse((it / '.dispatch-lock').exists())
        self.call('note', '-n', n, 'the controller has finished')       # free again
        self.assertIn('exited 0', self.call('dispatch', 'status', '-n', n).stdout)

    def test_the_verifier_differs_from_controller_and_executor(self):
        # E22: with per-iteration controllers the executor's family counts too.
        n, it, _ = self.dispatch_config('executor = twin\nharness_twin_family = anthropic\nharness_twin_cmd = true\n')
        self.call('new', '-n', n)
        it.joinpath('README.md').write_text((self.it / 'README.md').read_text())
        self.call('gate', 'predeclare', '-n', n)
        report = it / f'results/report/iteration{n}_report.md'
        report.parent.mkdir(parents=True, exist_ok=True); report.write_text(self.report.read_text())
        self.assertIn('the executor (twin/anthropic)', self.call('ask', '-n', n, good=False).stderr)
        # The iteration's controller counts as its producer: an anthropic controller cannot be
        # reviewed by an anthropic verifier either.
        record = it / 'metadata/dispatch/001'; record.mkdir(parents=True)
        (record / 'run.json').write_text(json.dumps({'harness': 'reviewer'}))
        self.set_config('harnesses.md', executor='')
        self.assertIn('same model family', self.call('ask', '-n', n, '--terms-changed', 'executor removed', good=False).stderr)

    def test_activity_names_the_harness_session(self):
        self.set_config('harnesses.md', session_env='CLAUDE_CODE_SESSION_ID')
        self.env['CLAUDE_CODE_SESSION_ID'] = 'sess-abc'
        self.call('note', '-n', '1', 'a note from a recorded session')
        last = json.loads((self.it / 'metadata/activity.jsonl').read_text().splitlines()[-1])
        self.assertEqual((last['command'], last['harness_session']), ('arh note', 'CLAUDE_CODE_SESSION_ID=sess-abc'))
        shown = self.call('sessions', '-n', '1').stdout
        self.assertIn('CLAUDE_CODE_SESSION_ID=sess-abc', shown)
        self.assertIn('not in use (the project is not a git repository)', shown)
        self.set_config('harnesses.md', session_env='NO_SUCH_VARIABLE')
        self.call('note', '-n', '1', 'another note')
        last = json.loads((self.it / 'metadata/activity.jsonl').read_text().splitlines()[-1])
        self.assertIsNone(last['harness_session'])

    def test_entire_checkpoints_are_linked_to_the_iteration(self):
        git = ['git', '-C', str(self.root), '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.org',
               '-c', 'commit.gpgsign=false']
        subprocess.run(git + ['init', '-q'], check=True)
        subprocess.run(git + ['add', 'iterations/iteration1'], check=True)
        subprocess.run(git + ['commit', '-q', '-m', 'iteration 1 report\n\nEntire-Checkpoint: 01JFIXTURECHECKPOINT0000AB'], check=True)
        self.assertIn('01JFIXTURECHECKPOINT0000AB', self.call('sessions', '-n', '1').stdout)
        self.ask(); self.gate()
        receipt = json.loads((self.it / 'metadata/conclusions.jsonl').read_text().splitlines()[-1])
        self.assertEqual(receipt['entire_checkpoints'], ['01JFIXTURECHECKPOINT0000AB'])
        self.assertTrue(receipt['sessions'])

    def test_only_a_concluded_iteration_enters_memory(self):
        finding = 'The fixture passes its one check: one failure is rejected by the negative control.'
        self.assertIn('has not concluded', self.call('memory', 'add', '-n', '1', finding, good=False).stderr)
        self.ask(); self.gate()
        self.assertIn('state the finding', self.call('memory', 'add', '-n', '1', 'too short', good=False).stderr)
        self.assertIn('credential', self.call('memory', 'add', '-n', '1', 'the token is ghp_' + 'a' * 40 + ' found here',
                                              good=False).stderr)
        self.assertIn('recorded F1.1', self.call('memory', 'add', '-n', '1', finding).stdout)
        text = (self.root / 'knowledge/F1.1.md').read_text()
        self.assertTrue(text.startswith('---\nid: F1.1\niteration: 1\n'))
        self.assertIn('report_sha256: ' + hashlib.sha256(self.report.read_bytes()).hexdigest(), text)
        self.assertIn('verdicts: "SOUND"', text)
        self.assertIn('F1.1', self.call('memory', 'list').stdout)
        self.assertIn(finding, self.call('memory', 'show', 'F1.1').stdout)
        context = json.loads(self.call('context', '-n', '1').stdout)
        self.assertEqual(context['memory']['findings'][0]['id'], 'F1.1')
        # The evidence changes: the finding no longer rests on a conclusion.
        self.report.write_text(self.report.read_text() + 'Edited after the finding was recorded.\n')
        self.assertIn('no findings recorded that are current', self.call('memory', 'list').stdout)
        self.assertIn('stale', self.call('memory', 'list', '--all').stdout)
        self.assertEqual(json.loads(self.call('context', '-n', '1').stdout)['memory']['findings'], [])

    def test_a_later_finding_supersedes_an_earlier_one(self):
        self.ask(); self.gate()
        self.call('memory', 'add', '-n', '1', 'The first estimate is 0.0184 raw units, from the fixture.')
        n = self.call('claim', '-t', 'corrected', '--continues', '1').stdout.split()[0]
        it = self.root / f'iterations/iteration{n}'
        self.call('new', '-n', n); it.joinpath('README.md').write_text((self.it / 'README.md').read_text())
        self.call('gate', 'predeclare', '-n', n)
        report = it / f'results/report/iteration{n}_report.md'
        report.parent.mkdir(parents=True, exist_ok=True); report.write_text(self.report.read_text())
        self.call('ask', '-n', n); self.call('gate', 'results', '-n', n)
        self.assertIn('no finding F9.9', self.call('memory', 'add', '-n', n, '--supersedes', 'F9.9',
                                                   'The corrected estimate is 0.0200 raw units here.', good=False).stderr)
        self.assertIn('F1.1 is now superseded', self.call('memory', 'add', '-n', n, '--supersedes', 'F1.1',
                                                         'The corrected estimate is 0.0200 raw units here.').stdout)
        listed = self.call('memory', 'list').stdout
        self.assertIn(f'F{n}.1', listed); self.assertNotIn('F1.1', listed)
        self.assertIn(f'superseded by F{n}.1', self.call('memory', 'list', '--all').stdout)
        self.assertTrue((self.root / 'knowledge/F1.1.md').is_file())          # kept, not deleted

    def test_the_agent_session_is_found_for_any_configured_harness(self):
        # A harness the code knows nothing about: only its command template names its program.
        bindir = Path(self.temp.name) / 'agent-bin'; bindir.mkdir()
        agent = bindir / 'fakeagent'
        agent.write_text('#!/usr/bin/env bash\narh note -n 1 "written from inside the fake agent"\n'); agent.chmod(0o755)
        self.configure(extra_config='harness_fake_cmd = fakeagent {prompt}\n')
        self.env['PATH'] = f"{bindir}{os.pathsep}{self.env['PATH']}"
        self.env.pop('CLAUDE_CODE_SESSION_ID', None)
        subprocess.run([str(agent)], env=self.env, cwd=self.root, check=True, capture_output=True)
        last = json.loads((self.it / 'metadata/activity.jsonl').read_text().splitlines()[-1])
        self.assertTrue(last['agent_process'].startswith('fake:'), last)
        self.assertIn(last['agent_process'], self.call('sessions', '-n', '1').stdout)
        self.call('note', '-n', '1', 'not from inside an agent')
        self.assertIsNone(json.loads((self.it / 'metadata/activity.jsonl').read_text().splitlines()[-1])['agent_process'])

    def test_a_fresh_home_records_the_template_it_ran(self):
        _, work, summary = self.replication_fixture('fresh')
        record = json.loads((work / 'HOME.json').read_text())
        self.assertIn('{prompt}', record['command_template'])
        self.assertIn('pinned model', record['note'])
        self.assertIn('HOME.json records the template', summary)

    def test_a_dispatched_controller_can_start_with_a_fresh_home(self):
        operator = Path(self.temp.name) / 'operator-home'
        (operator / '.claude-mem').mkdir(parents=True); (operator / '.claude-mem/memory.db').write_text('earlier iterations')
        self.env['HOME'] = str(operator)
        n, it, brief = self.dispatch_config('dispatch_home = fresh\nfresh_home_files =\n')
        controller = self.root / 'controller.py'
        controller.write_text("import os\nfrom pathlib import Path\n"
                              "print('memory_visible', (Path(os.environ['HOME']) / '.claude-mem/memory.db').exists())\n")
        self.call('dispatch', '-n', n, '--brief', str(brief), timeout=120)
        record = it / 'metadata/dispatch/001'
        self.assertIn('memory_visible False', (record / 'session.log').read_text())
        self.assertEqual(json.loads((record / 'run.json').read_text())['home'], 'fresh')

    # Built from parts so the source never holds a webhook-shaped literal (GitHub push protection).
    HOOK = 'https://hooks.slack.com/services/' + '/'.join(('T01ABCDEF12', 'B01ABCDEF34', 'abcdefghijklmnopqrstuvwx'))

    @needs_gitleaks
    def test_gitleaks_rules_apply_on_top_of_the_built_in_patterns(self):
        # A Slack webhook URL: no built-in pattern models it; gitleaks has a rule for it.
        self.report.write_text(self.report.read_text() + f'Alerts go to {self.HOOK}.\n')
        self.assertIn('gitleaks: slack-webhook-url', self.call('ask', '-n', '1', good=False).stderr)
        self.configure(extra_config='secret_scanner = builtin\n')
        self.call('ask', '-n', '1')

    @needs_gitleaks
    def test_gitleaks_redacts_a_dispatched_session_log(self):
        log = self.root / 'session.log'
        log.write_text(f'posting to {self.HOOK} now\n')
        out = subprocess.run([sys.executable, str(ROOT / 'lib/secret_scan.py'), 'redact', str(log)],
                             env=self.env, capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), '1')
        self.assertIn('[REDACTED gitleaks: slack-webhook-url]', log.read_text())

    def test_a_required_scanner_that_is_missing_stops_the_request(self):
        self.env['PATH'] = os.pathsep.join(p for p in self.env['PATH'].split(os.pathsep)
                                           if not (Path(p) / 'gitleaks').exists())
        self.configure(extra_config='secret_scanner = gitleaks\n')
        refused = self.call('ask', '-n', '1', good=False)
        self.assertIn('gitleaks is not on PATH', refused.stderr)
        self.assertIn('could not run', refused.stderr)
        self.assertFalse(list(self.it.glob('CROSSCHECK_*')))

    # The JSON shape Entire CLI 0.11.5 printed for a real checkpoint (2026-10-16), trimmed.
    ENTIRE_JSON = {"checkpoint_id": "01JFIXTURECHECKPOINT0000AB", "sessions": [{
        "index": 0, "session_id": "1ef98e50-36fd-4e2a-813b-75343ec1a214", "agent": "Claude Code",
        "model": "claude-opus-5-5", "token_usage": {"input_tokens": 4, "cache_creation_tokens": 15218,
                                                   "cache_read_tokens": 30147, "output_tokens": 420,
                                                   "api_call_count": 2}}]}

    def test_entire_supplies_agent_model_and_tokens_when_installed(self):
        git = ['git', '-C', str(self.root), '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.org',
               '-c', 'commit.gpgsign=false']
        subprocess.run(git + ['init', '-q'], check=True)
        subprocess.run(git + ['add', 'iterations/iteration1'], check=True)
        subprocess.run(git + ['commit', '-q', '-m', 'iteration 1\n\nEntire-Checkpoint: 01JFIXTURECHECKPOINT0000AB'], check=True)
        bindir = Path(self.temp.name) / 'entire-bin'; bindir.mkdir()
        stub = bindir / 'entire'
        stub.write_text('#!/usr/bin/env python3\nimport json, sys\n'
                        'assert sys.argv[1:3] == ["checkpoint", "explain"] and "--json" in sys.argv\n'
                        f'print(json.dumps({self.ENTIRE_JSON!r}))\n'); stub.chmod(0o755)
        self.env['PATH'] = f"{bindir}{os.pathsep}{self.env['PATH']}"
        shown = self.call('sessions', '-n', '1').stdout
        self.assertIn('Claude Code (claude-opus-5-5), session 1ef98e50-36fd-4e2a-813b-75343ec1a214, 45789 tokens', shown)
        self.ask(); self.gate()
        receipt = json.loads((self.it / 'metadata/conclusions.jsonl').read_text().splitlines()[-1])
        self.assertEqual(receipt['entire_sessions']['01JFIXTURECHECKPOINT0000AB'][0]['model'], 'claude-opus-5-5')

    def test_memory_search_uses_a_configured_tool_or_a_word_match(self):
        self.ask(); self.gate()
        self.call('memory', 'add', '-n', '1', 'No sample is empty; every sample has reads in at least 10,000 genes.')
        self.assertIn('F1.1', self.call('memory', 'search', 'empty', 'sample').stdout)
        self.assertIn('no current finding', self.call('memory', 'search', 'nothing', 'like', 'this').stdout)
        stub = self.root / 'search.py'
        stub.write_text('import sys\nprint("searched", sys.argv[1:])\n')
        self.configure(extra_config=f'memory_search_cmd = python3 {stub} {{query}} --in {{dir}}\n')
        out = self.call('memory', 'search', 'empty', 'sample').stdout
        self.assertIn("'empty sample', '--in', '" + str(self.root / 'knowledge') + "'", out)

    def test_a_finding_reformatted_by_a_markdown_tool_still_reads(self):
        # The front matter as basic-memory 0.23.2 rewrote it (2026-10-16): no quotes, a block list,
        # a datetime and a permalink.
        self.ask(); self.gate()
        self.call('memory', 'add', '-n', '1', 'The fixture passes its one check under a SOUND review.')
        path = self.root / 'knowledge/F1.1.md'
        meta = dict(re.findall(r'(?m)^(report_sha256|predeclaration_sha256): (\S+)$', path.read_text()))
        path.write_text('---\nid: F1.1\niteration: 1\nquestion: q1\ntitle: validation\n'
                        'recorded: 2026-10-16 10:39:16+00:00\nverdicts: SOUND\n'
                        f"predeclaration_sha256: {meta['predeclaration_sha256']}\nreport_sha256: {meta['report_sha256']}\n"
                        'reviews:\n- CROSSCHECK_adversary_reviewer_x.md\npermalink: knowledge/f1.1\n---\n\n'
                        'The fixture passes its one check under a SOUND review.\n')
        self.assertIn('F1.1', self.call('memory', 'list').stdout)
        self.assertEqual(json.loads(self.call('context', '-n', '1').stdout)['memory']['findings'][0]['id'], 'F1.1')

    def test_a_milder_second_review_does_not_answer_an_unsound_one(self):
        self.configure("print('VERDICT: UNSOUND')")
        self.ask()
        self.configure("print('VERDICT: SOUND')")
        self.call('ask', '-n', '1', '--note', 'asking again')
        self.assertIn('UNSOUND, with no recorded answer', self.gate(good=False).stdout)

    def declare(self, title, body):
        n = self.call('claim', '-t', title).stdout.split()[0]
        self.call('new', '-n', n)
        it = self.root / f'iterations/iteration{n}'
        (it / 'README.md').write_text(body)
        return n, it

    def test_empty_sections_do_not_freeze(self):
        headings = ['Question', 'Estimand', 'Instrument', 'Acceptance criteria', 'Negative controls', 'Detection limit', 'Prediction']
        n, it = self.declare('empty', ''.join(f'## {h}\n\n<!-- nothing yet -->\n\n' for h in headings))
        result = self.call('gate', 'predeclare', '-n', n, good=False)
        self.assertIn('section empty: Question', result.stdout)
        self.assertFalse((it / 'PREDECLARATION.sha256').exists())
        # The template's own instructions are not content either.
        template = (ROOT / 'templates/iteration/README.md').read_text()
        boiler = ''.join(f'## {h}\n\n' for h in headings[:2]) + template[template.index('## 3. Instrument'):]
        boiler = re.sub(r'(?ms)^<.*?>\n', 'Filled.\n', boiler).replace('## 3. Instrument\n\nFilled.', '## 3. Instrument\n')
        (it / 'README.md').write_text(boiler)
        self.assertIn('section empty: Instrument', self.call('gate', 'predeclare', '-n', n, good=False).stdout)

    def test_deleting_the_freeze_does_not_reopen_the_plan(self):
        frozen = (self.it / 'PREDECLARATION.sha256').read_text()
        (self.it / 'PREDECLARATION.sha256').unlink()
        self.report.unlink()
        result = self.call('gate', 'predeclare', '-n', '1', good=False)
        self.assertIn('a plan is frozen once', result.stderr)
        # A hand-written freeze of an edited plan is caught at the results gate and by the ledger.
        (self.it / 'README.md').write_text((self.it / 'README.md').read_text() + 'Edited to fit.\n')
        digest = hashlib.sha256((self.it / 'README.md').read_bytes()).hexdigest()
        (self.it / 'PREDECLARATION.sha256').write_text(digest + '\n' + frozen.splitlines()[1] + '\n')
        self.report.write_text('Negative controls reject failures. Detection limit: one check. Candidate only.\n')
        self.ask()
        self.assertIn('the plan was frozen again', self.gate(good=False).stdout)
        self.call('ledger', 'render')
        self.assertIn('frozen again', self.call('ledger', 'check', good=False).stdout)

    def test_a_run_or_review_blocks_a_late_declaration(self):
        n, it = self.declare('late', (self.it / 'README.md').read_text())
        receipt = it / 'logs/nextflow/run/attempt-x/run.json'
        receipt.parent.mkdir(parents=True)
        receipt.write_text('{"exit_code": 0}\n')
        self.assertIn('1 run receipt(s)', self.call('gate', 'predeclare', '-n', n, good=False).stdout)

    def test_journal_is_a_hash_chain(self):
        self.ask()
        self.declare('second', (self.it / 'README.md').read_text())
        self.call('gate', 'predeclare', '-n', '2')
        journal = self.root / '.arh/freezes.tsv'
        rows = journal.read_text().splitlines()
        self.assertEqual([r.split('\t')[0] for r in rows[1:]], ['1', '2'])
        self.call('ledger', 'render')
        self.call('ledger', 'check')
        journal.write_text('\n'.join([rows[0], rows[2]]) + '\n')     # iteration 1's row removed
        self.assertIn('does not chain', self.call('ledger', 'check', good=False).stdout)

    def test_ledger_check_reads_the_claim_registry(self):
        self.declare('to be deleted', 'x')
        self.call('ledger', 'render'); self.call('ledger', 'check', good=None)
        shutil.rmtree(self.root / 'iterations/iteration2')
        self.call('ledger', 'render')
        self.assertIn('iteration 2 — in the claim registry, but its directory is gone',
                      self.call('ledger', 'check', good=False).stdout)

    def test_freeze_anchor_is_journalled_and_a_failing_anchor_freezes_nothing(self):
        cfg = self.root / '.arh/config/project.md'
        cfg.write_text(cfg.read_text().replace('freeze_anchor     =', 'freeze_anchor     = echo anchored {iteration} {sha256}'))
        n, it = self.declare('anchored', (self.it / 'README.md').read_text())
        self.call('gate', 'predeclare', '-n', n)
        row = (self.root / '.arh/freezes.tsv').read_text().splitlines()[-1].split('\t')
        self.assertEqual(row[3], f'anchored {n} {row[1]}')
        cfg.write_text(cfg.read_text().replace('echo anchored {iteration} {sha256}', 'false'))
        n, it = self.declare('unanchored', (self.it / 'README.md').read_text())
        self.assertIn('freeze_anchor failed', self.call('gate', 'predeclare', '-n', n, good=False).stderr)
        self.assertFalse((it / 'PREDECLARATION.sha256').exists())

    def test_scripts_edited_after_a_completed_run_are_named(self):
        for i, (digest, code) in enumerate([('a', 0), ('b', 0)]):
            receipt = self.it / f'logs/nextflow/main/attempt-{i}/run.json'
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({'started': f'2026-10-15T0{i}', 'exit_code': code, 'workflow': 'w.nf',
                                           'workflow_sha256': 'w', 'script_sha256': {'s.py': digest}}))
        self.ask()
        result = self.gate()
        self.assertIn('2 attempt(s) of 1 named workflow(s), 2 completed', result.stdout)
        self.assertIn('1 file(s) a completed run used were edited and run again: s.py', result.stdout)

    def test_migrate_backfills_the_journal_but_never_a_journalled_iteration(self):
        journal = self.root / '.arh/freezes.tsv'
        claim = json.loads((self.it / 'CLAIM.json').read_text())
        claim.pop('freeze_journal'); (self.it / 'CLAIM.json').write_text(json.dumps(claim))
        journal.unlink()                # a study frozen before the journal existed
        self.ask()
        self.assertIn('no freeze journal', self.gate().stdout)
        self.assertIn('backfilled for 1', self.call('migrate', str(self.root), '--apply').stdout)
        self.assertIn('backfilled by arh migrate', journal.read_text())
        self.gate()
        n, it = self.declare('journalled', (self.it / 'README.md').read_text())
        self.call('gate', 'predeclare', '-n', n)
        journal.write_text(''.join(journal.read_text().splitlines(True)[:2]))   # its row removed
        self.assertNotIn('backfilled', self.call('migrate', str(self.root)).stdout)

    def test_unchanged_review_reused(self):
        self.ask(); result=self.ask()
        self.assertIn('no model call', result.stdout)
        self.assertEqual(len(list(self.it.glob('CROSSCHECK_*.md.json'))), 1)

    def test_review_round_limit(self):
        self.ask(); self.call('ask', '-n', '1', '--note', 'Concrete second check')
        self.call('ask', '-n', '1', '--note', 'Third check exceeds budget', good=False)
        self.assertEqual(len(list(self.it.glob('CROSSCHECK_*.md.json'))), 2)

    def test_provider_error_does_not_consume_round(self):
        # codex exec printed this and exited 0 on a real cluster (2026-09-10).
        self.configure("print(\"ERROR: You've hit your usage limit. Try again at 4:13 PM.\")")
        result = self.ask(good=False)
        self.assertIn('did not consume a review round', result.stderr)
        self.assertIn('PROVIDER ERROR', self.call('gate', 'results', '-n', '1', good=False).stdout)
        self.configure()
        self.ask()                                   # first real round: no --note required
        self.call('ask', '-n', '1', '--note', 'Concrete second check')
        self.assertEqual(len(list(self.it.glob('CROSSCHECK_*.md.json'))), 3)
        self.gate()

    def test_rule_violation_blocks_review_before_dispatch(self):
        # A report the results gate will reject must not be sent for review: fixing it afterwards
        # invalidates the review and costs a round (2026-09-11).
        # Violates detection-limit-stated (it never states one); every other rule is satisfied.
        self.report.write_text('Negative controls reject failures. Candidate only.\n')
        result = self.ask(good=False)
        self.assertIn('standing rules', result.stderr)
        self.assertFalse(list(self.it.glob('CROSSCHECK_*.md.json')))

    def test_verbose_stderr_does_not_abort_review(self):
        # codex exec echoes the entire prompt to stderr; a 16 KB stderr cap killed every real
        # review (exit 66) before the model answered (2026-09-11).
        self.configure("import sys; sys.stderr.write('x' * 40000); print('VERDICT: SOUND')")
        self.ask(); self.gate()

    def test_input_budget_prevents_dispatch(self):
        result = self.call('ask', '-n', '1', '--note', 'x'*49000, good=False)
        self.assertFalse(list(self.it.glob('CROSSCHECK_*.md.json')))
        # The refusal names the size, the limit and the parts (field report, 2026-09-11).
        self.assertIn('ask_max_input_bytes is 48000', result.stderr)
        self.assertIn('pre-declaration', result.stderr)

    def test_output_budget_rejects_incomplete_review(self):
        self.configure("print('VERDICT: SOUND'); print('x'*12000)")
        self.ask(good=False); self.gate(good=False)

    def test_context_is_bounded_and_deterministic(self):
        first=self.call('context', '-n', '1').stdout
        self.assertEqual(first,self.call('context','-n','1').stdout)
        self.assertLess(len(first.encode()),8000)
        self.assertEqual(json.loads(first)['predeclaration'],'frozen')

    def configure_generator(self, body=None):
        generator = self.root / 'generator.py'
        generator.write_text(body or '''import pathlib,sys
request,output,phase,iteration = pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2]),sys.argv[3],sys.argv[4]
(output/'proposal.txt').write_text(f'{phase}:{iteration}\\n')
print('PROPOSAL: '+request.read_text().splitlines()[0])
''')
        cfg = self.root / '.arh/config/generators.md'
        text = cfg.read_text()
        text = text.replace('generator_biomni_enabled = false', 'generator_biomni_enabled = true')
        text = text.replace(
            'generator_biomni_cmd =',
            f'generator_biomni_cmd = python3 "{generator}" {{request}} {{output}} {{phase}} {{iteration}}',
        )
        text = text.replace(
            'generator_biomni_version_cmd =',
            'generator_biomni_version_cmd = python3 --version',
        )
        cfg.write_text(text)
        return cfg

    def test_generator_registry_is_disabled_by_default(self):
        result = self.call('evoke', 'list')
        for name in ('biomni', 'ai-scientist-v2', 'agent-laboratory'):
            self.assertIn(name, result.stdout)
        self.assertEqual(result.stdout.count('disabled'), 3)
        self.call('evoke', 'unknown', '-n', '1', '--phase', 'plan', good=False)

    def test_evocation_requires_explicit_external_acknowledgement(self):
        self.configure_generator()
        self.call('evoke', 'biomni', '-n', '1', '--phase', 'plan', good=False)
        self.assertFalse((self.it / 'metadata/evocations').exists())

    def test_evocation_dry_run_sends_nothing_and_records_nothing(self):
        self.configure_generator()
        marker = self.root / 'should-not-exist'
        result = self.call(
            'evoke', 'biomni', '-n', '1', '--phase', 'plan',
            '--note', f'literal $(touch {marker})', '--dry-run',
        )
        self.assertIn('# command (not run)', result.stdout)
        self.assertIn('literal $(touch', result.stdout)
        self.assertFalse(marker.exists())
        self.assertFalse((self.it / 'metadata/evocations').exists())

    def test_evocation_is_hash_bound_and_advisory(self):
        cfg = self.configure_generator()
        result = self.call(
            'evoke', 'biomni', '-n', '1', '--phase', 'plan',
            '--note', 'propose one bounded analysis', '--allow-external',
        )
        self.assertIn('response:', result.stdout)
        runs = list((self.it / 'metadata/evocations').iterdir())
        self.assertEqual(len(runs), 1)
        run = runs[0]
        record = json.loads((run / 'run.json').read_text())
        self.assertEqual(record['schema'], 'arh-evocation-v1')
        self.assertEqual(record['tool'], 'biomni')
        self.assertEqual(record['phase'], 'plan')
        self.assertEqual(record['exit_code'], 0)
        self.assertEqual(record['config_sha256'], hashlib.sha256(cfg.read_bytes()).hexdigest())
        self.assertEqual(record['request_sha256'], hashlib.sha256((run/'request.md').read_bytes()).hexdigest())
        self.assertEqual((run/'artifacts/proposal.txt').read_text(), 'plan:1\n')
        self.assertIn('PROPOSAL:', (run/'response.md').read_text())
        self.assertFalse((self.it / 'results').joinpath('evocations').exists())

    def test_failed_evocation_retains_receipt(self):
        self.configure_generator("import sys; print('partial'); raise SystemExit(9)\n")
        result = self.call(
            'evoke', 'biomni', '-n', '1', '--phase', 'plan',
            '--allow-external', good=False,
        )
        self.assertIn('record retained', result.stderr)
        run = next((self.it/'metadata/evocations').iterdir())
        self.assertEqual(json.loads((run/'run.json').read_text())['exit_code'], 9)
        self.assertIn('partial', (run/'response.md').read_text())

    @needs_site
    def test_named_launch_lock(self):
        lock=self.it/'metadata/nextflow/busy/.launch-lock'; lock.mkdir(parents=True)
        script=self.it/'scripts/it1_01_busy.nf'; script.write_text('workflow {}')
        result=self.call('submit',str(script),'-n','busy',good=False)
        self.assertIn('already running',result.stderr)

    @needs_site
    def test_live_owner_lock_is_kept(self):
        lock=self.it/'metadata/nextflow/busy/.launch-lock'; lock.mkdir(parents=True)
        (lock/'owner.json').write_text(json.dumps({'host': socket.gethostname(), 'pid': os.getpid()}))
        script=self.it/'scripts/it1_01_busy.nf'; script.write_text('workflow {}')
        result=self.call('submit',str(script),'-n','busy',good=False)
        self.assertIn('already running',result.stderr); self.assertTrue(lock.is_dir())

    @needs_site
    def test_dead_owner_lock_reclaimed_and_scripts_hashed(self):
        # A wrapper killed before its `finally` left .launch-lock behind and every later submit
        # under that name refused; the receipt also hashed the workflow but not the scripts it
        # calls (2026-09-11).
        dead=subprocess.Popen(['true']); dead.wait()
        lock=self.it/'metadata/nextflow/ok/.launch-lock'; lock.mkdir(parents=True)
        (lock/'owner.json').write_text(json.dumps({'host': socket.gethostname(), 'pid': dead.pid}))
        (self.it/'scripts/it1_00_helper.py').write_text('print(1)\n')
        script=self.it/'scripts/it1_01_ok.sh'; script.write_text('set -euo pipefail\nexit 0\n')
        result=self.call('submit',str(script),'-n','ok')
        self.assertIn('reclaimed a launch lock',result.stderr); self.assertFalse(lock.exists())
        record=json.loads(next((self.it/'logs/nextflow/ok').glob('attempt-*/run.json')).read_text())
        self.assertIn('iterations/iteration1/scripts/it1_00_helper.py',record['script_sha256'])

    @needs_site
    def test_sigterm_to_wrapper_releases_lock(self):
        # Stopping a submit by signalling its wrapper left the lock behind (2026-09-11). The
        # wrapper now forwards the signal to Nextflow, records it, and releases the lock.
        script=self.it/'scripts/it1_01_slow.sh'; script.write_text('sleep 300\n')
        proc=subprocess.Popen([str(ROOT/'bin/arh'),'submit',str(script),'-n','slow'],env=self.env,cwd=self.root,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        work=self.it/'metadata/nextflow/slow/work'; deadline=time.time()+120
        while proc.poll() is None and time.time()<deadline and not list(work.glob('*/*/.command.begin')):
            time.sleep(0.5)
        if proc.poll() is not None:     # build the message only on failure: communicate() blocks
            self.fail('submit ended before its task started: '+proc.communicate()[1][-2000:])
        proc.send_signal(signal.SIGTERM); out,err=proc.communicate(timeout=120)
        self.assertNotEqual(proc.returncode,0,err)
        self.assertFalse((self.it/'metadata/nextflow/slow/.launch-lock').exists())
        record=json.loads(next((self.it/'logs/nextflow/slow').glob('attempt-*/run.json')).read_text())
        self.assertEqual(record['signal'],'SIGTERM')

    def legacy_study(self):
        """A minimal 0.1-layout study built from the current templates."""
        old = Path(self.temp.name) / 'legacy'
        (old / '.dl/config').mkdir(parents=True); (old / 'rules').mkdir()
        for name in ('site.md', 'project.md', 'harnesses.md'):
            (old / '.dl/config' / name).write_text((ROOT / 'config' / name).read_text().replace('arh-config', 'dl-config'))
        for rule in (ROOT / 'config/rules').glob('*.md'):
            (old / 'rules' / rule.name).write_text(rule.read_text().replace('arh-config', 'dl-config'))
        (old / '.dl/VERSION').write_text('protocol = 0.1.0\n')
        (old / '.dl/registry.tsv').write_text('iteration\tagent\tclaimed\tstatus\ttitle\n')
        (old / 'PROGRESS.md').write_text('# PROGRESS\n\n<!-- dl:status:begin — generated by `dl ledger render`; '
                                         'do not edit by hand -->\n| 1 | old |\n<!-- dl:status:end -->\n\n'
                                         'Iteration 1: `dl gate results` passed.\n')
        (old / 'AGENTS.md').write_text('# Automated discovery loop — agent contract\n\nUse `dl claim`.\n')
        it = old / 'iterations/iteration1'; it.mkdir(parents=True)
        (it / 'README.md').write_text('A frozen pre-declaration that mentions dl-config.\n')
        (it / 'CLAIM.json').write_text('{\n  "iteration": 1,\n  "declared_agent": "old",\n  "title": "legacy question"\n}\n')
        (old / 'iterations/iteration2').mkdir()                    # an iteration folder with no claim record
        return old

    def test_migrate_legacy_study(self):
        # Moving a real 0.1 study by hand took eight steps and missed the ledger markers (2026-09-11).
        old = self.legacy_study(); readme = (old / 'iterations/iteration1/README.md').read_bytes()
        env = dict(self.env, ARH_PROJECT=str(old))
        run = lambda *a: subprocess.run([str(ROOT / 'bin/arh'), 'migrate', str(old), *a], env=env, cwd=old,  # noqa: E731
                                        capture_output=True, text=True, timeout=120)
        dry = run()
        self.assertEqual(dry.returncode, 0, dry.stderr); self.assertIn('would change', dry.stdout)
        self.assertFalse((old / '.dl').is_symlink()); self.assertFalse((old / '.arh').exists())
        applied = run('--apply'); self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertTrue((old / '.arh').is_dir()); self.assertTrue((old / '.dl').is_symlink())
        for p in [*(old / '.arh/config').glob('*.md'), *(old / 'rules').glob('*.md')]:
            self.assertNotRegex(p.read_text(), r'(?m)^\s*```\s*dl-config', p.name)
        ledger = (old / 'PROGRESS.md').read_text()
        self.assertIn('arh:status:begin', ledger); self.assertNotIn('dl:status', ledger)
        self.assertIn('`dl gate results` passed', ledger)          # the record's prose is left as written
        protocol = re.search(r'protocol, v(\S+)', (ROOT / 'PROTOCOL.md').read_text()).group(1)
        self.assertIn(f'protocol = {protocol}', (old / '.arh/VERSION').read_text())
        self.assertTrue((old / 'AGENTS.md').read_text().startswith('# AutoResearch HPC'))
        self.assertTrue((old / 'skills/iterate/SKILL.md').is_file())
        self.assertTrue((old / '.arh/config/generators.md').is_file())
        self.assertEqual((old / 'iterations/iteration1/README.md').read_bytes(), readme)
        self.assertTrue(list((old / '.arh').glob('migration-backup-*.tgz')))
        subprocess.run([str(ROOT / 'bin/arh'), 'ledger', 'render'], env=env, cwd=old, check=True, capture_output=True)
        self.assertEqual((old / 'PROGRESS.md').read_text().count('status:begin'), 1)
        self.assertIn('nothing to do', run('--apply').stdout)

    def test_ledger_render_refuses_a_foreign_status_block(self):
        ledger = self.root / 'PROGRESS.md'
        text = ledger.read_text().replace('arh:status:', 'old:status:'); ledger.write_text(text)
        self.assertIn("'old:status'", self.call('ledger', 'render', good=False).stderr)
        self.assertEqual(ledger.read_text(), text)

    def test_ledger_check_detects_a_stale_table(self):
        self.ask(); self.call('ledger', 'render'); self.call('ledger', 'check')
        ledger = self.root / 'PROGRESS.md'
        ledger.write_text(ledger.read_text().replace('| frozen |', '| draft |'))
        self.assertIn('stale', self.call('ledger', 'check', good=False).stdout)
        self.call('ledger', 'render'); self.call('ledger', 'check')

    def test_rule_scope_paragraph(self):
        # One qualifier anywhere used to excuse every use of a forbidden term (2026-09-11).
        rule = self.root / 'rules/recall-scoped.md'
        body = 'id = recall-scoped\nseverity = error\napplies = report\nforbid = recall\nrequires = end.to.end\n'
        rule.write_text(f'```arh-config\n{body}scope = paragraph\n```\n')
        project = self.root / '.arh/config/project.md'
        project.write_text(re.sub(r'(?m)^(rules\s*=.*)$', r'\1 recall-scoped', project.read_text()))
        doc = self.root / 'doc.md'
        base = 'Negative controls did not fire. Detection limit: one event.\n\nEnd-to-end recall is 50%.\n\n'
        doc.write_text(base + 'Recall rose.\n')
        self.assertIn('a paragraph uses', self.call('gate', 'rules', str(doc), good=False).stdout)
        doc.write_text(base + 'End-to-end recall rose.\n'); self.call('gate', 'rules', str(doc))
        rule.write_text(f'```arh-config\n{body}```\n')             # default scope: document, as before
        doc.write_text(base + 'Recall rose.\n'); self.call('gate', 'rules', str(doc))

    def test_review_records_verifier_version(self):
        # The record named the verifier's family but not the build that answered (2026-09-11).
        self.configure(version='python3 -c "print(\'mock-cli 1.2.3\')"')
        self.ask()
        record = json.loads(next(self.it.glob('CROSSCHECK_*.md.json')).read_text())
        self.assertEqual(record['verifier_version'], 'mock-cli 1.2.3')
        self.gate()

    def test_doctor_names_a_protocol_mismatch(self):
        self.assertNotIn('records protocol', self.call('doctor', good=None).stdout)
        (self.root / '.arh/VERSION').write_text('protocol = 0.1.0\n')
        result = self.call('doctor', good=False)
        self.assertIn('records protocol 0.1.0', result.stdout); self.assertIn('arh migrate', result.stdout)

    def test_gate_warns_without_review_response(self):
        self.ask()
        self.assertIn('no REVIEW_RESPONSE.md', self.gate().stdout)
        (self.it / 'REVIEW_RESPONSE.md').write_text('Finding 1: accepted.\n')
        self.assertNotIn('no REVIEW_RESPONSE.md', self.gate().stdout)

    def test_claim_records_agent_source(self):
        env = {k: v for k, v in self.env.items() if not k.startswith(('CLAUDE', 'CODEX', 'OPENCODE', 'ARH_AGENT'))}
        def claim(title, **extra):
            result = subprocess.run([str(ROOT / 'bin/arh'), 'claim', '-t', title], env={**env, **extra},
                                    cwd=self.root, capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads((self.root / f'iterations/iteration{result.stdout.strip()}/CLAIM.json').read_text())
            return record, result.stderr
        # An inherited harness marker does not get to name the agent: the configured
        # producer wins, and what the session reported is kept beside it.
        record, stderr = claim('inherited marker', CLAUDECODE='1')
        self.assertEqual((record['agent'], record['agent_source']), ('source', 'config:producer'))
        self.assertEqual((record['inferred_agent'], record['inferred_from']), ('claude', 'CLAUDECODE'))
        self.assertIn("configured producer is 'source'", stderr)

        # The agent contract tells a session to export ARH_AGENT=<its harness name>. That
        # used to overwrite a producer name pinning a model and account (benchmark study 10,
        # 2026-09-18: a claude_sonnet_main lane recorded itself as plain "claude"). The
        # configured producer outranks it, and the override is reported rather than silent.
        record, stderr = claim('agent overrides itself', CLAUDECODE='1', ARH_AGENT='claude')
        self.assertEqual((record['agent'], record['agent_source']), ('source', 'config:producer'))
        self.assertEqual((record['inferred_agent'], record['inferred_from']), ('claude', 'ARH_AGENT'))
        self.assertIn("configured producer is 'source'", stderr)

        # Agreement between the session and the configured producer stays quiet.
        record, stderr = claim('explicit agent', CLAUDECODE='1', ARH_AGENT='source')
        self.assertEqual((record['agent'], record['agent_source']), ('source', 'ARH_AGENT'))
        self.assertNotIn('configured producer', stderr)

    def test_same_family_review_counts_only_when_the_project_allows_it(self):
        # A model does not reliably catch its own reasoning errors, so a same-family review is a
        # weaker check and is refused by default. A project may accept one deliberately.
        self.configure(family='openai')                       # producer and verifier both openai
        refused = self.ask(good=False)
        self.assertIn('same model family', refused.stderr)

        # --same-family records the review but must never satisfy the gate.
        self.call('ask', '-n', '1', '--same-family')
        self.assertIn('no eligible cross-check', self.gate(good=False).stdout)
        for record in self.it.glob('CROSSCHECK_*'):     # all of them: the round budget counts files
            record.unlink()

        # With require_foreign_family = false the same review is a full cross-check, and the gate
        # says on every reading that it was accepted under that policy.
        self.configure(family='openai', extra_config='require_foreign_family = false\n')
        self.ask()
        record = json.loads(next(self.it.glob('CROSSCHECK_*.md.json')).read_text())
        self.assertIs(record['require_foreign_family'], False)
        out = self.gate().stdout
        self.assertIn('eligible review', out)
        self.assertIn('SOUND; same model family, accepted because require_foreign_family = false', out)

    def test_the_rule_a_review_passed_under_is_read_from_the_review(self):
        # Tightening the setting afterwards must not invalidate a review already taken, and
        # relaxing it must not retroactively validate one. The record, not today's config, decides.
        self.configure(family='openai', extra_config='require_foreign_family = false\n')
        self.ask()
        self.assertIn('eligible review', self.gate().stdout)

        self.configure(family='openai', bind=False)           # back to the strict default, after the review
        self.assertIn('eligible review', self.gate().stdout)

        record_path = next(self.it.glob('CROSSCHECK_*.md.json'))
        record = json.loads(record_path.read_text())
        record['require_foreign_family'] = True               # as a strict-era review would read
        record_path.write_text(json.dumps(record))
        self.assertIn('no eligible cross-check', self.gate(good=False).stdout)

    def test_delegate_records_who_did_the_work(self):
        self.configure(extra_config='executor = reviewer\n')
        self.assertIn('executor', self.call('delegate', 'list').stdout)

        task = self.root / 'task.md'
        task.write_text('Implement the pre-declared analysis.\n')
        dry = self.call('delegate', '--role', 'executor', '-n', '1', '--prompt', str(task), '--dry-run')
        self.assertIn('Implement the pre-declared analysis.', dry.stdout)
        self.assertFalse(list((self.it / 'metadata').glob('delegations/*')))   # a dry run writes nothing

        self.call('delegate', '--role', 'executor', '-n', '1', '--prompt', str(task))
        run = next((self.it / 'metadata/delegations').iterdir())
        self.assertEqual(run.name, '001-executor')
        record = json.loads((run / 'run.json').read_text())
        self.assertEqual((record['schema'], record['role'], record['harness']),
                         ('arh-delegation-v1', 'executor', 'reviewer'))
        self.assertEqual(record['exit_code'], 0)
        self.assertIn('VERDICT: SOUND', (run / 'response.md').read_text())
        # The frozen pre-declaration travels with the task; the response is not a result.
        self.assertIn('pre-declaration', (run / 'request.md').read_text())
        self.assertFalse((self.it / 'results' / 'response.md').exists())

    def test_delegate_refuses_an_unconfigured_role(self):
        self.configure()
        failed = self.call('delegate', '--role', 'executor', '-n', '1', good=False)
        self.assertIn('no harness configured for role', failed.stderr)
        self.assertIn('none configured', self.call('doctor', good=None).stdout)

    def test_content_refusal_is_its_own_outcome(self):
        # Codex refused a public RNA-seq count table as "flagged for possible biological risk"
        # (2026-09-15). Waiting does not change that, so it must not look like a quota error.
        self.configure(REFUSE)
        result = self.ask(good=False)
        self.assertEqual(result.returncode, 77, result.stderr)
        self.assertIn('content-policy', result.stderr)
        self.assertIn('provider said: This content was flagged', result.stderr)
        record = json.loads(next(self.it.glob('CROSSCHECK_*.md.json')).read_text())
        self.assertEqual((record['provider_error'], record['provider_error_kind']), (True, 'refusal'))
        self.assertIn('PROVIDER REFUSAL', self.gate(good=False).stdout)
        self.configure()
        self.ask()                                   # no round was spent: no --note required
        self.gate()

    def test_fallback_verifier_after_content_refusal(self):
        self.configure(REFUSE)
        backup = self.root / 'backup.py'
        backup.write_text("print('VERDICT: QUALIFIED')\n")
        with self.config.open('a') as cfg:
            cfg.write(f'```arh-config\nverifier_fallback = kin backup\n'
                      f'harness_kin_family = openai\nharness_kin_cmd = python3 "{backup}" {{prompt}}\n'
                      f'harness_backup_family = google\nharness_backup_cmd = python3 "{backup}" {{prompt}}\n```\n')
        self.bind_terms()
        result = self.ask()
        self.assertIn("fallback verifier 'kin' skipped", result.stderr)   # the producer's own family
        self.assertIn('VERDICT: QUALIFIED', result.stdout)
        kinds = sorted(json.loads(p.read_text())['provider_error_kind'] or 'review'
                       for p in self.it.glob('CROSSCHECK_*.md.json'))
        self.assertEqual(kinds, ['refusal', 'review'])
        self.gate()

    LIMIT = "print(\"ERROR: You've hit your usage limit. Try again at 4:13 PM.\")"

    def test_limit_names_its_reset(self):
        self.configure(self.LIMIT)
        result = self.ask(good=False)
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn('Try again at 4:13 PM', result.stderr)
        self.assertIn('upper bound', result.stderr)
        records = [json.loads(p.read_text()) for p in self.it.glob('CROSSCHECK_*.md.json')]
        self.assertEqual([(r['provider_error_kind'], r['retry_hint']) for r in records],
                         [('limit', 'Try again at 4:13 PM')])

    def test_fallback_verifier_after_limit(self):
        # A stated reset is not a schedule: one provider named a time five days out, and a probe
        # 44 minutes later succeeded (2026-09-16). Another family may review in the meantime.
        self.configure(self.LIMIT)
        backup = self.root / 'backup.py'
        backup.write_text("print('VERDICT: SOUND')\n")
        with self.config.open('a') as cfg:
            cfg.write(f'```arh-config\nverifier_fallback = backup\nharness_backup_family = google\n'
                      f'harness_backup_cmd = python3 "{backup}" {{prompt}}\n```\n')
        self.bind_terms()
        result = self.ask()
        self.assertIn("verifier 'reviewer' is unavailable", result.stderr)
        kinds = sorted(json.loads(p.read_text())['provider_error_kind'] or 'review'
                       for p in self.it.glob('CROSSCHECK_*.md.json'))
        self.assertEqual(kinds, ['limit', 'review'])
        self.gate()

    def test_expired_key_and_timeout_try_the_fallback_without_spending_a_round(self):
        # OpenCode exited 1 on "This API key has expired", so the fallback never ran (field feedback
        # #75); a verifier that timed out spent a review round and stopped the chain (#51).
        backup = self.root / 'backup.py'
        backup.write_text("print('VERDICT: SOUND')\n")
        fallback = (f'verifier_fallback = backup\nharness_backup_family = google\n'
                    f'harness_backup_cmd = python3 "{backup}" {{prompt}}\n')
        self.configure("import sys; sys.stderr.write('This API key has expired. Create a new API key in OpenCode "
                       "Console.\\n'); raise SystemExit(1)", extra_config=fallback)
        result = self.ask()
        self.assertIn("verifier 'reviewer' is unavailable", result.stderr)
        self.assertIn('provider said: This API key has expired', result.stderr)
        for old in self.it.glob('CROSSCHECK_*'):
            old.unlink()
        self.configure("import time; time.sleep(10)", timeout=1, extra_config=fallback)
        self.ask()
        records = {json.loads(p.read_text())['provider_error_kind'] or 'review': json.loads(p.read_text())
                   for p in self.it.glob('CROSSCHECK_*.md.json')}
        self.assertEqual(sorted(records), ['review', 'timeout'])
        self.assertEqual(records['timeout']['exit_code'], 124)
        # A slow harness gets its own bound.
        for old in self.it.glob('CROSSCHECK_*'):
            old.unlink()
        self.configure("import time; time.sleep(2); print('VERDICT: SOUND')", timeout=1,
                       extra_config='harness_reviewer_timeout = 30\n')
        self.ask(); self.gate()

    def test_provider_line_is_not_quoted_from_the_prompt(self):
        # `codex exec` echoes the prompt to stderr; a report that mentioned a usage limit was quoted
        # back as what the provider said (field feedback #76).
        self.report.write_text(self.report.read_text() + 'The tool stops at its usage limit of 10 jobs.\n')
        self.configure("import sys; sys.stderr.write(sys.argv[1] + '\\nERROR: rate limit reached, try again in 5 "
                       "minutes\\n'); raise SystemExit(1)")
        result = self.ask(good=False)
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn('provider said: ERROR: rate limit reached', result.stderr)
        self.assertNotIn('usage limit of 10 jobs', result.stderr)

    def test_predeclaration_can_have_its_own_input_cap(self):
        # A frozen 31.8 kB plan left the report three trims and a one-line note (#82, #89).
        size = len(self.call('ask', '-n', '1', '--dry-run').stdout.split('\n', 2)[2].encode())
        plan = (self.it / 'README.md').stat().st_size
        self.configure(extra_config=f'ask_max_input_bytes = {size - plan // 2}\n')
        result = self.ask(good=False)
        self.assertIn('ask_max_predeclaration_bytes', result.stderr)
        self.assertFalse(list(self.it.glob('CROSSCHECK_*')))
        self.configure(extra_config=f'ask_max_input_bytes = {size - plan // 2}\nask_max_predeclaration_bytes = {plan}\n')
        self.ask(); self.gate()
        self.configure(extra_config=f'ask_max_input_bytes = {size}\nask_max_predeclaration_bytes = {plan - 1}\n')
        self.assertIn('ask_max_predeclaration_bytes is', self.call('ask', '-n', '1', '--note', 'again', good=False).stderr)

    def test_doctor_probe_names_an_expired_verifier_login(self):
        self.configure("print('Error: your session has expired. Please log in again.')")
        out = self.call('doctor', '--probe', good=None).stdout
        self.assertIn('FAIL probe reviewer: auth: Error: your session has expired', out)
        self.configure("print('OK')")
        self.assertIn('OK   probe reviewer answered', self.call('doctor', '--probe', good=None).stdout)
        self.assertIn('arh doctor --probe makes one short call', self.call('doctor', good=None).stdout)

    def test_review_terms_are_bound_at_claim(self):
        # Nothing froze harnesses.md, so a producing agent could change the terms of its own
        # cross-check without a trace (2026-09-16). In the replication benchmark three agents raised
        # the input budget; one could as easily have swapped the verifier or relaxed the family rule.
        self.ask()
        sha = hashlib.sha256(self.config.read_bytes()).hexdigest()
        record = json.loads(next(self.it.glob('CROSSCHECK_*.md.json')).read_text())
        self.assertEqual((record['harness_config_sha256'], record['terms_changed']), (sha, None))
        for f in self.it.glob('CROSSCHECK_*'):          # all of them: the round budget counts files
            f.unlink()

        with self.config.open('a') as cfg:
            cfg.write('```arh-config\nask_max_input_bytes = 60000\n```\n')
        self.assertIn('changed since iteration 1 was claimed', self.ask(good=False).stderr)
        self.assertFalse(list(self.it.glob('CROSSCHECK_*')))          # refused before any model call
        self.call('ask', '-n', '1', '--terms-changed', 'packet is 49 kB')
        path = next(self.it.glob('CROSSCHECK_*.md.json'))
        record = json.loads(path.read_text())
        self.assertEqual((record['terms_changed'], record['terms_changed_keys']),
                         ('packet is 49 kB', {'ask_max_input_bytes': [None, '60000']}))
        self.assertIn('review terms | changed since the claim: packet is 49 kB', Path(str(path)[:-5]).read_text())
        self.assertIn('SOUND; review terms changed since the claim (ask_max_input_bytes): packet is 49 kB',
                      self.gate().stdout)

        # The recorded reason is what lets such a review count: without it the gate refuses.
        record['terms_changed'] = None
        path.write_text(json.dumps(record))
        self.assertIn('no eligible cross-check', self.gate(good=False).stdout)

        self.call('claim', '-t', 'after configuration')
        it2 = self.root / 'iterations/iteration2'
        self.assertEqual(json.loads((it2 / 'CLAIM.json').read_text())['harness_config_sha256'],
                         hashlib.sha256(self.config.read_bytes()).hexdigest())
        self.assertEqual((it2 / 'metadata/harnesses.claimed.md').read_bytes(), self.config.read_bytes())
        states = {i['iteration']: i['harness_config']
                  for i in json.loads(self.call('status', '--json').stdout)['iterations']}
        self.assertEqual(states, {1: 'changed', 2: 'unchanged'})
        self.assertIn('iteration(s) 1 were claimed', self.call('status').stdout)

    def test_relaxing_the_family_rule_after_the_claim_needs_a_reason(self):
        # require_foreign_family = false is a legitimate project policy. Set by the producer after
        # the claim, it relaxes the rules of its own cross-check, so the review must say why.
        self.configure(family='openai')                       # claimed under the strict default
        self.assertIn('same model family', self.ask(good=False).stderr)
        self.configure(family='openai', extra_config='require_foreign_family = false\n', bind=False)
        self.assertIn('changed since iteration 1 was claimed', self.ask(good=False).stderr)
        self.call('ask', '-n', '1', '--terms-changed', 'no foreign verifier available')
        out = self.gate().stdout
        self.assertIn('same model family, accepted because require_foreign_family = false', out)
        self.assertIn('review terms changed since the claim (require_foreign_family): no foreign verifier available', out)

    def test_claim_matches_its_schema(self):
        # CI checked only that the schema parses, so fields added to CLAIM.json drifted out of
        # a schema that forbids unknown properties.
        schema = json.loads((ROOT / 'schema/claim.schema.json').read_text())
        claim = json.loads((self.it / 'CLAIM.json').read_text())
        self.assertLessEqual(set(claim), set(schema['properties']))
        self.assertLessEqual(set(schema['required']), set(claim))
        self.assertRegex(claim['harness_config_sha256'], schema['properties']['harness_config_sha256']['pattern'])

    def test_harness_access_follows_inputs_and_web_policy(self):
        # Headless, OpenCode rejected a read of the declared inputs outside the project root
        # instead of asking, and nothing named the cause (2026-09-16).
        inputs = Path(self.temp.name) / 'inputs'
        inputs.mkdir()
        project = self.root / '.arh/config/project.md'
        project.write_text(project.read_text().replace('immutable_inputs  =', f'immutable_inputs  = {inputs}'))
        with self.config.open('a') as cfg:
            cfg.write('```arh-config\nweb_access = deny\n```\n')
        subprocess.run([str(ROOT / 'harness/install.sh'), str(self.root), 'opencode', 'claude'],
                       check=True, capture_output=True, env=self.env)
        real = os.path.realpath(inputs)
        oc = json.loads((self.root / 'opencode.json').read_text())['permission']
        self.assertEqual((oc['external_directory'][real + '/**'], oc['webfetch'], oc['websearch']),
                         ('allow', 'deny', 'deny'))
        claude = json.loads((self.root / '.claude/settings.json').read_text())['permissions']
        self.assertEqual((claude['additionalDirectories'], claude['deny']), ([real], ['WebFetch', 'WebSearch']))
        self.assertIn('harness access: declared inputs reachable', self.call('doctor', good=None).stdout)
        del oc['webfetch']
        (self.root / 'opencode.json').write_text(json.dumps({'permission': oc}))
        self.assertIn('opencode.json leaves webfetch on', self.call('doctor', good=None).stdout)

    def test_review_records_usage(self):
        # "Bounded model calls" bounded bytes, but nothing counted tokens (2026-09-14).
        self.configure("import json,sys; open(sys.argv[2],'w').write(json.dumps({'input_tokens': 7})); "
                       "print('VERDICT: SOUND')", cmd_extra=' {usage}')
        self.ask()
        record = json.loads(next(self.it.glob('CROSSCHECK_*.md.json')).read_text())
        self.assertEqual(record['usage'], {'input_tokens': 7})
        self.assertFalse(list(self.it.glob('*.usage.json')))
        self.gate()

    def test_review_lock_owner_and_reclaim(self):
        lock = self.it / '.review-lock'
        lock.mkdir()
        (lock / 'owner.json').write_text(json.dumps({'host': socket.gethostname(), 'pid': os.getpid()}))
        self.assertIn('another review is running', self.ask(good=False).stderr)
        dead = subprocess.Popen(['true']); dead.wait()
        (lock / 'owner.json').write_text(json.dumps({'host': socket.gethostname(), 'pid': dead.pid}))
        self.assertIn('reclaimed a review lock', self.ask().stderr)
        self.assertFalse(lock.exists())

    def test_wait_blocks_on_live_work_only(self):
        # Headless sessions that ended their reply to wait for background work lost it (2026-09-14).
        self.assertIn('idle', self.call('wait', '-n', '1', '--timeout', '5').stdout)
        lock = self.it / 'metadata/nextflow/busy/.launch-lock'
        lock.mkdir(parents=True)
        holder = subprocess.Popen(['sleep', '60'])
        try:
            (lock / 'owner.json').write_text(json.dumps({'host': socket.gethostname(), 'pid': holder.pid}))
            result = self.call('wait', '-n', '1', '--timeout', '1', '--interval', '0.2', good=False)
            self.assertEqual(result.returncode, 124)
            self.assertIn('iteration1: submission busy', result.stdout)
        finally:
            holder.kill(); holder.wait()
        result = self.call('wait', '-n', '1', '--timeout', '5', '--interval', '0.2')
        self.assertIn('ignored: iteration1: submission busy', result.stdout)
        self.assertIn('idle', result.stdout)

    def test_migrate_refreshes_agent_contract_and_skills(self):
        # Agents read the study's copies, so framework fixes to AGENTS.md never reached them (2026-09-15).
        agents, skill = self.root / 'AGENTS.md', self.root / 'skills/iterate/SKILL.md'
        agents.write_text('# stale contract\n'); skill.unlink()
        own = self.root / 'skills/local/SKILL.md'; own.parent.mkdir(); own.write_text('project skill\n')
        self.assertIn("differ from the framework's", self.call('doctor', good=None).stderr)
        migrate = lambda *a: self.call('migrate', str(self.root), *a)  # noqa: E731
        self.assertIn('agent contract refreshed', migrate().stdout)
        self.assertEqual(agents.read_text(), '# stale contract\n')     # a dry run writes nothing
        migrate('--apply')
        self.assertEqual(agents.read_text(), (ROOT / 'AGENTS.md').read_text())
        self.assertEqual(skill.read_text(), (ROOT / 'skills/iterate/SKILL.md').read_text())
        self.assertEqual(own.read_text(), 'project skill\n')
        self.assertTrue((self.root / 'CLAUDE.md').is_symlink())
        self.assertIn('nothing to do', migrate().stdout)

    def test_env_cache_builds_once_for_many_projects(self):
        # Every study built its own ~1.5 GB of environments (2026-09-14).
        fake = Path(self.temp.name) / 'fake'; fake.mkdir()
        log, mm = fake / 'creates.log', fake / 'micromamba'
        mm.write_text(f"""#!{sys.executable}
import sys
from pathlib import Path
args = sys.argv[1:]
if args[:1] == ['--version']:
    print('2.8.1'); sys.exit()
prefix = Path(args[args.index('-p') + 1])
if args[0] == 'create':
    with open({str(log)!r}, 'a') as fh:
        fh.write(str(prefix) + '\\n')
    (prefix / 'bin').mkdir(parents=True)
    (prefix / 'bin/python3').symlink_to({sys.executable!r})
    (prefix / 'bin/nextflow').write_text('#!/bin/sh\\n')
    (prefix / 'bin/nextflow').chmod(0o755)
elif args[0] == 'list':
    print('https://conda.example/pkg-1.0-0.conda#' + 'a' * 32)
""")
        singularity = fake / 'singularity'        # `exec [options] IMAGE micromamba ARGS` runs the fake
        singularity.write_text(f'#!/bin/sh\nwhile [ "$1" != micromamba ]; do shift; done\nshift\nexec "{mm}" "$@"\n')
        for tool in (mm, singularity):
            tool.chmod(0o755)
        image, cache = fake / 'runtime.sif', Path(self.temp.name) / 'cache'
        image.write_bytes(b'image')
        env = dict(self.env, PATH=str(fake) + os.pathsep + self.env['PATH'])
        prefixes = []
        for name in ('a', 'b'):
            project = Path(self.temp.name) / name
            result = subprocess.run([str(ROOT / 'bin/arh'), 'init', str(project), '--bootstrap', '--micromamba', str(mm),
                                     '--runtime', str(image), '--env-cache', str(cache)],
                                    env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            site = (project / '.arh/config/site.md').read_text()
            prefixes.append([re.search(rf'(?m)^{key}\s*=\s*(\S+)', site).group(1) for key in ('nextflow_prefix', 'runtime_prefix')])
            self.assertTrue((project / '.arh/nextflow-host-explicit.lock').is_file())
        self.assertEqual(prefixes[0], prefixes[1])
        for prefix in prefixes[0]:
            self.assertTrue(prefix.startswith(str(cache)), prefix)
            self.assertTrue(Path(prefix, '.arh-complete').is_file())
        self.assertEqual(len(log.read_text().splitlines()), 2)       # host and task environment, each built once

    @needs_site
    def test_nextflow_reports_setting(self):
        site = self.root / '.arh/config/site.md'
        script = self.it / 'scripts/it1_01_ok.sh'; script.write_text('exit 0\n')
        for mode in ('gzip', 'none'):
            text = re.sub(r'(?m)^nextflow_reports\s*=.*\n', '', site.read_text())
            site.write_text(text + f'\n```arh-config\nnextflow_reports = {mode}\n```\n')
            self.call('submit', str(script), '-n', 'reports_' + mode, timeout=300)
            attempt = next((self.it / 'logs/nextflow' / ('reports_' + mode)).glob('attempt-*'))
            self.assertEqual(json.loads((attempt / 'run.json').read_text())['reports'], mode)
            self.assertFalse(list(attempt.glob('*.html')))
            self.assertEqual(sorted(p.name for p in attempt.glob('*.html.gz')),
                             ['report.html.gz', 'timeline.html.gz'] if mode == 'gzip' else [])

    @needs_site
    def test_lint_checks_without_running(self):
        good = self.it / 'scripts/it1_01_good.nf'
        good.write_text('workflow {\n    channel.of(1).view()\n}\n')
        self.call('submit', str(good), '--lint', timeout=300)
        bad = self.it / 'scripts/it1_02_bad.nf'
        bad.write_text('import groovy.json.JsonSlurper\n\nworkflow {\n    println(new JsonSlurper())\n}\n')
        self.call('submit', str(bad), '--lint', good=False, timeout=300)
        self.assertFalse((self.it / 'logs/nextflow').exists())

    @needs_site
    @needs_network
    def test_env_create_locks_and_is_immutable(self):
        prefix = self.call('env', 'create', 'tiny', 'zlib', timeout=1200).stdout.strip()
        self.assertTrue(Path(prefix, '.arh-complete').is_file())
        lock = self.root / '.arh/tiny-explicit.lock'
        self.assertEqual(lock.read_text().splitlines()[0], '@EXPLICIT')
        self.assertIn('zlib', lock.read_text())
        self.assertEqual(self.call('env', 'path', 'tiny').stdout.strip(), prefix)
        self.assertIn('is ready', self.call('env', 'create', 'tiny', 'zlib').stderr)
        self.assertIn('different package set', self.call('env', 'create', 'tiny', 'zlib', 'xz', good=False).stderr)
        shutil.rmtree(prefix)
        self.call('env', 'create', 'tiny', timeout=1200)             # rebuilt from its lock, package list verified
        self.assertTrue(Path(prefix, '.arh-complete').is_file())


    # --- durable knowledge (field feedback #39) -------------------------------------------------

    def test_knowledge_files_are_scaffolded_and_bound_to_the_claim(self):
        # Operator directives once reached a study only through one harness's private memory, which
        # no other harness, account or reviewer could read (2026-10-05).
        directives = self.root / 'DIRECTIVES.md'
        self.assertIn('## Operator directives', directives.read_text())
        claim = json.loads((self.it / 'CLAIM.json').read_text())
        self.assertEqual(claim['knowledge_sha256']['DIRECTIVES.md'], hashlib.sha256(directives.read_bytes()).hexdigest())
        self.assertIn('GOTCHAS.md', claim['knowledge_sha256'])
        self.assertEqual(json.loads(self.call('context', '-n', '1').stdout)['knowledge']['DIRECTIVES.md']['since_claim'],
                         'unchanged')
        directives.write_text(directives.read_text() + '\n### 2026-10-05 — score in HCI regions only\n')
        self.assertEqual(json.loads(self.call('context', '-n', '1').stdout)['knowledge']['DIRECTIVES.md']['since_claim'],
                         'changed')

    def test_review_is_pointed_at_and_bound_to_the_directives(self):
        directives = self.root / 'DIRECTIVES.md'
        directives.write_text(directives.read_text() + '\n### 2026-10-05 — HG002 confirms, never selects\n')
        self.assertIn('DIRECTIVES.md', self.call('ask', '-n', '1', '--dry-run').stdout)
        self.ask()
        record = json.loads(next(self.it.glob('CROSSCHECK_*.md.json')).read_text())
        self.assertEqual(record['knowledge_sha256']['DIRECTIVES.md'],
                         hashlib.sha256(directives.read_bytes()).hexdigest())

    def test_delegated_executor_receives_the_directives(self):
        self.configure(extra_config='executor = reviewer\n')
        directives = self.root / 'DIRECTIVES.md'
        directives.write_text(directives.read_text() + '\n### 2026-10-05 — the ONT truth trains and scores\n')
        dry = self.call('delegate', '--role', 'executor', '-n', '1', '--dry-run').stdout
        self.assertIn('the ONT truth trains and scores', dry)
        self.assertIn('GOTCHAS.md', dry)

    def test_site_gotchas_are_shared_checked_and_hashed(self):
        shared = Path(self.temp.name) / 'site/GOTCHAS.md'
        shared.parent.mkdir(); shared.write_text('# Site gotchas\n\n## truvari 5.4 with pysam 0.24\n**Assertion:** pin pysam\n')
        self.set_config('site.md', site_gotchas=shared)
        self.assertIn(str(shared), self.call('ask', '-n', '1', '--dry-run').stdout)
        self.assertIn('site_gotchas: ' + str(shared), self.call('doctor', good=None).stdout)
        n = self.call('claim', '-t', 'second').stdout.strip()
        claim = json.loads((self.root / f'iterations/iteration{n}/CLAIM.json').read_text())
        self.assertIn('site_gotchas', claim['knowledge_sha256'])
        shared.unlink()
        self.assertIn('not a readable file', self.call('doctor', good=False).stdout)

    def test_doctor_names_missing_knowledge_and_bare_gotchas(self):
        gotchas = self.root / 'GOTCHAS.md'
        gotchas.write_text(gotchas.read_text() + '\n## a mode with no check\n**Symptom:** looks fine\n')
        (self.root / 'DIRECTIVES.md').unlink()
        err = self.call('doctor', good=None).stderr
        self.assertIn('DIRECTIVES.md is missing', err)
        self.assertIn('without an assertion (a failure mode nobody can detect recurs): a mode with no check', err)
        self.call('migrate', str(self.root), '--apply')
        self.assertTrue((self.root / 'DIRECTIVES.md').is_file())
        self.assertIn('a mode with no check', gotchas.read_text())          # an existing file is never replaced


    # --- freezes and sealed inputs (field feedback #21, #29) --------------------------------------

    def seal(self):
        """A held-out directory inside a declared immutable input, declared sealed."""
        data = Path(self.temp.name) / 'data'
        held = data / 'heldout'
        held.mkdir(parents=True)
        (held / 'truth.txt').write_text('held-out truth\n')
        (data / 'open.txt').write_text('open\n')
        self.set_config('project.md', immutable_inputs=data, sealed_inputs=held)
        return data, held

    def test_freeze_is_write_once_and_binds_every_named_file(self):
        # A hand-written guard hashed the model but not the thresholds that carried the rule (2026-09-12).
        model = self.it / 'results/model'; model.mkdir(parents=True)
        (model / 'weights.bin').write_bytes(b'w')
        thresholds = self.it / 'scripts/thresholds.json'; thresholds.write_text('{"t": 0.5}\n')
        self.call('freeze', '-n', '1', str(model), str(thresholds))
        frozen = json.loads((self.it / 'FREEZE.json').read_text())
        self.assertEqual(set(frozen['files']), {'iterations/iteration1/results/model/weights.bin',
                                                'iterations/iteration1/scripts/thresholds.json'})
        self.assertIn('written once', self.call('freeze', '-n', '1', str(thresholds), good=False).stderr)
        self.call('freeze', 'check', '-n', '1')
        self.assertEqual(json.loads(self.call('status', '--json').stdout)['iterations'][0]['freeze'], 'valid')
        thresholds.write_text('{"t": 0.4}\n')
        self.assertIn('thresholds.json', self.call('freeze', 'check', '-n', '1', good=False).stdout)
        self.ask()
        self.assertIn('freeze: frozen file(s) changed', self.gate(good=False).stdout)
        script = self.it / 'scripts/it1_01_confirm.sh'; script.write_text('exit 0\n')
        self.assertIn('changed since the freeze', self.call('submit', str(script), '-n', 'confirm', good=False).stderr)

    def test_freeze_refuses_without_a_plan_outside_the_project_and_on_sealed_data(self):
        _, held = self.seal()
        n = self.call('claim', '-t', 'unplanned').stdout.strip()
        thing = self.root / f'iterations/iteration{n}/scripts/x.txt'; thing.write_text('x\n')
        self.assertIn('pre-declaration first', self.call('freeze', '-n', n, str(thing), good=False).stderr)
        outside = Path(self.temp.name) / 'outside.txt'; outside.write_text('x\n')
        self.assertIn('outside the project', self.call('freeze', '-n', '1', str(outside), good=False).stderr)
        self.assertIn('sealed input', self.call('freeze', '-n', '1', str(held / 'truth.txt'), good=False).stderr)
        self.assertFalse((self.it / 'FREEZE.json').exists())

    def test_workflow_naming_a_sealed_input_is_refused_before_a_freeze(self):
        _, held = self.seal()
        script = self.it / 'scripts/it1_01_peek.sh'; script.write_text(f'cat {held}/truth.txt\n')
        failed = self.call('submit', str(script), '-n', 'peek', good=False)
        self.assertIn('sealed input', failed.stderr)
        self.assertFalse((self.it / 'logs/nextflow/peek').exists())        # refused before any attempt
        self.call('guard', str(held / 'x'), good=False)

    @needs_site
    def test_sealed_input_is_hidden_until_the_freeze_then_read_and_logged(self):
        data, held = self.seal()
        out = self.it / 'results/seen.txt'
        script = self.it / 'scripts/it1_01_read.sh'
        script.write_text(f'set -eu\ncat "{data}/open.txt" > /dev/null\nls -A "{data}/held""out" > "{out}"\n'
                          f'cat "{data}/held""out/truth.txt" >> "{out}"\n')
        self.call('submit', str(script), '-n', 'early', good=False)
        self.assertEqual(out.read_text(), '')                             # an empty mount, not the data
        early = json.loads(next((self.it / 'logs/nextflow/early').glob('attempt-*/run.json')).read_text())
        self.assertEqual(early['sealed_inputs'], {'read': [], 'masked': [str(held)]})
        self.assertIn('singularity.autoMounts = false',
                      next((self.it / 'logs/nextflow/early').glob('attempt-*/execution.config')).read_text())
        self.call('freeze', '-n', '1', str(script))
        self.call('submit', str(script), '-n', 'confirm')
        self.assertIn('held-out truth', out.read_text())
        record = json.loads(next((self.it / 'logs/nextflow/confirm').glob('attempt-*/run.json')).read_text())
        self.assertEqual(record['sealed_inputs']['read'], [str(held)])
        self.assertEqual(record['freeze_sha256'], hashlib.sha256((self.it / 'FREEZE.json').read_bytes()).hexdigest())
        log = (self.root / '.arh/unseals.tsv').read_text().splitlines()
        self.assertEqual((len(log), log[1].split('\t')[1:3]), (2, ['1', 'confirm']))
        self.assertIn('read by iteration(s) 1', self.call('freeze', 'list').stdout)

    @needs_site
    def test_arh_run_never_reads_a_sealed_input(self):
        data, held = self.seal()
        self.assertEqual(self.call('run', 'runtime', '--', 'ls', '-A', str(held)).stdout, '')
        self.assertIn('open', self.call('run', 'runtime', '--', 'cat', str(data / 'open.txt')).stdout)

    def test_doctor_and_harnesses_know_about_sealed_inputs(self):
        data, held = self.seal()
        self.assertIn('sealed: ' + str(held), self.call('doctor', good=None).stdout)
        subprocess.run([str(ROOT / 'harness/install.sh'), str(self.root), 'claude', 'opencode'],
                       env=self.env, check=True, capture_output=True)
        deny = json.loads((self.root / '.claude/settings.json').read_text())['permissions']['deny']
        self.assertIn(f'Read(/{held}/**)', deny)
        self.assertEqual(json.loads((self.root / 'opencode.json').read_text())['permission']['external_directory'][str(held)],
                         'deny')
        # An immutable input inside a sealed one would be hidden by the seal's mount.
        self.set_config('project.md', sealed_inputs=data, immutable_inputs=held)
        self.assertIn('lies inside sealed input', self.call('doctor', good=False).stdout)


    # --- nothing runs without a receipt (field feedback #14, #18, #33, #34, #35, #41) -------------

    def test_slurm_gpu_settings_are_per_task(self):
        # Every GPU arm of a field study ran by hand-written sbatch: tasks had no way to ask for one,
        # and 16 folds landed on cards too small for them (2026-09-22).
        sys.path.insert(0, str(ROOT / 'lib'))
        import nextflow
        site = {'slurm_partition': 'all', 'slurm_account': 'lab', 'gpu_partition': 'gpu', 'gpu_type': 'a100',
                'gpu_constraint': 'gpu80g'}
        plain = nextflow.slurm_settings(site, False)
        self.assertIn('process.queue = "all"', plain)
        self.assertIn('process.clusterOptions = "--account=lab"', plain)
        gpu = '\n'.join(nextflow.slurm_settings(site, True))
        self.assertIn(nextflow.WANTS_GPU + ' ? "gpu" : "all"', gpu)
        self.assertIn("' --gres=gpu:a100:' + (task.accelerator ? (task.accelerator.request ?: 1) : 1)", gpu)
        self.assertIn('--constraint=gpu80g', gpu)

    def nf(self, name, body):
        path = self.it / 'scripts' / name
        path.write_text(body)
        return path

    @needs_site
    def test_gpu_process_runs_with_nv(self):
        wf = self.nf('it1_01_gpu.nf', 'process G {\n    label \'gpu\'\n    output:\n    stdout\n'
                     '    script:\n    """\n    (nvidia-smi -L 2>&1 || echo no-gpu) | head -1\n    """\n}\n'
                     'workflow {\n    G() | view\n}\n')
        self.call('submit', str(wf), '-n', 'gpu', timeout=900)
        attempt = next((self.it / 'logs/nextflow/gpu').glob('attempt-*'))
        self.assertIn("' --nv'", (attempt / 'execution.config').read_text())
        self.assertIn('gpu', json.loads((attempt / 'run.json').read_text()))
        if os.environ.get('ARH_TEST_GPU'):          # a host with a GPU: the task must see it
            self.assertIn('GPU 0', (attempt / 'console.log').read_text())

    @needs_site
    def test_image_label_runs_in_its_declared_image_with_its_own_path(self):
        site = Path(os.environ['ARH_TEST_SITE']).read_text()
        image = re.search(r'(?m)^runtime_image\s*=\s*(\S+)', site).group(1)
        digest = re.search(r'(?m)^runtime_sha256\s*=\s*(\S+)', site).group(1)
        self.set_config('site.md', image_alt=image, image_alt_sha256=digest, image_alt_path='/alt/bin:/usr/bin:/bin')
        wf = self.nf('it1_01_alt.nf', 'process A {\n    label \'image_alt\'\n    output:\n    stdout\n'
                     '    script:\n    """\n    echo "PATH=\\$PATH"\n    """\n}\nworkflow {\n    A() | view\n}\n')
        self.call('submit', str(wf), '-n', 'alt', timeout=900)
        attempt = next((self.it / 'logs/nextflow/alt').glob('attempt-*'))
        self.assertIn('PATH=/alt/bin:/usr/bin:/bin', (attempt / 'console.log').read_text())    # its tools first
        record = json.loads((attempt / 'run.json').read_text())
        self.assertEqual(record['images']['image_alt']['sha256'], digest)
        trace = (attempt / 'trace.tsv').read_text().splitlines()
        self.assertEqual(trace[0].split('\t')[-1], 'container')
        self.assertEqual(trace[1].split('\t')[-1], image)
        self.set_config('site.md', image_alt_sha256='0' * 64)
        self.assertIn('digest does not match', self.call('submit', str(wf), '-n', 'alt2', good=False).stderr)

    def plan_with_imports(self, *paths):
        n = self.call('claim', '-t', 'uses a helper').stdout.strip()
        self.call('new', '-n', n)
        it = self.root / f'iterations/iteration{n}'
        headings = ['Question', 'Estimand', 'Instrument', 'Acceptance criteria', 'Negative controls', 'Detection limit', 'Prediction']
        (it / 'README.md').write_text('\n'.join(f'## {i}. {h}\nFixture.\n' for i, h in enumerate(headings, 1))
                                      + '\n```arh-config\nimports = ' + ' '.join(paths) + '\n```\n')
        return n, it

    def test_declared_imports_are_frozen_with_the_plan_and_checked_at_submit(self):
        # A pre-declaration promised the shared library was unchanged; nothing could check it (2026-09-29).
        lib = self.it / 'scripts/it1_00_lib.py'; lib.write_text('THRESHOLD = 0.5\n')
        n, it = self.plan_with_imports('iterations/iteration1/scripts/it1_00_lib.py')
        self.assertIn('imports: 1 file(s) hashed with the plan', self.call('gate', 'predeclare', '-n', n).stdout)
        self.assertIn(f"import {hashlib.sha256(lib.read_bytes()).hexdigest()} iterations/iteration1/scripts/it1_00_lib.py",
                      (it / 'PREDECLARATION.sha256').read_text())
        lib.write_text('THRESHOLD = 0.4\n')
        script = it / 'scripts' / f'it{n}_01_run.sh'; script.write_text('exit 0\n')
        self.assertIn('changed since the pre-declaration was frozen',
                      self.call('submit', str(script), '-n', 'run', good=False).stderr)
        m, _ = self.plan_with_imports('iterations/iteration1/scripts/missing.py')
        self.assertIn('does not exist', self.call('gate', 'predeclare', '-n', m, good=False).stdout)

    @needs_site
    def test_undeclared_reference_to_another_iteration_is_hashed(self):
        (self.it / 'scripts/it1_00_helper.py').write_text('print(1)\n')
        n, it = self.plan_with_imports()
        self.call('gate', 'predeclare', '-n', n)
        script = it / 'scripts' / f'it{n}_01_run.sh'
        script.write_text(f'python3 {self.root}/iterations/iteration1/scripts/it1_00_helper.py\n')
        result = self.call('submit', str(script), '-n', 'run')
        self.assertIn('does not declare as imports', result.stderr)
        record = json.loads(next((it / 'logs/nextflow/run').glob('attempt-*/run.json')).read_text())
        self.assertIn('iterations/iteration1/scripts/it1_00_helper.py', record['referenced_sha256'])

    def verification(self, name='recount'):
        self.call('verify', 'new', name, '-m', 'recalculation', '--of', '1')
        d = self.root / 'verification' / name
        (d / 'PREDECLARATION.md').write_text(
            '# Verification\n\n## What is being verified\nIteration 1.\n\n## Mode\nRecalculation.\n\n'
            '## Analytic variant\nSeed 1.\n\n## Success criterion\nThe same records come back, by name.\n\n'
            '## What a failure would mean\nThe count was wrong.\n')
        self.call('verify', 'gate', name)
        return d

    @needs_site
    def test_verification_runs_through_submit_and_concludes_on_its_receipt(self):
        # A verification recount ran on a login node, outside the task image, with no receipt (2026-10-05).
        d = self.verification()
        (d / 'scripts').mkdir(exist_ok=True)
        check = d / 'scripts/check.sh'; check.write_text(f'echo 3 > {d}/results/count.txt\n')
        self.call('verify', 'run', 'recount', str(check), '-n', 'check')
        record = json.loads(next((d / 'logs/nextflow/check').glob('attempt-*/run.json')).read_text())
        self.assertEqual(record['owner'], {'kind': 'verification', 'path': 'verification/recount'})
        self.assertIn('wrote', self.call('verify', 'conclude', 'recount', good=False).stderr)   # scaffolds RESULT.md
        (d / 'RESULT.md').write_text('# Result\n\nOUTCOME: CONFIRMED\n\n## What was run\ncheck\n')
        self.assertIn('CONFIRMED (verifies iteration 1); 1 run receipt', self.call('verify', 'conclude', 'recount').stdout)
        self.assertIn('concluded: CONFIRMED', self.call('verify', 'list').stdout)
        self.assertIn('verification recount: CONFIRMED', self.call('gate', 'results', '-n', '1', good=None).stdout)
        self.call('ledger', 'render')
        self.assertIn('| recount | 1 | frozen | CONFIRMED |', (self.root / 'PROGRESS.md').read_text())
        self.assertIn('already concluded', self.call('verify', 'conclude', 'recount', good=False).stderr)

    def test_verification_needs_a_receipt_or_a_reason(self):
        d = self.verification()
        self.assertIn('already frozen', self.call('verify', 'gate', 'recount', good=False).stderr)
        (d / 'RESULT.md').write_text('OUTCOME: REFUTED\n')
        self.assertIn('no successful run receipt', self.call('verify', 'conclude', 'recount', good=False).stderr)
        self.call('verify', 'conclude', 'recount', '--without-run', 'read two counts from the report')
        self.assertEqual(json.loads((d / 'CONCLUDED.json').read_text())['without_run'], 'read two counts from the report')

    def test_out_of_band_work_is_noted_and_named_at_the_gate(self):
        # A GPU job chain ran unrecorded; a second session found it only in the first one's transcript.
        self.call('note', '-n', '1', '--job', '967736', 'LAYA folds by sbatch array; logs in logs/laya/')
        self.assertIn('job 967736', self.call('note', 'list').stdout)
        self.assertEqual(json.loads(self.call('status', '--json').stdout)['iterations'][0]['notes'], 1)
        self.assertEqual(json.loads(self.call('context', '-n', '1').stdout)['notes'][0]['job'], '967736')
        (self.it / 'results/folds.tsv').write_text('fold\tf1\n')
        self.ask()
        out = self.gate().stdout
        self.assertIn('1 note(s) of work outside arh submit', out)
        self.assertIn('no arh submit run receipt does', out)

    def test_requests_carrying_a_credential_are_not_sent(self):
        key = 'sk-ant-api03-' + 'A1b2C3d4E5f6G7h8I9j0' * 2
        self.report.write_text(self.report.read_text() + f'\nexport ANTHROPIC_API_KEY={key}\n')
        failed = self.ask(good=False)
        self.assertIn('Anthropic API key', failed.stderr); self.assertNotIn(key, failed.stderr)
        self.assertFalse(list(self.it.glob('CROSSCHECK_*')))
        self.assertIn('would refuse', self.call('ask', '-n', '1', '--dry-run').stderr)
        self.configure(extra_config='executor = reviewer\n')
        task = self.root / 'task.md'; task.write_text(f'password = "{key}"\n')
        self.call('delegate', '--role', 'executor', '-n', '1', '--prompt', str(task), good=False)
        self.assertFalse((self.it / 'metadata/delegations').exists())
        self.configure(extra_config='secret_scan = off\n')
        self.ask()


    # --- unattended runs, leases and pre-flight checks (field feedback #5, #11, #35-#38) ----------

    @needs_site
    def test_detached_submission_outlives_its_caller_and_can_be_followed(self):
        # A harness's two-hour cap on background tasks stopped a long run (2026-10-04).
        script = self.it / 'scripts/it1_01_slow.sh'; script.write_text('sleep 20\n')
        started = time.time()
        out = self.call('submit', str(script), '-n', 'slow', '--detach', timeout=300)
        self.assertLess(time.time() - started, 120)
        self.assertIn('detached as pid', out.stderr)
        self.assertIn('submission slow', self.call('status', '--running').stdout)
        self.call('wait', '-n', '1', '--timeout', '600', timeout=700)
        record = json.loads(next((self.it / 'logs/nextflow/slow').glob('attempt-*/run.json')).read_text())
        self.assertEqual(record['exit_code'], 0)
        self.assertIn('nothing running', self.call('status', '--running').stdout)

    def test_lease_names_the_holder_warns_another_session_and_records_a_takeover(self):
        # A second account's session learned what the first had left running only from its transcript.
        self.call('note', '-n', '1', 'first session')        # creates the lease if setUp's claim predates it
        holder = json.loads((self.it / 'metadata/lease.json').read_text())['holder']
        env, self.env = self.env, dict(self.env, ARH_AGENT='other-agent', ARH_SESSION='s2')
        try:
            warned = self.call('note', '-n', '1', 'second session')
            self.assertIn('is held by', warned.stderr)
            self.call('lease', 'take', '-n', '1', good=False)                 # a takeover needs a reason
            self.call('lease', 'take', '-n', '1', '--reason', 'the first session hit its usage limit')
        finally:
            self.env = env
        lease = json.loads((self.it / 'metadata/lease.json').read_text())
        self.assertEqual((lease['holder']['agent'], lease['holder']['session']), ('other-agent', 's2'))
        history = json.loads((self.it / 'metadata/lease-history.jsonl').read_text().splitlines()[-1])
        self.assertEqual(history['previous'], holder)
        self.assertIn('held by other-agent', self.call('status').stdout)

    def test_inputs_check_reads_end_markers_and_caches_passes(self):
        # A truncated CRAM (no end-of-file container) made a caller drop chr11-22 silently (2026-10-04).
        sys.path.insert(0, str(ROOT / 'lib'))
        import inputs
        data = Path(self.temp.name) / 'inputs'; data.mkdir()
        bgzf_head = bytes.fromhex('1f8b08040000000000ff060042430200')
        (data / 'whole.vcf.gz').write_bytes(bgzf_head + b'x' * 64 + inputs.BGZF_EOF)
        (data / 'cut.vcf.gz').write_bytes(bgzf_head + b'x' * 64)
        (data / 'whole.cram').write_bytes(b'CRAM\x03\x00' + b'x' * 64 + inputs.CRAM3_EOF)
        (data / 'cut.cram').write_bytes(b'CRAM\x03\x00' + b'\x00' * 64)
        import gzip as gz
        (data / 'plain.txt.gz').write_bytes(gz.compress(b'abc' * 1000)[:-12])
        self.set_config('project.md', immutable_inputs=data)
        out = self.call('inputs', 'check', good=False).stdout
        self.assertIn('cut.vcf.gz: BGZF end-of-file block missing', out)
        self.assertIn('cut.cram: CRAM end-of-file container missing', out)
        self.assertIn('5 checked', out)
        listed = self.call('inputs', 'list').stdout
        self.assertIn('ok   ', listed); self.assertIn('whole.cram: CRAM end-of-file container present', listed)
        self.assertIn('plain.txt.gz: decompression failed',
                      self.call('inputs', 'check', '--deep', str(data / 'plain.txt.gz'), good=False).stdout)
        (data / 'cut.vcf.gz').unlink(); (data / 'cut.cram').unlink(); (data / 'plain.txt.gz').unlink()
        self.assertIn('0 checked, 2 unchanged', self.call('inputs', 'check').stdout)
        self.assertIn('failed their last integrity check', self.call('doctor', good=None).stderr)

    @needs_site
    def test_submit_cites_input_checks_in_its_receipt(self):
        data = Path(self.temp.name) / 'inputs'; data.mkdir()
        (data / 'cut.bam').write_bytes(b'\x1f\x8b\x08\x04' + b'x' * 40)
        self.set_config('project.md', immutable_inputs=data)
        self.call('inputs', 'check', good=False)
        script = self.it / 'scripts/it1_01_ok.sh'; script.write_text('exit 0\n')
        result = self.call('submit', str(script), '-n', 'ok')
        self.assertIn('failed their last integrity check', result.stderr)
        record = json.loads(next((self.it / 'logs/nextflow/ok').glob('attempt-*/run.json')).read_text())
        self.assertEqual(record['input_checks']['failed'], [os.path.realpath(data / 'cut.bam')])

    @needs_site
    def test_doctor_smoke_runs_one_task_through_the_boundary(self):
        # doctor said "No problems found" while no task could run (2026-09-10).
        data, held = self.seal()
        out = self.call('doctor', '--smoke', good=None, timeout=900).stdout
        self.assertIn('immutable input visible and read-only: ' + os.path.realpath(data), out)
        self.assertIn('sealed input hidden: ' + str(held), out)
        self.assertIn('the task ran through the scheduler and completed', out)

    @needs_site
    def test_predeclared_commands_run_before_the_freeze(self):
        # A flag copied from a patched build failed only on the first real task (2026-10-04).
        n = self.call('claim', '-t', 'smoke').stdout.strip()
        it = self.root / f'iterations/iteration{n}'
        headings = ['Question', 'Estimand', 'Instrument', 'Acceptance criteria', 'Negative controls', 'Detection limit', 'Prediction']
        body = '\n'.join(f'## {i}. {h}\nFixture.\n' for i, h in enumerate(headings, 1))
        (it / 'README.md').write_text(body + "\n```arh-smoke\n# a comment\nruntime: python3 --version\nruntime: false\n```\n")
        self.assertIn('smoke [runtime]: false failed', self.call('gate', 'predeclare', '-n', n, good=False).stdout)
        self.assertFalse((it / 'PREDECLARATION.sha256').exists())
        (it / 'README.md').write_text(body + "\n```arh-smoke\nruntime: python3 --version\n```\n")
        self.call('gate', 'predeclare', '-n', n)
        self.assertIn('Python 3', (it / 'metadata/predeclare-smoke.txt').read_text())
        frozen = (it / 'PREDECLARATION.sha256').read_text()
        self.assertIn('smoke ' + hashlib.sha256((it / 'metadata/predeclare-smoke.txt').read_bytes()).hexdigest(), frozen)


    # --- closing the review loop (field feedback #12, #16) ----------------------------------------

    def test_each_numbered_finding_must_be_answered(self):
        # Every review of a field study was QUALIFIED for specific findings, and the results gate
        # passed with no response file at all (2026-09-12).
        self.configure("print('VERDICT: QUALIFIED\\n\\nF1: the acceptance criterion was asserted, not checked.\\n"
                       "- **F2:** the control is over-read.')")
        self.assertIn('numbered: "F1: ..."', self.call('ask', '-n', '1', '--dry-run').stdout)
        self.ask()
        failed = self.gate(good=False).stdout
        self.assertIn('2 numbered finding(s)', failed)
        self.assertIn('F2 UNANSWERED: the control is over-read.', failed)
        skeleton = self.call('gate', 'results', '-n', '1', '--skeleton').stdout
        self.assertIn('- F1: <accepted', skeleton); self.assertIn('- F2: <accepted', skeleton)
        response = self.it / 'REVIEW_RESPONSE.md'
        response.write_text('F1: accepted; the criterion is now computed in it1_02.\n')
        self.assertIn('answers 1 of 2', self.gate(good=False).stdout)
        response.write_text(response.read_text() + '\nF2: rejected, because the control is reported as a bound.\n')
        passed = self.gate().stdout
        self.assertIn('answers 2 of 2', passed)
        self.assertIn('F2 answered (rejected)', passed)
        self.bind_policy(review_response='warn')       # the policy the iteration was claimed under
        response.unlink()
        self.assertIn('WARN no REVIEW_RESPONSE.md, and the review(s) list 2', self.gate().stdout)

    def test_report_numbers_must_come_from_results(self):
        # A reviewer caught mis-transcribed numbers in a report (2026-09-12).
        (self.it / 'results/metrics.json').write_text('{"f1": 0.76912, "precision": 0.7534, "ci": [0.052, 0.072]}\n')
        self.report.write_text(self.report.read_text() + '\nF1 0.769, precision 75.3%, gain CI [+0.052, +0.072]; '
                               'recall 0.786 and Sniffles 2.8.1.\n\n## Cross-check\nSee 0.999 in REVIEW_RESPONSE.md.\n')
        self.ask()
        out = self.gate().stdout
        self.assertIn('1 number(s) in the report match no file under results/', out)
        self.assertIn('0.786', out)
        for ok in ('0.769', '75.3%', '0.052', '2.8.1', '0.999'):
            self.assertNotIn(ok + '   ', out)
        self.set_config('project.md', report_numbers='require')
        self.gate(good=False)


    # --- v0.4: the record out of a task's reach, pinned scripts, a stop switch ------------------------

    @needs_site
    def test_a_task_writes_only_its_own_results_when_the_project_is_read_only(self):
        # External review of v0.3.0: tasks could write anywhere in the project, the record included.
        script = self.it / 'scripts/it1_01_write.sh'
        script.write_text(f'set -u\necho ok > {self.it}/results/ok.txt\n'
                          f'echo forged >> {self.it}/README.md || echo refused > {self.it}/results/refused.txt\n')
        self.call('submit', str(script), '-n', 'ro')
        self.assertTrue((self.it / 'results/ok.txt').is_file())
        self.assertTrue((self.it / 'results/refused.txt').is_file())
        self.assertNotIn('forged', (self.it / 'README.md').read_text())
        record = json.loads(next((self.it / 'logs/nextflow/ro').glob('attempt-*/run.json')).read_text())
        self.assertEqual(record['task_project_access'], 'ro')
        self.assertEqual((record['user'], record['host']), (os.environ.get('USER', 'unknown'), os.uname().nodename))
        self.set_config('project.md', task_project_access='rw')
        self.call('submit', str(script), '-n', 'rw')
        self.assertIn('forged', (self.it / 'README.md').read_text())

    def pinned_iteration(self):
        self.call('claim', '-t', 'pinned')
        self.call('new', '-n', '2')
        it = self.root / 'iterations/iteration2'
        headings = ['Question', 'Estimand', 'Instrument', 'Acceptance criteria', 'Negative controls', 'Detection limit', 'Prediction']
        (it / 'README.md').write_text('\n'.join(f'## {i}. {h}\nThe setup check in scripts/ is part of the plan.\n'
                                                for i, h in enumerate(headings, 1)))
        setup = it / 'scripts/it2_04_setup.sh'
        setup.write_text('test "$(cat /dev/null)" = ""\n')
        self.assertIn('1 script(s) already in scripts/, pinned', self.call('gate', 'predeclare', '-n', '2').stdout)
        return it, setup

    def test_scripts_written_with_the_plan_are_pinned_with_it(self):
        # A gating script was changed after the freeze and nothing in the record showed it (field feedback #74).
        it, setup = self.pinned_iteration()
        self.assertRegex((it / 'PREDECLARATION.sha256').read_text(), r'(?m)^script [0-9a-f]{64} iterations/iteration2/scripts/it2_04_setup.sh$')
        setup.write_text('true  # accept the excluded person\n')
        report = it / 'results/report/iteration2_report.md'; report.parent.mkdir(parents=True)
        report.write_text('Candidate only.\n')
        self.assertIn('pinned with the frozen plan changed since the freeze', self.call('gate', 'results', '-n', '2', good=None).stdout)

    @needs_site
    def test_a_run_after_a_pinned_script_changed_is_reported_or_refused(self):
        it, setup = self.pinned_iteration()
        setup.write_text('true\n')
        out = self.call('submit', str(setup), '-n', 'setup')
        self.assertIn('pinned with the frozen plan changed', out.stderr)
        record = json.loads(next((it / 'logs/nextflow/setup').glob('attempt-*/run.json')).read_text())
        self.assertEqual(record['scripts_changed_since_freeze'], ['iterations/iteration2/scripts/it2_04_setup.sh'])
        self.set_config('project.md', frozen_scripts='refuse')
        self.assertIn('A changed plan is a new iteration', self.call('submit', str(setup), '-n', 'setup2', good=False).stderr)

    @needs_site
    def test_stop_ends_a_running_submission(self):
        script = self.it / 'scripts/it1_01_slow.sh'; script.write_text('sleep 300\n')
        self.call('submit', str(script), '-n', 'slow', '--detach', timeout=300)
        lock = self.it / 'metadata/nextflow/slow/.launch-lock'
        deadline = time.time() + 300
        while time.time() < deadline and not list((self.it / 'metadata/nextflow/slow/work').glob('*/*/.command.begin')):
            time.sleep(1)
        self.assertIn('sent SIGTERM', self.call('stop', '-n', '1').stdout)
        self.call('wait', '-n', '1', '--timeout', '300', timeout=400)
        self.assertFalse(lock.exists())
        record = json.loads(next((self.it / 'logs/nextflow/slow').glob('attempt-*/run.json')).read_text())
        self.assertEqual(record['signal'], 'SIGTERM')
        self.assertIn('nothing to stop', self.call('stop', '--all').stdout)
        self.call('stop', good=False)

if __name__ == '__main__':
    unittest.main(verbosity=2)
