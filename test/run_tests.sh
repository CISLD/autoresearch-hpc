#!/usr/bin/env bash
# AutoResearch HPC test suite. Exercises the whole loop end to end with a generic
# toy study — no domain tools, no cluster, no network.
#
#   test/run_tests.sh            run in a temp dir, clean up
#   KEEP=1 test/run_tests.sh     keep the scratch project for inspection
set -uo pipefail
: "${ARH_TEST_SITE:?Set ARH_TEST_SITE to a configured local Nextflow/Singularity site.md}"

ARH_HOME=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export ARH_HOME PATH="$ARH_HOME/bin:$PATH" ARH_VERBOSE=1
# A Slurm or PBS site.md made the suite submit real jobs and report failures that had nothing to do
# with the protocol: 142 of 143 with a Slurm site.md, all 154 with a local one (2026-09-16).
[ -f "$ARH_TEST_SITE" ] || { echo "ARH_TEST_SITE is not a file: $ARH_TEST_SITE" >&2; exit 2; }
# Read the key the way arh does, in a subshell: common.sh sets -e, and this suite must not.
# shellcheck source=lib/common.sh
[ "$(. "$ARH_HOME/lib/common.sh"; arh_config_get "$ARH_TEST_SITE" scheduler local)" = local ] \
  || { echo "ARH_TEST_SITE must set scheduler = local, not a real scheduler: $ARH_TEST_SITE" >&2; exit 2; }

WORK=$(mktemp -d "${TMPDIR:-/tmp}/arh-test.XXXXXX")
PROJ="$WORK/toy"
pass=0; fail=0

ok()   { pass=$((pass+1)); printf '  ok %2d — %s\n' "$((pass+fail))" "$1"; }
no()   { fail=$((fail+1)); printf 'not ok %2d — %s\n' "$((pass+fail))" "$1"
         [ -n "${2-}" ] && printf '     %s\n' "$2"; }
# check <desc> <expect-exit 0|1> <cmd...>
check() {
  local desc="$1" want="$2"; shift 2
  local out rc
  out=$("$@" 2>&1); rc=$?
  if { [ "$want" = 0 ] && [ "$rc" = 0 ]; } || { [ "$want" != 0 ] && [ "$rc" != 0 ]; }
  then ok "$desc"; else no "$desc" "exit $rc (wanted ${want}); output: $(printf '%s' "$out" | tail -3 | tr '\n' ' ')"; fi
}
grep_ok() { # <desc> <pattern> <file>
  if grep -qE "$2" "$3" 2>/dev/null; then ok "$1"; else no "$1" "pattern '$2' not in $3"; fi
}

cleanup() { [ -n "${KEEP:-}" ] && printf '\nkept: %s\n' "$WORK" || rm -rf "$WORK"; }
trap cleanup EXIT

printf '# AutoResearch HPC test suite\n# scratch: %s\n\n' "$WORK"

# --- 1. framework --------------------------------------------------------
printf '# framework\n'
check "arh prints usage"                    0 arh --help
check "arh rejects an unknown command"      1 arh nonsense
check "arh doctor runs outside a project"   0 env ARH_PROJECT="$WORK" arh doctor
for f in "$ARH_HOME"/bin/arh*; do
  bash -n "$f" 2>/dev/null && ok "syntax: $(basename "$f")" || no "syntax: $(basename "$f")"
done
python3 -c "
import json,glob,sys
for f in sorted(glob.glob('$ARH_HOME/schema/*.json')): json.load(open(f))
" && ok "schemas are valid JSON" || no "schemas are valid JSON"

