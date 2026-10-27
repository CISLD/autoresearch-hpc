# AutoResearch HPC — reference

The details `AGENTS.md` leaves out. Read the section you need when you need it.

## Re-examining a result: the verification track

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
When the project declares several sealed groups (`sealed_inputs_<group>`), name
the one the confirmation may read: `arh freeze -n N --unseal GROUP ...`; the
other groups stay covered.

## Writing a workflow for `arh submit`

`arh submit` runs a Nextflow workflow that belongs to a claimed iteration with a
frozen pre-declaration, and blocks until Nextflow exits. With
`task_project_access = ro` (the default for new projects) a task can write only
its iteration's `results/` and its own work directory; everything else in the
project is read-only inside it. Scripts already in `scripts/` when the plan is
frozen are frozen with it: changing one afterwards is a deviation the report must
name (or a new iteration, with `frozen_scripts = refuse`). `arh stop -n N` stops
the iteration's running submissions. A minimal workflow:

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
- `arh sessions -n N` names the agent sessions that ran `arh` commands on an
  iteration (from `metadata/activity.jsonl`: the agent process each ran under,
  found for any configured harness, and a session id your harness reports if
  `session_env` names one), any dispatched controller, and, when the project is a git repository
  recorded by Entire CLI, the `Entire-Checkpoint` of each commit that touched it.
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
labour, not a second opinion. Review is still governed by `arh ask`, and with
`orchestration = per-iteration` the verifier must differ in family from the
executor too.

## Per-iteration controllers

With `orchestration = per-iteration` in `.arh/config/harnesses.md`, the session
that talks to the operator is the **main controller**: it claims iterations and
runs `arh dispatch -n N --brief FILE`, which starts a fresh **iteration
controller** session that owns iteration N. Read `skills/dispatch/SKILL.md`.
The main controller reads hand-backs (`arh dispatch status`) and the ledger; it
does not change a dispatched iteration, and `arh` refuses if it tries. An
iteration controller finds its instructions in its prompt; it works only on its
own iteration and ends with `arh dispatch report`.

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

