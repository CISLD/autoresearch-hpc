# AutoResearch HPC — agent contract

You are working inside an **AutoResearch HPC** project. This file is the
harness-agnostic contract; Claude Code reads it through `CLAUDE.md`.

**If `arh` started you** to review, re-implement, adjudicate or carry out a
delegated task, your prompt is the whole task: skip the start below.

**Start with `arh context`.** It prints the current state from `PROGRESS.md`, the
open iterations, the directives in force (or where to read them in full: they are
binding) and an index of `GOTCHAS.md`. Open a gotcha entry, a `PROGRESS.md`
section or `skills/iterate/reference.md` when your task touches it, not by
default. Never reconstruct state from conversation history.

## The shape of the work

Work happens in numbered, **append-only** iterations under `iterations/`. One
iteration answers one question:

```text
iterations/iterationN/
  CLAIM.json  README.md (the pre-declaration)  PREDECLARATION.sha256
  scripts/  resources/  metadata/  logs/  results/report/iterationN_report.md
  CROSSCHECK_<role>_<harness>_<ts>.md   REVIEW_RESPONSE.md
```

## The loop

```bash
arh claim -t "the question"          # atomic; returns N (--continues M: another try at M's question)
arh new -n N                         # scaffold the pre-declaration; complete every section
arh gate predeclare -n N             # freezes it, and the scripts already in scripts/
arh submit iterations/iterationN/scripts/experiment.nf -n itN_01
arh ask --role adversary -n N        # cross-check from another model family
arh gate results -n N
arh ledger render && arh ledger check
```

If your harness resets the shell's directory, `export ARH_PROJECT=<study>`.
`skills/iterate/SKILL.md` walks one iteration; `skills/iterate/reference.md`
covers workflows for `arh submit`, held-out data (`arh freeze`), the
verification track, running unattended, delegation and dispatch.

A review is bound to the report and to every file under `results/`: write the
report's *Cross-check* section as a pointer before `arh ask`, and answer each
numbered finding by its id in `REVIEW_RESPONSE.md` at the iteration root
(`F2: rejected, because ...`; `arh gate results -n N --skeleton` lists them).
An `UNSOUND` verdict needs `Verdict: rebutted, because <reason>` (then
`arh ask --rebuttal -n N`; the gate passes only on `WITHDRAWN`) or
`Verdict: accepted`, which leaves the iteration unconcluded. Every number the
report states comes from a file under `results/`.

## Rules that are not negotiable

1. **Claim before you create.** Only `arh claim` takes an iteration number.
2. **Pre-declare before you run.** A changed design is a new iteration. Scripts
   already in `scripts/` at the freeze are part of the plan.
3. **Append-only.** A correction is a new iteration; superseded evidence stays.
4. **Immutable and sealed inputs are never written.** All output stays under the
   iteration that produced it.
5. **Pin every scientific tool.** Run through `arh submit`, `arh run` and
   `arh env create`; work that cannot is recorded at once with `arh note`.
6. **Review comes from another model family** unless `.arh/config/harnesses.md`
   says otherwise. Its terms are bound at claim: do not edit that file
   mid-iteration; if a change cannot wait, `arh ask --terms-changed 'why'`.
7. **Standing rules in `rules/` bind every conclusion.**
8. **Record predictions, including wrong ones.**
9. **With `web_access = deny`, do not look up the results you are to produce.**
10. **Durable knowledge goes in the project, never only in private memory:**
    directives and data locations in `DIRECTIVES.md`, silent failure modes with
    their assertion in `GOTCHAS.md`, the state of the work in `PROGRESS.md`'s
    `## Current state`, a concluded finding with `arh memory add -n N`.
    A harness's private memory may hold a pointer, not the fact.
11. **Do not set `ARH_AGENT` yourself**; the producer is configured.

## Reporting

- Report the pre-declared quantity, even if another number looks nicer.
- A null result is an upper bound with its detection basis; state the detection
  limit in the estimand's units.
- Anything without orthogonal validation is a candidate; causal language only
  when the design supports it.
- Report negative controls, failed arms and missed predictions.

An operator's challenge is the motivation for a new iteration, not an edit. A
failed acceptance criterion is this iteration's result: report, review and
conclude it, then pre-declare the handling in a new iteration. Stop as blocked
only when no iteration can proceed (missing data or access, broken environment).

## Commands that wait

`arh submit`, `arh ask` and `arh env create` block until done: run them in the
foreground and do not end a reply to wait. A run longer than your harness allows
goes out with `--detach` and is followed with `arh wait -n N`. `arh ask` exit 75
(limit, login or timeout) and 77 (content refused) spend no review round; after
75 retry after a bounded wait, not at the reset time the provider names.

## Before you finish

Run `arh status`. An `ALTERED` plan or a missing or ineligible required review is
an unfinished protocol violation. Update `## Current state` in `PROGRESS.md`.

## Project-specific instructions

Instructions for this study only go between the two markers below. `arh migrate`
refreshes the rest of this file from the framework and keeps what is between them.

<!-- arh:project:begin -->
<!-- arh:project:end -->