# --- 2. init -------------------------------------------------------------
printf '\n# init\n'
check "arh init creates a project"          0 arh init "$PROJ"
if [ -n "${ARH_TEST_SITE:-}" ]; then cp "$ARH_TEST_SITE" "$PROJ/.arh/config/site.md"; fi
check "arh init refuses to re-init"         1 arh init "$PROJ"
for p in .arh/config/site.md .arh/config/project.md .arh/config/harnesses.md .arh/config/generators.md \
         PROGRESS.md AGENTS.md GOTCHAS.md DIRECTIVES.md rules/null-is-upper-bound.md .arh/registry.tsv; do
  [ -e "$PROJ/$p" ] && ok "created $p" || no "created $p"
done
[ -L "$PROJ/CLAUDE.md" ] && ok "CLAUDE.md symlinks to AGENTS.md" || no "CLAUDE.md symlinks to AGENTS.md"

cd "$PROJ" || exit 1
check "arh doctor passes on a fresh project" 0 arh doctor

# --- 3. claiming ---------------------------------------------------------
printf '\n# claiming\n'
n=$(arh claim -t "Does the toy signal exceed its null?" -a tester 2>/dev/null)
[ "$n" = 1 ] && ok "first claim returns 1" || no "first claim returns 1" "got '$n'"
[ -f "iterations/iteration1/CLAIM.json" ] && ok "CLAIM.json written" || no "CLAIM.json written"
python3 -c "import json;json.load(open('iterations/iteration1/CLAIM.json'))" 2>/dev/null \
  && ok "CLAIM.json is valid JSON" || no "CLAIM.json is valid JSON"
grep_ok "registry row appended" "^1[[:space:]]+tester" .arh/registry.tsv
python3 -c "import json; assert 'DIRECTIVES.md' in json.load(open('iterations/iteration1/CLAIM.json'))['knowledge_sha256']" 2>/dev/null \
  && ok "claim records the knowledge files' hashes" || no "claim records the knowledge files' hashes"

# Concurrent claims must not collide. This is the failure the protocol exists
# to prevent: two agents creating the same iteration directory.
for i in 1 2 3 4 5 6; do ( arh claim -t "concurrent $i" -a "agent$i" >"$WORK/c$i" 2>/dev/null ) & done
wait
got=$(cat "$WORK"/c[1-6] 2>/dev/null | sort -n | tr '\n' ' ')
uniq_n=$(cat "$WORK"/c[1-6] 2>/dev/null | sort -n | uniq | wc -l)
[ "$uniq_n" = 6 ] && ok "6 concurrent claims get 6 distinct numbers" \
  || no "6 concurrent claims get 6 distinct numbers" "got: $got"
dirs=$(ls -1d iterations/iteration* | wc -l)
[ "$dirs" = 7 ] && ok "7 iteration directories exist" || no "7 iteration directories exist" "got $dirs"

# --- 4. pre-declaration gate --------------------------------------------
printf '\n# pre-declaration gate\n'
check "arh new scaffolds the README"         0 arh new -n 1
check "arh new refuses to overwrite"         1 arh new -n 1
check "gate rejects an unfilled template"   1 arh gate predeclare -n 1
if [ -f iterations/iteration1/PREDECLARATION.sha256 ]
then no "a failed gate freezes nothing"; else ok "a failed gate freezes nothing"; fi

cat > iterations/iteration1/README.md <<'EOF'
# Iteration 1 — Does the toy signal exceed its null?

**Status: PRE-DECLARED. Written BEFORE any result exists.**

## 1. Question
Does the mean of series A exceed the mean of series B by more than chance?

## 2. Estimand
The difference in means, A minus B, in raw units, over all 100 paired draws.

## 3. Instrument
python3 stdlib only, seed 20260908, sorted inputs, no container required.

## 4. Acceptance criteria
Both series carry exactly 100 records; no missing values; row counts reconcile.

## 5. Negative controls
Series B against a label-permuted copy of itself; expected to be null.

## 6. Detection limit
0.20 raw units at 80% power for n=100; smaller true differences are not
resolvable by this design and are reported as within the detection limit.

## 7. Prediction
The difference will be null and the negative control will not fire.

