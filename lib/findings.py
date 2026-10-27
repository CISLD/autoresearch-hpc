"""Each finding of each eligible review, and whether REVIEW_RESPONSE.md answers it (stdlib only).

PROTOCOL 6.5 says findings MUST be evaluated on their merits and rejections recorded with reasons,
but nothing checked that they were: a field study's results gate passed with no response file at
all, and the reviews' value was precisely in their specific findings (field feedback #12, #16).
`arh ask` asks the reviewer to number findings F1, F2, ...; this reads them back and looks, in
REVIEW_RESPONSE.md, for each id beside a decision (accepted, rejected, fixed, deferred, ...).
With several reviews, a response section whose heading names a review's file answers that review;
otherwise the whole file is searched.

  findings.py check DIR MODE      MODE require|warn|off; prints a checklist; exit 1 if MODE is require
                                  and a numbered finding is unanswered
  findings.py skeleton DIR        a REVIEW_RESPONSE.md skeleton listing every numbered finding
  findings.py verdicts DIR MODE   MODE require-adjudication|require-rebuttal|allow; every eligible
                                  UNSOUND review needs a recorded rebuttal, and under
                                  require-adjudication the reviewer's withdrawal, before the
                                  iteration can conclude
  findings.py summary DIR         the verdicts of the eligible reviews, for the ledger
  findings.py pending DIR         UNSOUND reviews whose rebuttal no reviewer has judged yet:
                                  review, rebuttal sha256, review harness, adjudications so far
  findings.py rebuttal DIR REVIEW the part of REVIEW_RESPONSE.md that answers REVIEW

A review's verdict was once read by no gate: an iteration whose only review said UNSOUND concluded
like any other (external review of v0.3.0, 2026-10-13; three benchmark iterations did). An UNSOUND
verdict is now answered in the review's part of REVIEW_RESPONSE.md by a line
`Verdict: rebutted, because <reason>`; `Verdict: accepted` records that the producer agrees, and
the iteration then stays unconcluded and the correction goes into a new iteration. Every UNSOUND
review needs its answer, so asking again until a milder verdict arrives does not help.

A rebuttal alone was still the producer judging its own case: any reason of three words passed.
`arh ask --rebuttal` puts it to a reviewer, who answers `ADJUDICATION: WITHDRAWN` or `MAINTAINED`
in a REBUTTAL_ record bound to the review and to the rebuttal's text. A maintained UNSOUND blocks
the iteration in every mode but `allow`, whichever reviewer said it.
"""
import hashlib
import json
from pathlib import Path
import re
import sys

from harness import valid_adjudications, valid_records

FINDING = re.compile(r'^\s*(?:[-*+]\s+|\d+\.\s+)?(?:\*\*|__)?\[?(F\d{1,3})\]?(?:\*\*|__)?\s*[:.)\]–—-]\s*(?:\*\*|__)?\s*(.+)$')
DECISION_WORDS = ('accepted', 'rejected', 'fixed', 'addressed', 'deferred', 'disputed', 'declined', 'acknowledged',
                  'not applicable', "won't fix", 'verified', 'new iteration', 'partly accepted')
DECISION = re.compile(r"\b(accept(?:ed)?|reject(?:ed)?|fix(?:ed)?|addressed|deferred|disput(?:e|ed)|declined|"
                      r"acknowledged|not applicable|n/a|won't fix|verified|new iteration|partly accepted)\b", re.I)


def findings(review):
    """[(id, summary)] in order of first appearance, after the VERDICT line."""
    text = Path(review).read_text(errors='replace')
    body = text.split('VERDICT:', 1)[1] if 'VERDICT:' in text else text
    seen, out = set(), []
    for line in body.splitlines():
        match = FINDING.match(line)
        if match and match.group(1) not in seen:
            seen.add(match.group(1))
            out.append((match.group(1), match.group(2).strip()[:140]))
    return out


def scope(response, review):
    """The part of the response that answers REVIEW: its own section when sections name reviews."""
    sections = re.split(r'(?m)^(?=#{1,6} )', response)
    named = [s for s in sections if s.startswith('#') and 'CROSSCHECK_' in s.splitlines()[0]]
    if not named:
        return response
    stem = Path(review).name.removesuffix('.md')
    return '\n'.join(s for s in named if stem in s.splitlines()[0])


VERDICT_ANSWER = re.compile(r'^\s*(?:[-*+]\s+)?(?:\*\*|__)?(?:verdict|unsound)(?:\*\*|__)?\s*[:.)–—-]\s*'
                            r'(?:\*\*|__)?\s*(rebutted|disputed|accepted)\b(?:\*\*|__)?[\s,:;.–—-]*(.*)$', re.I | re.M)


