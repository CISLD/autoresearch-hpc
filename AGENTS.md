# AutoResearch HPC — agent contract

You are working inside an **AutoResearch HPC** project. This file is the
harness-agnostic contract. Codex, OpenCode, Cursor and Copilot can read it
directly; Claude Code reads it through `CLAUDE.md`, which symlinks here.

**Read `PROGRESS.md` first.** It is the authoritative project state and resume
point. Never reconstruct state from conversation history. Then read
`DIRECTIVES.md` (what the operator decided, where the data are, what was learned
outside the project) and `GOTCHAS.md` (failure modes that produce plausible
output), plus the site's shared file if `.arh/config/site.md` names one as
`site_gotchas`.

## The shape of the work

Work happens in numbered, **append-only** iterations under `iterations/`. One
iteration answers one question. A complete iteration contains:

```text
iterations/iterationN/
  CLAIM.json
  README.md                     pre-declaration, written BEFORE results
  PREDECLARATION.sha256         frozen declaration hash
  scripts/  resources/  metadata/
  results/report/iterationN_report.md
  logs/
  CROSSCHECK_<role>_<harness>_<ts>.md
  REVIEW_RESPONSE.md            your evaluation of each review finding
```

Project/runtime configuration lives under `.arh/config/`.

## The loop

```bash
arh claim -t "the question"          # atomic; returns N (--continues M: another try at M's question)
arh new -n N                         # scaffold the pre-declaration
# complete every section first
arh gate predeclare -n N             # freezes the declaration hash
# write/run the workflow
arh submit iterations/iterationN/scripts/experiment.nf -n itN_01
arh ask --role adversary -n N        # foreign-family cross-check
arh gate results -n N                # verifies the declaration stayed frozen
arh ledger render && arh ledger check
```

`arh` finds the project by walking up from the working directory. If your
harness resets the shell's directory between commands, `export ARH_PROJECT=<study>`
so every command resolves the project from anywhere.

A review is bound to the report's sha256 and to every file under `results/`.
Write the report's *Cross-check* section as a pointer before `arh ask`, and put
your evaluation of the findings in `REVIEW_RESPONSE.md` at the iteration root.
Reviewers number their findings (`F1:`, `F2:` ...); answer each by its id with a
decision and the reason (`F2: rejected, because ...`). `arh gate results` fails
while a numbered finding is unanswered, and `arh gate results -n N --skeleton`
prints a response to start from. The gate also lists numbers in the report that
match no file under `results/`: write every reported value to a results file and
copy it from there, never by hand.

An `UNSOUND` verdict needs its own answer in the review's part of
`REVIEW_RESPONSE.md`: `Verdict: rebutted, because <reason>` if the iteration
stands, or `Verdict: accepted` if it does not. A rebuttal goes to the reviewer
with `arh ask --rebuttal -n N`, and the gate passes only if the reviewer answers
`WITHDRAWN`. An accepted or maintained `UNSOUND` iteration stays unconcluded and
the correction goes into a new iteration; asking for another review does not
answer the first one. The review policy in `project.md` is bound to an iteration
when it is claimed, so editing it mid-iteration changes nothing for that
iteration. Every required section of the pre-declaration needs content of its
own, and a plan is frozen once:
`.arh/freezes.tsv` records each freeze, so deleting `PREDECLARATION.sha256` does
not reopen it, and `arh ledger check` fails if an iteration directory is removed.

To re-examine a result an iteration already produced, use the verification
track instead of silently revising the original:

```bash
arh verify new <object> -m re-implementation --of N
arh verify gate <object>
arh verify run <object> verification/<object>/scripts/check.nf   # pinned image, run receipt
arh verify conclude <object>       # RESULT.md with one OUTCOME line, checked against the receipts
```

## Confirming on held-out data: freeze, then unseal

When the project declares `sealed_inputs` (an external validation sample, a
test split), no run can read them while you are still choosing. Once the
configuration is chosen without them:

```bash
arh freeze -n N iterations/iteration8/results/model/ iterations/iteration8/results/thresholds.json \
    iterations/iterationN/scripts/
arh submit iterations/iterationN/scripts/confirm.nf -n itN_confirm
```

`FREEZE.json` is written once and names every file the confirmation applies:
the model, the thresholds and emission rule, the feature list, the scripts.
Freeze everything that carries a decision, not only the model file. A run of
iteration N then reads the sealed inputs read-only, and `arh submit` refuses it
if any frozen file has changed. Every read is appended to `.arh/unseals.tsv` and
shown by `arh freeze list`, so how often the held-out data were used is on
record. Without a valid freeze the sealed paths are covered by empty mounts, and
a workflow, params file or script that names one is refused before it runs.

## Writing a workflow for `arh submit`

`arh submit` runs a Nextflow workflow that belongs to a claimed iteration with a
frozen pre-declaration, and blocks until Nextflow exits. A minimal workflow:

```nextflow
params.outdir = 'results'      // arh submit sets iterations/iterationN/results/<name>
params.inputs = '/absolute/path/to/a/declared/immutable/input'

process ANALYSE {
    cpus 4                     // optional; defaults come from .arh/config/site.md
    memory '16 GB'
    time '2h'
    publishDir params.outdir, mode: 'copy'

    input:
    path script

    output:
    path 'out/*'

    script:
    """
    mkdir -p out
    python3 ${script} --inputs ${params.inputs} --out out
    """
}

workflow {
    ANALYSE(channel.fromPath("${projectDir}/itN_01_analyse.py", checkIfExists: true))
}
```

- Every process runs in the pinned task image on the site's scheduler. It sees
  the project at its own absolute path (read-write), the `immutable_inputs` of
  `.arh/config/project.md` (read-only) and the task environment `runtime_prefix`
  (read-only; its `python3`, `bash` and `git` are on `PATH`). Nothing else is bound.
- Pass scripts in as `path` inputs, as above, so `-resume` notices when they change.
- Nextflow runs offline and in strict syntax: no plugin downloads, no Groovy
  `import`. `arh submit WORKFLOW.nf --lint` checks a workflow without running it.
- Evidence stays under the iteration: `logs/nextflow/<name>/attempt-*/`
  (`console.log`, `trace.tsv`, `run.json`) and `metadata/nextflow/<name>/work/`.
  A failed run prints the tail of its console log.
- Scientific packages: `arh env create NAME pkg=version ...` solves them once in
  the task image, locks them in `.arh/NAME-explicit.lock` and prints the prefix to
  call from a process (`<prefix>/bin/python`, `<prefix>/bin/Rscript`). A different
  package set is a new NAME. Do not build environments by hand.
- GPUs: give the process `label 'gpu'` (or `process_gpu`), or an `accelerator N`
  directive. It runs with `--nv`, and on Slurm goes to the site's `gpu_partition`
  with `--gres=gpu:N`. Never run GPU work by hand with `sbatch`.
- A second tool image: declare `image_<name>` and its `_sha256` in `site.md`, and
  give the process `label 'image_<name>'`. It runs in that image with the image's
  own `PATH`; the receipt and `trace.tsv` record which image each task used.
- Code from another iteration's `scripts/`: declare it under `imports =` in the
  pre-declaration's `arh-config` block. Its hash is frozen with the plan, and
  `arh submit` refuses a run in which it changed.
- Work that truly cannot go through `arh submit` is recorded at once:
  `arh note -n N --job JOBID 'what ran, where its output is'`. Without a note,
  nothing in the study says the work exists.

## Rules that are not negotiable

1. **Claim before you create.** `arh claim` is the only way to take an iteration
   number. The directory creation is the concurrency lock. Never `mkdir -p` an
   iteration by hand.

2. **Pre-declare before you run.** Complete the iteration README before any
   result exists; `arh gate predeclare` freezes its hash. If the design changes,
   create a **new iteration**.