## 8. Limits of the conclusion
Results are associated with the grouping variable and cannot separate it from
draw order. Any null is an upper bound at the stated detection limit. Nothing
here is orthogonally validated, so every result is a candidate.
EOF
check "gate accepts a complete pre-declaration" 0 arh gate predeclare -n 1
[ -f iterations/iteration1/PREDECLARATION.sha256 ] && ok "hash frozen" || no "hash frozen"
frozen=$(head -1 iterations/iteration1/PREDECLARATION.sha256)

# A pre-declaration written after the results is not a pre-declaration.
arh new -n 2 >/dev/null 2>&1
mkdir -p iterations/iteration2/results && echo "answer" > iterations/iteration2/results/out.tsv
check "gate rejects pre-declaration after results exist" 1 arh gate predeclare -n 2

# --- 5. running work -----------------------------------------------------
printf '\n# running work\n'
mkdir -p iterations/iteration1/scripts iterations/iteration1/results/report
cat > iterations/iteration1/scripts/it1_01_toy.py <<'EOF'
"""Generic toy analysis: paired difference in means with a permutation null."""
import random, statistics, pathlib, sys
random.seed(20260908)
n = 100
a = [random.gauss(0, 1) for _ in range(n)]
b = [random.gauss(0, 1) for _ in range(n)]
assert len(a) == len(b) == n, "row counts must reconcile"
obs = statistics.mean(a) - statistics.mean(b)
pool = a + b
null = []
for _ in range(2000):
    random.shuffle(pool)
    null.append(statistics.mean(pool[:n]) - statistics.mean(pool[n:]))
p = sum(1 for x in null if abs(x) >= abs(obs)) / len(null)
out = pathlib.Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(f"metric\tvalue\nn\t{n}\ndiff_means\t{obs:.6f}\nperm_p\t{p:.4f}\n")
print(f"n={n} diff={obs:.6f} p={p:.4f}")
EOF
cat > iterations/iteration1/scripts/it1_01_run.sh <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$PROJ" || exit 1
python3 iterations/iteration1/scripts/it1_01_toy.py iterations/iteration1/results/it1_01_result.tsv
EOF
chmod +x iterations/iteration1/scripts/it1_01_run.sh

jid=$(arh submit iterations/iteration1/scripts/it1_01_run.sh -n it1_01 \
        -l iterations/iteration1/logs -w 2>/dev/null)
[ -n "$jid" ] && ok "arh submit returned a job id ($jid)" || no "arh submit returned a job id"
for _ in $(seq 1 50); do [ -s iterations/iteration1/results/it1_01_result.tsv ] && break; sleep 0.2; done
[ -s iterations/iteration1/results/it1_01_result.tsv ] \
  && ok "job produced results" || no "job produced results"
grep_ok "results reconcile to n=100" "^n[[:space:]]+100" iterations/iteration1/results/it1_01_result.tsv
check "arh run uses the configured Singularity runtime" 0 arh run runtime -- true

# --- 6. guard ------------------------------------------------------------
printf '\n# immutable-input guard\n'
check "guard allows a path inside the project" 0 arh guard "$PROJ/iterations/iteration1/results/x"
check "guard refuses a path outside"           1 arh guard /etc/passwd
python3 - <<EOF
import re,pathlib
p=pathlib.Path(".arh/config/project.md"); s=p.read_text()
p.write_text(s.replace("immutable_inputs  =", "immutable_inputs  = $WORK/raw"))
EOF
mkdir -p "$WORK/raw"
check "guard refuses a declared immutable input" 1 arh guard "$WORK/raw/x"

# --- 7. standing rules ---------------------------------------------------
printf '\n# standing rules\n'
cat > "$WORK/bad_report.md" <<'EOF'
# Report
The exposure causes the outcome. There is no effect in the control arm.
EOF
check "rules reject causal language and a bare null" 1 arh gate rules "$WORK/bad_report.md"
cat > "$WORK/good_report.md" <<'EOF'
# Report
The exposure is associated with the outcome; this design cannot separate it from
draw order and the claim is not causal. The control arm is null: we cannot
exclude effects below the stated detection limit of 0.20 units, which is the
upper bound this design supports. Negative controls did not fire.
EOF
check "rules accept a properly qualified report" 0 arh gate rules "$WORK/good_report.md"

