"""Shell-free harness dispatch and hash-bound cross-check records (stdlib only)."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import selectors
import subprocess
import sys
import tempfile
import time

from project import config as project_config, knowledge_hashes


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def result_artifacts(directory):
    directory = Path(directory)
    return {str(p.relative_to(directory)): digest(p)
            for p in sorted((directory / 'results').rglob('*')) if p.is_file()}


def claimed_terms(directory):
    """SHA-256 of harnesses.md when the iteration was claimed; None for claims older than the key."""
    try:
        return json.loads((Path(directory) / 'CLAIM.json').read_text()).get('harness_config_sha256') or None
    except (OSError, ValueError, AttributeError):
        return None


def changed_terms(directory, config):
    """{key: [at claim, now]} for every arh-config value that differs from the claim-time copy."""
    snapshot = Path(directory) / 'metadata/harnesses.claimed.md'
    if not snapshot.is_file():
        return None
    old, new = project_config(snapshot), project_config(config)
    return {k: [old.get(k), new.get(k)] for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)}


def terms_and_families_ok(data, claimed):
    """Whether a review or adjudication record ran under the iteration's terms and family rule."""
    pf, vf = data['producer_family'], data['verifier_family']
    # Which rule this review ran under is read from the review, not from today's config:
    # relaxing require_foreign_family later must not retroactively validate an old review,
    # and tightening it must not invalidate one. Records written before the key existed
    # default to True, the behaviour they were produced under.
    strict = data.get('require_foreign_family', True)
    families_ok = (pf != vf and not data['same_family_override']) if strict else True
    # The review terms (verifier, fallbacks, family rule, bounds) are bound to the iteration when it
    # is claimed. A review taken under changed terms counts only if it records why (arh ask
    # --terms-changed): otherwise a producer could relax the rules of its own cross-check.
    # Records older than the key carry no terms hash and are judged as before.
    terms_ok = (not claimed or 'harness_config_sha256' not in data
                or data['harness_config_sha256'] == claimed or bool(data.get('terms_changed')))
    return (pf not in ('', 'unknown', 'mixed') and vf not in ('', 'unknown', 'mixed')
            and families_ok and terms_ok)


def valid_records(directory):
    directory = Path(directory)
    valid = []
    claimed = claimed_terms(directory)
    for record in sorted(directory.glob('CROSSCHECK_*.md.json')):
        try:
            data = json.loads(record.read_text())
            output = Path(str(record)[:-5])
            report = directory / 'results/report' / (directory.name + '_report.md')
            if (data['exit_code'] == 0 and data['verdict'] in ('SOUND', 'QUALIFIED', 'UNSOUND')
                    and terms_and_families_ok(data, claimed)
                    and data['review_sha256'] == digest(output)
                    and data['report_sha256'] == digest(report)
                    and data['predeclaration_sha256'] == digest(directory / 'README.md')
                    and ('result_artifacts' not in data or data['result_artifacts'] == result_artifacts(directory))):
                valid.append(str(output))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return valid


def valid_adjudications(directory):
    """[(record, data)] for REBUTTAL_ records that judged a review still eligible and unchanged.
    Which rebuttal text a record judged is compared by the caller (findings.py)."""
    directory = Path(directory)
    reviews = {Path(r).name: r for r in valid_records(directory)}
    claimed = claimed_terms(directory)
    out = []
    for record in sorted(directory.glob('REBUTTAL_*.md.json')):
        try:
            data = json.loads(record.read_text())
            output = Path(str(record)[:-5])
            review = reviews.get(data['adjudicates'])
            if (review and data['exit_code'] == 0 and data['adjudication'] in ('WITHDRAWN', 'MAINTAINED')
                    and terms_and_families_ok(data, claimed)
                    and data['adjudicated_review_sha256'] == digest(review)
                    and data['review_sha256'] == digest(output)):
                out.append((str(output), data))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