3. **Append-only. Never rewrite an earlier conclusion.** A correction is a new
   iteration that records what the earlier one got wrong. Superseded evidence
   remains intact.

4. **Immutable inputs are immutable.** Bind them read-only in containers. All
   output stays under the project root. Use `arh guard` before writing.

5. **Pin every scientific tool.** Use the declared task image / `arh run` path.
   A tool that can silently change underneath a run is not reproducibly pinned.

6. **Required review comes from a different configured model family, unless the
   project says otherwise.** `arh ask` enforces this while
   `require_foreign_family = true` in `.arh/config/harnesses.md`, which is the
   default. Cross-family review reduces one source of correlated error; it is
   evidence, not proof or independent scientific validation. A project may set
   the key to `false` to accept an adversarial review from the producer's own
   family — a weaker check, because a model does not reliably catch its own
   reasoning errors. Each review records the value in force when it ran, so the
   setting never revalidates or invalidates a review already taken. The review
   terms in `.arh/config/harnesses.md` are bound to an iteration when it is
   claimed, so do not edit that file mid-iteration. If a change cannot wait (the
   verifier is unavailable, the review budget is too small), pass
   `arh ask --terms-changed 'what changed and why'`; without the reason the
   review does not count.

7. **Standing rules bind every conclusion.** They live in `rules/` and are
   enforced by `arh gate`.

8. **Record predictions, including wrong ones.** Do not revise a missed
   prediction after seeing the result.

9. **Web access follows the project.** When `.arh/config/harnesses.md` sets
   `web_access = deny` (a blinded replication, for example), do not search for,
   fetch or otherwise look up the results you are asked to produce.
   `harness/install.sh` turns the harness's web tools off, and `arh doctor`
   checks that they stay off.

10. **Durable knowledge goes in the project, never only in private memory.**
   A fact that outlives this session is written to the project's files and kept
   with the study: an operator directive, a data location, an external finding
   or tool behaviour a design depends on (`DIRECTIVES.md`), a silent failure mode
   with its assertion (`GOTCHAS.md`), the state of the work (`PROGRESS.md`). A
   harness's private memory (Claude Code auto-memory, a Codex memory, a chat
   history) is invisible to every other harness, to a second account's session and
   to the reviewer; it may hold a pointer to the project file, not the fact. A
   pitfall of a tool or of the cluster also goes in the `site_gotchas` file when
   one is configured and writable.

## Reporting

- Report the quantity that was pre-declared, even if another number looks nicer.
- A null result is an **upper bound** with its detection basis, not an absence.
- Anything without appropriate orthogonal validation is a **candidate**.
- Use causal language only when the design supports it.
- State the detection limit in the units of the estimand.
- Report negative-control behaviour and failed arms.

## When the operator challenges a result

Treat the challenge as the trigger for a **new iteration**, not an instruction
to edit the old one. Record the challenge as motivation. The operator is an
adversary in this protocol by design.

## A failed acceptance criterion is a result

When an acceptance criterion fails (an undocumented code, counts that do not
reconcile), do not stop and do not work around it inside the frozen design.
Report the failure as this iteration's result, have it reviewed and conclude it.
Then claim a new iteration whose pre-declaration states how the problem is
handled. Stop as blocked only when no iteration can proceed at all: missing data
or access, or a broken environment.

## Running unattended

A headless session (`claude -p`, `codex exec`, a batch driver) gets no completion
notices, and it ends as soon as its reply ends.

- Run `arh submit`, `arh ask` and `arh env create` in the foreground; they block
  until done. Never background them yourself and never end a reply to wait for
  one. A run longer than your harness lets a command live goes out with
  `arh submit WORKFLOW.nf -n NAME --detach`, which returns once the run holds its
  lock and survives the session; follow it with `arh wait -n N` and
  `arh status --running` (live submissions with their trace counts, reviews, and
  the scheduler state of noted jobs). A pending review is not a reason to end the
  session.