# --- 8. results gate & tamper detection ---------------------------------
printf '\n# results gate\n'
check "results gate fails with no report" 1 arh gate results -n 1
cat > iterations/iteration1/results/report/iteration1_report.md <<'EOF'
# Iteration 1 report

## Headline
The difference in means is associated with nothing detectable: the observed
difference is null, and we cannot exclude effects below the detection limit of
0.20 raw units, which is the upper bound this design supports.

## Negative controls
The label-permuted control did not fire, as pre-declared.

## Result
diff_means and perm_p are in results/it1_01_result.tsv. n = 100, reconciled.

## Was the prediction right?
Yes — §7 predicted a null with a quiet negative control.

## What this does not establish
Association only; the design cannot separate grouping from draw order. The
result is a candidate, not a validated finding.
EOF
check "results gate still fails with no cross-check" 1 arh gate results -n 1
cat > "iterations/iteration1/CROSSCHECK_adversary_codex_20260908T000000Z.md" <<'EOF'
# Cross-check — iteration 1
VERDICT: SOUND
No findings; the null is reported as an upper bound.
EOF
python3 - "$ARH_HOME" <<'PYTEST'
import sys, json
from pathlib import Path
sys.path.insert(0, sys.argv[1] + '/lib')
from harness import digest
p=Path('iterations/iteration1/CROSSCHECK_adversary_codex_20260908T000000Z.md')
data=dict(exit_code=0, verdict='SOUND', producer_family='anthropic', verifier_family='openai', same_family_override=False,
          review_sha256=digest(p), report_sha256=digest('iterations/iteration1/results/report/iteration1_report.md'),
          predeclaration_sha256=digest('iterations/iteration1/README.md'))
Path(str(p)+'.json').write_text(json.dumps(data))
PYTEST
check "results gate passes when cross-checked" 0 arh gate results -n 1

# The core mechanism: editing the pre-declaration after results must be caught.
printf '\n' >> iterations/iteration1/README.md
echo "## 9. Added after the fact" >> iterations/iteration1/README.md
check "tampering with a frozen pre-declaration is caught" 1 arh gate results -n 1
grep_ok "tamper report names the file" "README.md CHANGED" <(arh gate results -n 1 2>&1)
python3 - <<'EOF'
import pathlib
p = pathlib.Path("iterations/iteration1/README.md")
lines = p.read_text().splitlines(True)
p.write_text("".join(lines[:-2]))
EOF
now=$(if command -v sha256sum >/dev/null 2>&1
      then sha256sum iterations/iteration1/README.md
      else shasum -a 256 iterations/iteration1/README.md; fi | awk '{print $1}')
[ "$now" = "$frozen" ] && ok "restored README matches the frozen hash" \
  || no "restored README matches the frozen hash"
check "results gate passes again after restore" 0 arh gate results -n 1

# --- 9. cross-harness dispatch ------------------------------------------
printf '\n# cross-harness dispatch\n'
check "arh ask --dry-run composes a prompt"    0 arh ask --role adversary -n 1 --dry-run
out=$(arh ask --role adversary -n 1 --dry-run 2>&1)
printf '%s' "$out" | grep -q "^# Role: adversary" \
  && ok "prompt carries the role instructions" || no "prompt carries the role instructions"
printf '%s' "$out" | grep -q "PRE-DECLARED" \
  && ok "prompt carries the pre-declaration" || no "prompt carries the pre-declaration"
printf '%s' "$out" | grep -q "DIRECTIVES.md" \
  && ok "prompt points the reviewer at the directives" || no "prompt points the reviewer at the directives"