# A provider that refuses the call is an unavailable verifier, not a review. Some CLIs exit 0 when
# this happens (`codex exec` printed "You've hit your usage limit" and exited 0), so it is
# recognised from the text of a response that carries no VERDICT line. A content-policy refusal is
# kept apart from limits: waiting does not help, and another model family may still review. Codex
# refused a public RNA-seq count table as "flagged for possible biological risk" (2026-09-15).
PROVIDER_ERRORS = (
    ('refusal', 77, re.compile(
        r"flagged for possible|violat\w* (our |the )?(usage|content|acceptable use) polic|"
        r"content (policy|filter|management)|safety (system|classifier|filter)|"
        r"unable to respond to this request|invalid_prompt", re.I)),
    ('limit', 75, re.compile(
        r"usage limit|session limit|rate.?limit|quota|too many requests|\b429\b|"
        r"insufficient.?(credit|balance)|try again (at|in)|overloaded", re.I)),
    # An expired or revoked key is the same as no login: OpenCode said "This API key has expired.
    # Create a new API key in OpenCode Console" and exited 1, so the fallback was never tried
    # (field feedback #75).
    ('auth', 75, re.compile(
        r"\b401\b|\b403\b|unauthori[sz]ed|authentication|not logged in|"
        r"(api.?key|token|credential|session|login)s? (has |have |is |are )?(expired|revoked|invalid)|"
        r"invalid (api.?key|token|credential)|create a new api.?key|(log ?in|sign ?in|re-?authenticate) again|"
        r"please (log ?in|sign ?in|re-?authenticate)", re.I)),
)
RETRY_HINT = re.compile(r"\b(?:try again (?:at|in)|resets?(?: at)?) [^.\n\u00b7(]*\d[^.\n\u00b7(]*", re.I)


def classify(text, prompt=''):
    """(kind, exit code, the provider's own line, retry hint) for a provider refusal, else None.

    Lines of the prompt are skipped: `codex exec` echoes the prompt to stderr, and a plan that
    mentions a usage limit was quoted back as what the provider said (field feedback #76). The
    last matching line wins, because a refusal is usually the last thing a CLI writes."""
    echoed = {l.strip() for l in prompt.splitlines() if l.strip()}
    lines = [l.strip() for l in text.splitlines() if l.strip() and l.strip() not in echoed]
    for kind, code, pattern in PROVIDER_ERRORS:
        line = next((l for l in reversed(lines) if pattern.search(l)), None)
        if line:
            hint = RETRY_HINT.search(text)
            return kind, code, line[:300], hint.group(0).strip() if hint else None
    return None


def record_field(path, key):
    try:
        return json.loads(Path(str(path) + '.json').read_text()).get(key)
    except (OSError, ValueError, AttributeError):
        return None


def provider_error(path):
    """True if the cross-check record at PATH was a provider refusal, not a review."""
    return bool(record_field(path, 'provider_error'))