def verdict_of(review):
    try:
        return json.loads(Path(str(review) + '.json').read_text()).get('verdict')
    except (OSError, ValueError):
        return None


def verdict_answer(text, review):
    """('rebutted'|'accepted', reason) from the response's part for REVIEW, or None."""
    if not text:
        return None
    found = VERDICT_ANSWER.search(scope(text, review))
    if not found:
        return None
    kind = 'accepted' if found.group(1).lower() == 'accepted' else 'rebutted'
    return kind, found.group(2).strip()


def response_text(directory):
    response = Path(directory) / 'REVIEW_RESPONSE.md'
    return response.read_text(errors='replace') if response.is_file() else None


def rebuttal_sha(text, review):
    """SHA-256 of the part of the response that answers REVIEW; an adjudication is bound to it."""
    return hashlib.sha256(scope(text or '', review).encode()).hexdigest()


def judged(directory, review, text):
    """Valid adjudications of REVIEW's current rebuttal: [(record name, WITHDRAWN|MAINTAINED)]."""
    name, current = Path(review).name, rebuttal_sha(text, review)
    return [(Path(record).name, data['adjudication']) for record, data in valid_adjudications(directory)
            if data.get('adjudicates') == name and data.get('rebuttal_sha256') == current]


def standing(directory, review, text):
    """How an UNSOUND REVIEW stands: (state, detail). States: unanswered, accepted, no-reason,
    unadjudicated, withdrawn, maintained."""
    answer = verdict_answer(text, review)
    if not answer:
        return 'unanswered', None
    if answer[0] == 'accepted':
        return 'accepted', None
    if len(answer[1].split()) < 3:
        return 'no-reason', None
    outcomes = judged(directory, review, text)
    maintained = [record for record, outcome in outcomes if outcome == 'MAINTAINED']
    if maintained:
        return 'maintained', maintained[0]
    if outcomes:
        return 'withdrawn', outcomes[-1][0]
    return 'unadjudicated', answer[1]


def verdicts(directory, mode):
    directory = Path(directory)
    text = response_text(directory)
    n = directory.name.removeprefix('iteration')
    fails = 0
    for review in valid_records(directory):
        if verdict_of(review) != 'UNSOUND':
            continue
        name = Path(review).name
        state, detail = standing(directory, review, text)
        if state == 'withdrawn':
            print(f'  OK   {name}: UNSOUND, rebutted, and the reviewer withdrew it ({detail})')
            continue
        if state == 'unadjudicated' and mode == 'require-rebuttal':
            print(f'  OK   {name}: UNSOUND, rebutted by the producer, not put to a reviewer '
                  f'(unsound_review = require-rebuttal): {detail[:120]}')
            continue
        problem = {
            'unanswered': ("UNSOUND, with no recorded answer: add 'Verdict: rebutted, because <reason>' "
                           "to its part of REVIEW_RESPONSE.md, or leave this iteration unconcluded and "
                           "correct it in a new one"),
            'accepted': ('UNSOUND, and the response accepts it: this iteration does not conclude; '
                         'record the correction in a new iteration'),
            'no-reason': 'UNSOUND, and the rebuttal gives no reason',
            'unadjudicated': (f'UNSOUND, rebutted, and no reviewer has judged the rebuttal: '
                              f'arh ask --rebuttal -n {n}'),
            'maintained': (f'UNSOUND, and the reviewer maintained it over the rebuttal ({detail}): '
                           'this iteration does not conclude; record the correction in a new iteration'),
        }[state]
        if mode == 'allow':
            print(f'  WARN {name}: {problem} (unsound_review = allow)')
        else:
            print(f'  FAIL {name}: {problem}')
            fails += 1
    return 1 if fails else 0


LABELS = {'unanswered': 'unanswered', 'accepted': 'accepted', 'no-reason': 'rebutted without reason',
          'unadjudicated': 'rebutted, unadjudicated', 'withdrawn': 'rebutted, withdrawn',
          'maintained': 'rebutted, maintained'}


def summary(directory):
    """'QUALIFIED', 'UNSOUND (rebutted, withdrawn), QUALIFIED', ... for the eligible reviews."""
    directory = Path(directory)
    text = response_text(directory)
    out = []
    for review in valid_records(directory):
        verdict = verdict_of(review) or '?'
        if verdict == 'UNSOUND':
            verdict += f' ({LABELS[standing(directory, review, text)[0]]})'
        out.append(verdict)
    return ', '.join(out)


def review_harness(review):
    """The harness that wrote REVIEW, from its file name CROSSCHECK_<role>_<harness>_<time>."""
    match = re.match(r'CROSSCHECK_[^_]+_(.+)_\d{8}T\d{6}Z', Path(review).name)
    return match.group(1) if match else ''