check "arh ask rejects an unknown role"        1 arh ask --role nonsense -n 1 --dry-run
python3 - <<'EOF'
import pathlib
p = pathlib.Path(".arh/config/harnesses.md")
p.write_text(p.read_text().replace("verifier   = codex", "verifier   = claude"))
EOF
# Swapping the verifier after the claim changes the review terms: refused without a reason.
check "changed review terms need a reason"    1 arh ask --role adversary -n 1 --dry-run --same-family
check "same-family verification is refused"   1 arh ask --role adversary -n 1 --dry-run --terms-changed "verifier swapped"
check "--same-family overrides it"            0 arh ask --role adversary -n 1 --dry-run --same-family --terms-changed "verifier swapped"
python3 - <<'EOF'
import pathlib
p = pathlib.Path(".arh/config/harnesses.md")
p.write_text(p.read_text().replace("verifier   = claude", "verifier   = codex"))
EOF

# --- 10. ledger ----------------------------------------------------------
printf '\n# ledger\n'
check "arh ledger render"  0 arh ledger render
grep_ok "status table rendered" "^\| 1 \| tester" PROGRESS.md
grep_ok "frozen state shown"    "frozen" PROGRESS.md
check "arh ledger render is idempotent" 0 arh ledger render
[ "$(grep -c 'arh:status:begin' PROGRESS.md)" = 1 ] \
  && ok "render does not duplicate the table" || no "render does not duplicate the table"
check "arh status runs" 0 arh status
grep_ok "status shows the cross-check" "yes" <(arh status 2>&1)

python3 - <<'EOF'
import pathlib
p = pathlib.Path("iterations/iteration1/README.md")
p.write_text(p.read_text() + "\ntampered\n")
EOF
check "ledger check catches an altered pre-declaration" 1 arh ledger check
grep_ok "ledger names the altered iteration" "iteration 1 — README.md altered" <(arh ledger check 2>&1)
python3 - <<'RESTORE'
from pathlib import Path
p = Path('iterations/iteration1/README.md')
p.write_text(p.read_text().removesuffix('\ntampered\n'))
RESTORE

# --- 11. config ----------------------------------------------------------
printf '\n# configuration\n'
python3 - <<'EOF'
import pathlib
p = pathlib.Path(".arh/config/site.md")
p.write_text(p.read_text().replace("scheduler         = local", "scheduler         = nonesuch"))
EOF
check "doctor fails on an unknown scheduler backend" 1 arh doctor
python3 - <<'EOF'
import pathlib
p = pathlib.Path(".arh/config/site.md")
p.write_text(p.read_text().replace("scheduler         = nonesuch", "scheduler         = local"))
EOF
check "doctor passes when the config matches the machine" 0 arh doctor

# --- 11b. site discovery --------------------------------------------------
printf '\n# site discovery\n'
check "arh site prints usage"                    0 arh site --help
check "arh site rejects an unknown subcommand"   1 arh site bogus
check "arh site rejects an unknown scheduler"    1 arh site detect --scheduler bogus
check "arh site rejects --scheduler with no name" 1 arh site detect --scheduler
check "arh site detect runs on any host"         0 arh site detect
# A scheduler the framework does not support must still be reported, and must never
# be proposed as a site.md value — site.md accepts only slurm, pbs or local.
arh site detect --scheduler lsf > "$WORK/site-lsf.txt" 2>&1
check "arh site detect reports an unsupported scheduler" 0 test -s "$WORK/site-lsf.txt"
grep_ok "unsupported scheduler is named"  'scheduler:  *lsf'         "$WORK/site-lsf.txt"
grep_ok "unsupported scheduler is flagged" 'not a value site.md accepts' "$WORK/site-lsf.txt"
grep_ok "unsupported scheduler falls back to local" '^scheduler +=  *local' "$WORK/site-lsf.txt"
arh site detect --scheduler local > "$WORK/site-local.txt" 2>&1
grep_ok "local proposal has no queue keys" '^container_runtime' "$WORK/site-local.txt"