def budget():
    directory, prompt, command, role, harness, pf, vf, max_input, max_rounds, note, dry = sys.argv[2:]
    size = Path(prompt).stat().st_size
    if size > int(max_input):
        d = Path(directory)
        body = d / ('DAG.md' if role == 'reimplementer' else 'results/report/' + d.name + '_report.md')
        parts = [(name, p.stat().st_size) for name, p in (('pre-declaration', d / 'README.md'), (body.stem, body))
                 if p.exists()]
        parts.append(('role, instructions and note', size - sum(n for _, n in parts)))
        # The frozen plan cannot be shortened; a field study trimmed its report three times instead (#82, #89).
        sys.exit(f"review input is {size} bytes ({', '.join(f'{name} {n}' for name, n in parts)}); "
                 f"ask_max_input_bytes is {max_input}. Shorten the report or the note, or raise "
                 "ask_max_input_bytes in .arh/config/harnesses.md and give the reason to arh ask "
                 "--terms-changed")
    for record in valid_records(directory):
        data = json.loads(Path(record + '.json').read_text())
        if (Path(record).name.startswith('CROSSCHECK_' + role + '_' + harness + '_')
                and data.get('command_template') == command
                and data.get('prompt_sha256') == digest(prompt)
                and data['producer_family'] == pf and data['verifier_family'] == vf):
            print(record)
            return
    if dry == '1':
        return
    # Provider refusals are not review rounds: counting them let one quota error spend half of
    # an iteration's two-round budget without any model having read the work. Nor is a same-family
    # check taken with --same-family, which cannot satisfy the gate: it made the first foreign-family
    # review a "further review" that needed --note (field feedback #83).
    attempts = len([p for p in Path(directory).glob('CROSSCHECK_*.md')
                    if not provider_error(p) and not (record_field(p, 'same_family_override')
                                                      and record_field(p, 'require_foreign_family'))])
    if attempts >= int(max_rounds):
        sys.exit('review round budget exhausted; leave unresolved work recorded or deliberately revise the budget')
    if attempts and not note.strip():
        sys.exit('a further review requires --note describing the concrete unresolved issue')


def cli_version(template, cwd):
    """First output line of the harness's configured version command, recorded so a verdict can be
    traced to the CLI build that produced it. Never trusted for eligibility."""
    if not template.strip():
        return None
    try:
        out = subprocess.run(shlex.split(template), cwd=cwd, stdin=subprocess.DEVNULL,
                             capture_output=True, text=True, timeout=15)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    lines = (out.stdout.strip() or out.stderr.strip()).splitlines()
    return lines[0][:200] if lines else None