- `arh status` lists open iterations with who holds them and how long they have
  been idle. Every `arh` command on an iteration records itself in its lease and
  warns when another session holds it. Taking over an iteration an earlier session
  left is explicit: `arh lease take -n N --reason '...'`.
- On a new site, run `arh doctor --smoke` (and `--smoke gpu` if you will use GPUs)
  before the first iteration: it runs one task through the real scheduler and
  image. Run `arh inputs check` after declaring inputs and whenever they change;
  a truncated CRAM or VCF is caught by its missing end-of-file marker.
- `arh ask` exit 75: the provider refused on a usage or rate limit, or on
  authentication, and any `verifier_fallback` was already tried. No review round
  was spent. The reset time it prints is an upper bound, not a schedule: run the
  same command again after a bounded wait (for example 30 minutes) instead of
  sleeping until then.
- `arh ask`, `arh delegate` and `arh evoke` refuse to send a request that carries
  something shaped like a credential. Remove it from the file; never paste keys or
  tokens into a pre-declaration, report, task or note.
- `arh ask` exit 77: the provider refused the content. No round was spent, and
  waiting will not help. Any `verifier_fallback` was already tried; if none gave a
  review, record the refusal as what blocks the iteration.
- **Do not set `ARH_AGENT` yourself.** Whoever started this session already named the
  producer in `.arh/config/harnesses.md`, and that name may pin a model and an account
  (`claude_sonnet_main`) that your harness name (`claude`) would throw away. `arh claim`
  takes the configured producer, records what the session reported as `inferred_agent`,
  and warns when the two disagree. Only set `ARH_AGENT` if no producer is configured.

## Delegating implementation to another model

A project may name two agents instead of one: `orchestrator` plans, claims and
pre-declares; `executor` writes and runs the analysis. Both are harnesses in
`.arh/config/harnesses.md`. Run `arh delegate list` to see what is configured;
nothing is delegated unless a role is set.

```bash
arh delegate --role executor -n 4 --prompt task.md --dry-run   # inspect the request first
arh delegate --role executor -n 4 --prompt task.md
```

The request carries the frozen pre-declaration and your task. The response lands
in `iterations/iterationN/metadata/delegations/NNN-<role>/` with `request.md`,
`response.md` and a `run.json` recording the harness, model version, command and
hashes. A delegated response is a **draft**: it is not evidence until it has gone
through pinned execution, the gates and a cross-check, exactly like work you
wrote yourself. Delegation carries no family requirement — it is a division of
labour, not a second opinion. Review is still governed by `arh ask`.

## Optional external generators

External research systems are proposal engines, not protocol authorities. Read
`skills/evoke/SKILL.md` and run `arh evoke list` when a specialist generator
materially fits the iteration. Preview the bounded request with `--dry-run`;
never clone, install, enable or invoke a generator implicitly.

An evocation is stored under `metadata/evocations/` and cannot satisfy a
results gate. Adopt useful proposals through the ordinary pre-declaration,
pinned execution, cross-check and ledger path. Never send credentials, patient
identifiers or undeclared data, and never use an evoked generator in place of
the required `arh ask` review.

## Style

- Shell: `set -euo pipefail`, quote expansions, explicit paths.
- Scripts: `itN_NN_description.{sh,py}`, deterministic seeds, sorted inputs.
- Tabular data is real TSV; parse deliberately.
- Write outputs only under the iteration that produced them.

## Before you finish

Run `arh status`. Anything showing `ALTERED`, or a required review that is
missing/ineligible, is an unfinished protocol violation rather than a formatting
detail.

## Default coding skill — Ponytail

For coding, debugging, refactoring and dependency decisions, use Ponytail in
full mode by default. Read `skills/ponytail/SKILL.md` once when starting coding
work; reuse that context rather than reloading it every turn. Prefer existing
code, standard libraries and installed tools before adding implementation.

Explicit user requirements, validation, immutable-input protection and every
research gate above take precedence over brevity. “Stop ponytail” or “normal
mode” disables this coding preference for the session; it does not change the
research protocol.