# --- 12. arms -------------------------------------------------------------
printf '\n# arms\n'
check "arh arm list on an iteration with none" 0 arh arm list -n 1
check "arh arm new refuses before pre-declaration" 1 arh arm new -n 2 -a A -t "too early"
check "arh arm new scaffolds"                  0 arh arm new -n 1 -a A -t "the primary route"
check "arh arm new refuses a duplicate"        1 arh arm new -n 1 -a A
check "arh arm new rejects a path segment"     1 arh arm new -n 1 -a ../escape
check "arm gate rejects an unfilled template" 1 arh arm gate -n 1 -a A
cat > iterations/iteration1/arms/A/README.md <<'EOF'
# Iteration 1 · Arm A — the primary route

## 1. What this arm tests
Whether the difference survives when draws are matched by index.

## 2. Acceptance criteria
100 matched pairs retained; no index collisions; counts reconcile.

## 3. Negative control
Index-shuffled pairing, expected null.

## 4. Fate
PLANNED
EOF
check "arm gate accepts a complete arm"       0 arh arm gate -n 1 -a A
grep_ok "arm shows as frozen" "^A[[:space:]]+frozen" <(arh arm list -n 1 2>&1)
check "arh arm fate rejects an invalid fate"   1 arh arm fate -n 1 -a A -f MADE_UP
check "arh arm fate records KILLED_BY_CONTROL" 0 arh arm fate -n 1 -a A -f KILLED_BY_CONTROL
grep_ok "fate is listed" "KILLED_BY_CONTROL" <(arh arm list -n 1 2>&1)
grep_ok "a killed arm is called a reportable result" "REPORTABLE" \
  <(arh arm fate -n 1 -a A -f INFEASIBLE 2>&1)

# --- 13. discovery DAG ----------------------------------------------------
printf '\n# discovery DAG\n'
check "arh dag init scaffolds"              0 arh dag init -n 1
check "arh dag init refuses to overwrite"   1 arh dag init -n 1
check "dag check rejects the empty template" 1 arh dag check -n 1
cat > iterations/iteration1/DAG.md <<'EOF'
# Discovery DAG — iteration 1

## 1. Inputs
| id | what | identity |
|---|---|---|
| I1 | 100 paired draws | sha256:aa11 |

## 2. The graph, as it ran
```mermaid
flowchart TD
    I1 --> N1
    N1 --> N2
    N2 --> C1
```

## 3. Nodes
| id | operation | parameters | decision? | output |
|---|---|---|---|---|
| N1 | pair by index | half-open | yes | pairs |
| N2 | mean difference | none | no | diff |
| C1 | the claim | none | no | perm p |

## 4. Branch count
Three paths exist from I1 to C1 under the two pairing conventions and the
two-sided rule; one was reported. The denominator is therefore 3, not 1.

## 5. What falls out of the graph
The permutation node draws from the pooled series, so the pairing established at
N1 is discarded before the null is built. Nothing downstream restores it.

## 6. Terminal claim
The mean difference is 0.0184 raw units at permutation p = 0.87.
EOF
check "dag check passes on a complete DAG"  0 arh dag check -n 1
check "arh dag freeze"                       0 arh dag freeze -n 1
[ -f iterations/iteration1/DAG.sha256 ] && ok "DAG hash frozen" || no "DAG hash frozen"
grep_ok "dag show reports frozen state" "frozen and unchanged" <(arh dag show -n 1 2>&1)

# An orphan node is the defect the topology check exists to surface: something
# the tables describe and the graph never connects.
python3 - <<'EOF'
import pathlib
p = pathlib.Path("iterations/iteration1/DAG.md")
p.write_text(p.read_text().replace(
    "| C1 | the claim | none | no | perm p |",
    "| C1 | the claim | none | no | perm p |\n| N9 | synthetic covariate | none | yes | dosage |"))
