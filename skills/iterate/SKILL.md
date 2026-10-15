---
name: iterate
description: Run one complete AutoResearch HPC iteration — claim a number, pre-declare the design before any result exists, execute, cross-check with a foreign harness, and record the outcome in the ledger.
---

# Run an iteration

One iteration answers **one question**. If the question becomes “and also…”,
that is normally another iteration.

## 0. Read what the project already knows

`PROGRESS.md` (state), `DIRECTIVES.md` (operator directives, data locations,
external findings) and `GOTCHAS.md` (silent failure modes), plus the site's
`site_gotchas` file when `.arh/config/site.md` names one. Whatever you learn that
outlives this session goes back into those files, never only into a harness's
private memory.

## 1. Claim

```bash
arh claim -t "the question, stated as a question"
```

This is the only supported way to take an iteration number.

## 2. Pre-declare

```bash
arh new -n N
```

Complete every section of `iterations/iterationN/README.md`, then freeze it:

```bash
arh gate predeclare -n N
```

The frozen declaration is immutable. A changed design is a new iteration.

## 3. Execute

Keep scripts under the producing iteration and pin scientific tools:

```bash
arh run samtools -- samtools view -c input.bam
arh submit iterations/iterationN/scripts/experiment.nf -n itN_01
```

Scientific packages come from `arh env create NAME pkg=version ...`, solved once in
the task image and locked. `arh submit WORKFLOW.nf --lint` checks a workflow before
it runs; `AGENTS.md` shows a minimal one.

A confirmation on held-out data (`sealed_inputs`) first freezes every artefact
carrying a decision: `arh freeze -n N MODEL THRESHOLDS SCRIPTS...`. Only then can
its runs read the sealed paths, and each read is recorded (`arh freeze list`).

GPU work gets `label 'gpu'`, a second tool image `label 'image_<name>'`, and code
from another iteration is declared under `imports =` in the pre-declaration. Work
that cannot go through `arh submit` is recorded at once with `arh note`.

Check acceptance criteria before interpretation. A failed criterion is this
iteration's result: report and conclude it, then pre-declare the handling in a new
iteration. It is not a reason to stop.

## 4. Report

Write `results/report/iterationN_report.md`. Report the pre-declared quantity,
negative-control behaviour, detection limit and missed predictions.

## 5. Cross-check

```bash
arh ask --role adversary -n N
arh ask --role estimand-auditor -n N
```

Evaluate findings on their merits. A verdict is evidence, not a ruling.

`arh ask` blocks until the review is written; stay in the session until it returns.
Exit 75 (usage or rate limit, authentication) and exit 77 (the provider refused the
content) spend no review round. After 75, wait for the stated reset and run it again;
after 77, the configured fallback verifiers have already been tried.

**Where to record it.** A review is bound to the report's sha256 and to every
file under `results/`. Editing the report, or adding a file under `results/`,
after the review makes it ineligible. So:

- write the report's *Cross-check* section before `arh ask`, as a pointer;
- put your evaluation in `iterations/iterationN/REVIEW_RESPONSE.md` — at the
  iteration root, outside `results/`, and not named `CROSSCHECK_*` (that glob
  counts review attempts);
- answer every numbered finding by its id with a decision and the reason
  (`F1: accepted ...`, `F2: rejected, because ...`); `arh gate results -n N
  --skeleton` lists them, and the gate fails while one is unanswered;
- answer an `UNSOUND` verdict with `Verdict: rebutted, because <reason>`, or
  `Verdict: accepted` and leave the iteration unconcluded; the gate fails until
  every `UNSOUND` review is rebutted, and the correction of an accepted one is a
  new iteration;
- if a finding needs new computation, do it through `arh verify`, not by
  changing the iteration, and append the outcome to the response file.

Every number the report states should be in a file under `results/`; the
results gate lists those that are not.

## 6. Conclude

```bash
arh gate results -n N
arh ledger render
arh ledger check
```

Record what the iteration established, its strongest limit and what it
supersedes. Never edit an older conclusion to make history look cleaner.