def run():
    command, prompt_file, cwd, output, seconds, pf, vf, override, output_limit = sys.argv[2:11]
    version_cmd = sys.argv[11] if len(sys.argv) > 11 else ''
    # '0' when the project accepts a same-family review; appended last so older callers keep working.
    strict = (sys.argv[12] if len(sys.argv) > 12 else '1') != '0'
    terms_reason = (sys.argv[13] if len(sys.argv) > 13 else '').strip()
    # A JSON object for an adjudication of a rebuttal (arh ask --rebuttal): which review it judges,
    # that review's hash and the rebuttal text's hash. Absent for an ordinary review.
    judging = json.loads(sys.argv[14]) if len(sys.argv) > 14 and sys.argv[14] else None
    version = cli_version(version_cmd, cwd)
    prompt = Path(prompt_file).read_text()
    # {usage}: a path the command may write a JSON object of token counts or cost to.
    usage_file = output + '.usage.json' if '{usage}' in command else None
    values = {'{prompt}': prompt, '{cwd}': cwd, '{usage}': usage_file}
    argv = [re.sub(r'\{prompt\}|\{cwd\}|\{usage\}', lambda match: values[match.group()], arg)
            for arg in shlex.split(command)]
    if not argv:
        raise ValueError('empty harness command')
    timeout = float(seconds)
    if timeout <= 0:
        raise ValueError('ask_timeout must be positive')
    directory = Path(output).parent
    report = directory / 'results/report' / (directory.name + '_report.md')
    reviewed_report = digest(report) if report.exists() else None
    reviewed_predeclaration = digest(directory / 'README.md')
    reviewed_artifacts = result_artifacts(directory)
    config = Path(cwd, '.arh/config/harnesses.md')
    terms = digest(config) if config.is_file() else None
    claimed = claimed_terms(directory)
    changed = bool(claimed) and terms != claimed
    started = time.time()
    limit = int(output_limit)
    if limit <= 0:
        raise ValueError('ask_max_output_bytes must be positive')
    sent_input = None if '{prompt}' in command else open(prompt_file, 'rb')
    with open(output, 'ab') as stdout, open(output + '.err', 'wb') as stderr:
        try:
            process = subprocess.Popen(argv, cwd=cwd, stdin=sent_input or subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True)
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ, (stdout, limit))
            selector.register(process.stderr, selectors.EVENT_READ, (stderr, 16384))
            received = {process.stdout: 0, process.stderr: 0}
            tail = b''                  # a refusal is usually the last thing a CLI writes
            rc = None
            while selector.get_map():
                if time.time() - started >= timeout:
                    rc = 124
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    break
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target, maximum = key.data
                    available = max(0, maximum - received[key.fileobj])
                    target.write(chunk[:available])
                    received[key.fileobj] += len(chunk)
                    if key.fileobj is process.stderr:
                        tail = (tail + chunk)[-8192:]
                    # Only the review (stdout) is bounded. stderr is diagnostic: it is truncated
                    # on disk but drained, never fatal — `codex exec` echoes the whole prompt to
                    # stderr, so a stderr cap killed every review whose prompt exceeded it.
                    if received[key.fileobj] > maximum and key.fileobj is process.stdout:
                        rc = 66
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        break
                if rc is not None:
                    break
            selector.close()
            try:
                status = process.wait(timeout=max(0.01, timeout - (time.time() - started)))
            except subprocess.TimeoutExpired:
                rc = 124
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                status = process.wait()
            rc = status if rc is None else rc
            if received[process.stderr] > 16384:
                stderr.write(b'\n[stderr truncated; its last 8 KB follow]\n' + tail)
            if rc == 66:
                stderr.write(b'\nReview output exceeded its byte limit; response is incomplete.\n')
        finally:
            if sent_input:
                sent_input.close()
    text = Path(output).read_text(errors="replace")
    if judging:
        found = re.findall(r'^ADJUDICATION: (WITHDRAWN|MAINTAINED)\s*$', text, re.M)
        verdict = None
        adjudication = found[0] if len(found) == 1 else None
    else:
        verdicts = re.findall(r'^VERDICT: (SOUND|QUALIFIED|UNSOUND)\s*$', text, re.M)
        verdict = verdicts[0] if len(verdicts) == 1 else None
        adjudication = None
    provider = None
    if not (verdict or adjudication):
        err = Path(output + '.err')
        provider = classify(text + '\n' + (err.read_text(errors="replace") if err.exists() else ''), prompt)
        # A timeout produced no review either. It used to spend a review round and stop the fallback
        # chain, so a verifier that timed out on four iterations in a row stalled them all (#51).
        if provider is None and rc == 124:
            provider = ('timeout', 75, f'no answer within {seconds} s (ask_timeout or harness_<name>_timeout)', None)
        if provider and provider[0] == 'timeout':
            print('arh: ' + provider[2], file=sys.stderr)       # the record keeps exit 124
        elif provider:
            rc = provider[1]
            print('provider said: ' + provider[2], file=sys.stderr)
        elif rc == 0:
            rc = 65
    usage = None
    if usage_file and Path(usage_file).is_file():
        try:
            if Path(usage_file).stat().st_size <= 65536:
                usage = json.loads(Path(usage_file).read_text(errors="replace"))
        except ValueError:
            usage = None
        Path(usage_file).unlink()
    data = dict(exit_code=rc, verdict=verdict, producer_family=pf, verifier_family=vf,
                same_family_override=override == '1', require_foreign_family=strict,
                started=started, finished=time.time(),
                command_template=command, cwd=cwd, prompt_sha256=digest(prompt_file),
                review_sha256=digest(output), report_sha256=reviewed_report,
                predeclaration_sha256=reviewed_predeclaration, result_artifacts=reviewed_artifacts,
                provider_error=provider is not None, provider_error_kind=provider and provider[0],
                provider_message=provider and provider[2], retry_hint=provider and provider[3],
                usage=usage, verifier_version=version, verifier_version_cmd=version_cmd or None,
                harness_config_sha256=terms, knowledge_sha256=knowledge_hashes(cwd),
                terms_changed=(terms_reason or None) if changed else None,
                terms_changed_keys=changed_terms(directory, config) if changed else None)
    if judging:
        data.update(kind='adjudication', adjudication=adjudication, adjudicates=judging['adjudicates'],
                    adjudicated_review_sha256=judging['review_sha256'],
                    rebuttal_sha256=judging['rebuttal_sha256'])
    with open(output + '.json', 'x') as record:
        json.dump(data, record, indent=2)
        record.write('\n')
    return 75 if provider and provider[0] == 'timeout' else rc