EOF
check "dag check catches a node with no edge" 1 arh dag check -n 1
grep_ok "orphan is named" "N9" <(arh dag check -n 1 2>&1)

# --- 14. blind replication ------------------------------------------------
printf '\n# blind replication\n'
check "replicate refuses while the DAG is altered" 1 arh replicate -n 1 --agents 2 --dry-run
python3 - <<'EOF'
import pathlib
p = pathlib.Path("iterations/iteration1/DAG.md")
p.write_text(p.read_text().replace(
    "\n| N9 | synthetic covariate | none | yes | dosage |", ""))
EOF
check "replicate runs once the DAG matches again" 0 arh replicate -n 1 --agents 2 --dry-run
for f in verification/replication_it1/agent1/SPEC.md verification/replication_it1/agent1/PROMPT.md \
         verification/replication_it1/agent2/SPEC.md; do
  [ -f "$f" ] && ok "sandbox: ${f#verification/}" || no "sandbox: ${f#verification/}"
done
# The firewall: the original scripts must not reach the sandbox.
if find verification/replication_it1 -name 'it1_*' 2>/dev/null | grep -q .; then
  no "original scripts are absent from the sandbox"
else ok "original scripts are absent from the sandbox"; fi
grep_ok "prompt carries the DAG"        "Discovery DAG" verification/replication_it1/agent1/PROMPT.md
grep_ok "prompt forbids reading code"   "voids this replication" verification/replication_it1/agent1/PROMPT.md
grep_ok "prompt asks for membership"    "BY NAME" verification/replication_it1/agent1/PROMPT.md
grep_ok "prompt asks for ambiguities"   "ambiguities" verification/replication_it1/agent1/PROMPT.md

# Membership comparison across agents: contested elements must be named.
cat > verification/replication_it1/agent1/REPORT.md <<'EOF'
VERDICT: QUALIFIED
```arh-replication
value = 0.0184
members = e1,e2,e3
ambiguities = 2
```
EOF
cat > verification/replication_it1/agent2/REPORT.md <<'EOF'
VERDICT: QUALIFIED
```arh-replication
value = 0.0191
members = e1,e2,e4
ambiguities = 3
```
EOF
check "replicate report runs" 0 arh replicate report -n 1
rep=$(arh replicate report -n 1 2>&1)
printf '%s' "$rep" | grep -q "2 distinct values" && ok "divergent values are reported" \
  || no "divergent values are reported"
printf '%s' "$rep" | grep -q "contested: 2" && ok "contested membership is counted" \
  || no "contested membership is counted"
printf '%s' "$rep" | grep -q "e3" && ok "contested elements are named" || no "contested elements are named"
printf '%s' "$rep" | grep -qi "evidence, not truth" && ok "agreement is not equated with truth" \
  || no "agreement is not equated with truth"

# The reimplementer role must work from the DAG, never the directory.
grep_ok "reimplementer prompt carries the DAG" "frozen" \
  <(arh ask --role reimplementer -n 1 --dry-run 2>&1)
out=$(arh ask --role reimplementer -n 1 --dry-run 2>&1)
printf '%s' "$out" | grep -q "it1_01_toy.py" && no "reimplementer prompt leaks the code" \
  || ok "reimplementer prompt does not leak the code"
check "reimplementer refuses without a frozen DAG" 1 arh ask --role reimplementer -n 2 --dry-run

# --- 15. guidance and machine-readable output -----------------------------
printf '\n# guidance and API\n'
check "arh next runs"        0 arh next
check "arh next -n works"    0 arh next -n 1
check "arh status --json"    0 arh status --json
arh status --json > "$WORK/st.json" 2>/dev/null
python3 -c "
import json,sys
d=json.load(open('$WORK/st.json'))
assert 'iterations' in d and d['iterations'], 'no iterations in json'
i=d['iterations'][0]
for k in ('iteration','predeclaration','results','crosschecks','dag','arms'): assert k in i, k
assert i['dag']=='frozen', i['dag']
assert i['arms']==1, i['arms']
" && ok "status --json is valid and complete" || no "status --json is valid and complete"