def pending(directory):
    """Rebutted UNSOUND reviews with no adjudication of their current rebuttal, one line each."""
    directory = Path(directory)
    text = response_text(directory)
    for review in valid_records(directory):
        if verdict_of(review) != 'UNSOUND' or standing(directory, review, text)[0] != 'unadjudicated':
            continue
        # Provider refusals are not adjudications and do not count against the limit.
        tried = 0
        for record in directory.glob('REBUTTAL_*.md.json'):
            try:
                data = json.loads(record.read_text())
            except (OSError, ValueError):
                continue
            if data.get('adjudicates') == Path(review).name and not data.get('provider_error'):
                tried += 1
        print('\t'.join((review, rebuttal_sha(text, review), review_harness(review), str(tried))))


def decision(text, fid):
    for paragraph in re.split(r'\n\s*\n', text):
        for line in paragraph.splitlines():
            if re.search(rf'\b{fid}\b', line):
                found = DECISION.search(paragraph)
                if found:
                    return found.group(1).lower()
    return None


def checklist(directory):
    directory = Path(directory)
    response = directory / 'REVIEW_RESPONSE.md'
    text = response.read_text(errors='replace') if response.is_file() else None
    rows = []
    for review in valid_records(directory):
        for fid, summary in findings(review):
            rows.append((Path(review).name, fid, summary, decision(scope(text, review), fid) if text else None))
    return text is not None, rows


def check(directory, mode):
    if mode == 'off':
        return 0
    has_response, rows = checklist(directory)
    if not rows:
        if not has_response:
            print('  WARN no REVIEW_RESPONSE.md: record what was done about each finding (protocol 6.5)')
        return 0
    open_rows = [r for r in rows if not r[3]]
    level = 'FAIL' if mode == 'require' else 'WARN'
    if not has_response:
        print(f'  {level} no REVIEW_RESPONSE.md, and the review(s) list {len(rows)} numbered finding(s) '
              '(protocol 6.5); start from: arh gate results -n N --skeleton')
    else:
        answered = len(rows) - len(open_rows)
        print(f'  {"OK  " if not open_rows else level} review response answers {answered} of {len(rows)} numbered finding(s)')
    for review, fid, summary, found in rows:
        mark = f'answered ({found})' if found else 'UNANSWERED'
        print(f'       {review}: {fid} {mark}: {summary}')
    if open_rows and has_response:
        # "F4: noted." reads as an answer and was refused without saying why (field feedback #85).
        print('       an answer is the finding id with one of: ' + ', '.join(DECISION_WORDS)
              + ' (and the reason), in the same paragraph')
    return 1 if open_rows and mode == 'require' else 0


def skeleton(directory):
    _, rows = checklist(directory)
    print('# Review response\n')
    print('Each finding: accepted, rejected, fixed, deferred or disputed, with the reason and what was done.')
    print('A finding that needs new computation goes through `arh verify`, not into this iteration.\n')
    directory = Path(directory)
    unsound = {Path(r).name for r in valid_records(directory) if verdict_of(r) == 'UNSOUND'}
    current = None
    for review, fid, summary, _ in rows:
        if review != current:
            print(f'\n## {review}\n')
            if review in unsound:
                print('Verdict: <rebutted, because <reason> | accepted>  (UNSOUND: a rebuttal goes to the '
                      'reviewer with arh ask --rebuttal; accepted leaves this iteration unconcluded)\n')
            current = review
        print(f'- {fid}: <accepted | rejected | fixed | deferred | disputed> — <reason>  ({summary})')
    for review in sorted(unsound - {r[0] for r in rows}):
        print(f'\n## {review}\n\nVerdict: <rebutted, because <reason> | accepted>')
    if not rows and not unsound:
        print('(the eligible reviews list no numbered findings)')


if __name__ == '__main__':
    if sys.argv[1] == 'check':
        sys.exit(check(sys.argv[2], sys.argv[3]))
    elif sys.argv[1] == 'skeleton':
        skeleton(sys.argv[2])
    elif sys.argv[1] == 'verdicts':
        sys.exit(verdicts(sys.argv[2], sys.argv[3]))
    elif sys.argv[1] == 'summary':
        print(summary(sys.argv[2]))
    elif sys.argv[1] == 'pending':
        pending(sys.argv[2])
    elif sys.argv[1] == 'rebuttal':
        sys.stdout.write(scope(response_text(sys.argv[2]) or '', sys.argv[3]))
    else:
        sys.exit(f'unknown command: {sys.argv[1]}')