def probe():
    """One short call to a verifier, so an expired login or an exhausted quota shows up in `arh doctor
    --probe` and not when an iteration needs its review (field feedback #54, #75). Prints OK or the
    provider's own line; exit 0, 75 or 77 as for a review."""
    command, _, seconds = sys.argv[2:5]
    prompt = 'This is a connectivity check. Reply with the single word OK.'
    # Run outside the project, so the CLI does not load the project's instructions for a one-word reply.
    scratch = tempfile.TemporaryDirectory(prefix='arh-probe-')
    cwd = scratch.name
    with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as handle:
        handle.write(prompt)
    values = {'{prompt}': prompt, '{cwd}': cwd, '{usage}': os.devnull}
    try:
        argv = [re.sub(r'\{prompt\}|\{cwd\}|\{usage\}', lambda m: values[m.group()], arg) for arg in shlex.split(command)]
        out = subprocess.run(argv, cwd=cwd, stdin=open(handle.name) if '{prompt}' not in command else subprocess.DEVNULL,
                             capture_output=True, text=True, timeout=float(seconds), start_new_session=True)
    except subprocess.TimeoutExpired:
        print(f'no answer within {seconds} s')
        return 75
    except (OSError, ValueError) as error:
        print(f'could not start: {error}')
        return 1
    finally:
        os.unlink(handle.name)
        scratch.cleanup()
    provider = classify(out.stdout + '\n' + out.stderr, prompt)
    if provider:
        print(f'{provider[0]}: {provider[2]}')
        return provider[1]
    if out.returncode:
        tail = (out.stderr.strip() or out.stdout.strip()).splitlines()[-1:] or ['no output']
        print(f'exit {out.returncode}: {tail[0][:200]}')
        return out.returncode
    print('OK')
    return 0


if __name__ == '__main__':
    if sys.argv[1] == 'probe':
        sys.exit(probe())
    elif sys.argv[1] == 'budget':
        budget()
    elif sys.argv[1] == 'valid':
        print('\n'.join(valid_records(sys.argv[2])))
    elif sys.argv[1] == 'describe':
        directory = Path(sys.argv[2])
        valid = set(valid_records(directory))
        for path in sorted(directory.glob('CROSSCHECK_*.md')):
            if str(path) in valid:
                data = json.loads(Path(str(path) + '.json').read_text())
                # An accepted review that deviates from the default rules says so on every reading.
                notes = []
                if data['producer_family'] == data['verifier_family']:
                    notes.append('same model family, accepted because require_foreign_family = false')
                if data.get('terms_changed'):
                    keys = ', '.join(data.get('terms_changed_keys') or {}) or 'no claim-time copy to compare'
                    notes.append(f"review terms changed since the claim ({keys}): {data['terms_changed']}")
                print(path.name + ': ' + data['verdict'] + ''.join('; ' + n for n in notes))
            elif record_field(path, 'provider_error_kind') == 'refusal':
                print(path.name + ': PROVIDER REFUSAL (content policy; not a review round)')
            elif provider_error(path):
                print(path.name + ': PROVIDER ERROR (verifier unavailable; not a review round)')
            else:
                print(path.name + ': INELIGIBLE (missing/failed metadata, invalid verdict, family or artifact '
                      'hash, or review terms changed since the claim without a recorded reason)')
    else:
        sys.exit(run())