check "arh wait returns at once when nothing runs" 0 arh wait -n 1 --timeout 5
check "arh freeze list runs"                0 arh freeze list
check "arh freeze needs the files to freeze" 1 arh freeze -n 1
check "arh note list runs"                  0 arh note list
check "arh note needs text"                1 arh note -n 1
check "arh lease show runs"                0 arh lease show -n 1
check "arh lease take needs a reason"      1 arh lease take -n 1
check "arh inputs list runs"               0 arh inputs list
check "arh status --running runs"          0 arh status --running
check "arh env list runs"                  0 arh env list
check "arh env rejects a reserved name"    1 arh env create nextflow-host zlib

# --- 16. verification track ---------------------------------------------
printf '\n# verification track\n'
check "arh verify list runs"                   0 arh verify list
check "arh verify new scaffolds"               0 arh verify new panel_recalc -m recalculation
check "arh verify new refuses a duplicate"     1 arh verify new panel_recalc
check "arh verify new rejects a path segment"  1 arh verify new ../escape
check "verify gate rejects an unfilled template" 1 arh verify gate panel_recalc
cat > verification/panel_recalc/PREDECLARATION.md <<'EOF'
# Verification pre-declaration — panel_recalc

**Written before any result exists.**

## What is being verified
Iteration 1's reported difference in means. It was null at perm p = 0.87.

## Mode
Re-implementation from the written specification alone. Recalculation would only
confirm the code runs; the claim needs independence from that code.

## Analytic variant
Within-pair label swapping rather than unrestricted permutation. Seed 20260909.

## Success criterion
Stated as membership: the same 100 pair identifiers must be retained, by name,
and the reported difference must agree to 6 decimal places.

## What a failure would mean
Disagreement in retained pairs would show the pairing was not preserved, which
changes the null the original test was against. A difference only in the sixth
decimal changes nothing about the claim.
EOF
check "verify gate accepts a complete pre-declaration" 0 arh verify gate panel_recalc
[ -f verification/panel_recalc/PREDECLARATION.sha256 ] \
  && ok "verification hash frozen" || no "verification hash frozen"
grep_ok "verify list shows frozen" "panel_recalc[[:space:]]+frozen" <(arh verify list 2>&1)
python3 - <<'EOF'
import pathlib
p = pathlib.Path("verification/panel_recalc/PREDECLARATION.md")
p.write_text(p.read_text() + "\nadded later\n")
EOF
grep_ok "verify list detects tampering" "panel_recalc[[:space:]]+ALTERED" <(arh verify list 2>&1)

# A membership criterion is required: reproducing a set's size is not
# reproducing the set (PROTOCOL.md 6.4).
arh verify new counts_only >/dev/null 2>&1
cat > verification/counts_only/PREDECLARATION.md <<'EOF'
# Verification pre-declaration — counts_only

## What is being verified
Iteration 1's candidate set, originally 41 elements at p = 0.089.

## Mode
Recalculation.

## Analytic variant
Same code, same seed 20260909, rerun on the frozen inputs.

## Success criterion
The rerun must return 41 elements.

## What a failure would mean
A different count would indicate non-determinism in the pipeline.
EOF
check "verify gate rejects a count-only success criterion" 1 arh verify gate counts_only

# --- 17. harness install -------------------------------------------------
printf '\n# harness install\n'
check "harness/install.sh runs" 0 "$ARH_HOME/harness/install.sh" "$PROJ"
for p in .claude/skills/iterate/SKILL.md .codex/config.toml opencode.json; do
  [ -e "$PROJ/$p" ] && ok "installed $p" || no "installed $p"
done

printf '\n1..%d\n' "$((pass+fail))"
printf '# passed %d, failed %d\n' "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1
