# Validation scope

## Current baseline

A run on 2026-10-15 at commit `8aa7541` (clean worktrees) passed:

| Suite | Command | Result |
|---|---|---|
| Core protocol checks | `test/run_tests.sh` | 173 / 173 |
| Boundary regressions | `ARH_TEST_GPU=1 python3 test/test_hardening.py` | 108 / 108 (1 network case skipped) |
| Protocol conformance matrix | `python3 test/conformance.py --site SITE` | 18 / 18 (E1–E17), locally (xfs) and on Slurm with the project on CephFS |
| Deterministic synthetic example | `bash examples/mean-shift/check.sh` | OK |

The Slurm run raced 12 claims from 4 tasks on two compute nodes
(`srun -p priority -N 2 --ntasks-per-node 2`), all distinct; the cluster had no more free CPUs that day.
The local and test sites were a local executor with Nextflow 26.04.6 and Singularity-compatible
Apptainer, and an NVIDIA TITAN RTX on the host.

Earlier baselines: commit `1d98801` passed 173 / 173, 98 / 98 and 14 / 14 (E1–E13) on 2026-10-06; the
v0.3.0 release (commit `77b7cfc`) passed 158 / 158, 70 / 70 and 12 / 12 on 2026-09-21, and its matrix
again at the tag on 2026-09-24, locally and on Slurm with 96 claims raced from four nodes.

## Protocol conformance matrix

`test/conformance.py` injects one violation per protocol boundary into a scratch project
and checks the specified refusal. A stand-in reviewer answers `arh ask`, so no model is
called. The cases that run real tasks (E5b, E6, E9, E12, E13) need `--site`; without it
they are reported as skipped. The result is written as JSON with the commit it ran on, marked
`-dirty` when the checkout had uncommitted changes.

| ID | Injected violation | Specified behaviour |
|---|---|---|
| E1 | pre-declaration template left unfilled (placeholders remain) | predeclare gate refuses |
| E2 | result written before the plan is frozen | predeclare gate refuses |
| E3 | frozen plan edited after the result | results gate refuses the changed hash |
| E4 | concurrent claims | distinct iteration numbers |
| E5 | write to a declared immutable input through `arh` | refused |
| E5b | task writes to a declared immutable input | refused by the read-only mount |
| E6 | task exits with an error | failure reported; receipt and logs kept |
| E7 | review requested from the producer's own family | refused by default |
| E8 | evidence changed after a review | review becomes ineligible |
| E9 | submission interrupted while its task runs | signal recorded; launch lock released; scheduler job gone |
| E10 | fresh shell with no chat history | status, next and the ledger name each iteration's state |
| E11 | review configuration changed after the claim | review refused unless the reason is recorded |
| E12 | held-out data read before a freeze | a workflow naming the sealed path is refused; a task building the path sees an empty mount; after `arh freeze` the confirmation reads it and the read is logged |
| E13 | frozen decision changed before the confirmation | `arh submit` refuses the run |
| E14 | every required heading present, every section empty | predeclare gate refuses |
| E15 | results moved aside, freeze file deleted, plan edited to fit and frozen again | second freeze refused; a hand-made freeze file fails the results gate |
| E16 | the only review returns `UNSOUND` | results gate refuses until a reviewer withdraws it on a reasoned rebuttal; refused while the rebuttal is unjudged, when the reviewer maintains it, and after `Verdict: accepted` |
| E18 | review policy relaxed in `project.md` after the claim | the results gate still applies the policy recorded at claim |
| E17 | a concluded iteration's directory deleted and the ledger re-rendered | `arh ledger check` fails: the claim registry still lists it |

E14–E17 come from an external review of v0.3.0 (2026-10-13), which found that v0.3.0
accepted all four: an empty pre-declaration froze, an iteration whose only review said
`UNSOUND` concluded, a plan rewritten after the result was frozen again in three file
operations, and a deleted iteration left `arh ledger check` passing. A first fix accepted any
reasoned rebuttal of an `UNSOUND` verdict, so the producer still judged its own case; E16 now
requires the reviewer to withdraw the verdict, and E18 checks that a producer cannot relax the
review policy for an iteration already claimed. E1 in v0.3.0 tested
unfilled template placeholders, not an empty field, although this table described it as one.

On 2026-09-21 all twelve cases passed on a local site, and again on Slurm with the
scratch project on a shared CephFS directory. With
`--claim-launcher 'srun -N 4 --ntasks-per-node 8'`, 32 tasks on four compute nodes made
96 claims against one CephFS project and received 96 distinct iteration numbers. CI runs
the matrix on every push with a local site and keeps `conformance.json` as an artifact.

The network-dependent regression (`test_env_create_locks_and_is_immutable`)
solves real packages and needs `ARH_TEST_NETWORK=1`; CI runs it with network
enabled. Without a configured site and network, the boundary suite skips eight
integration cases while retaining all generator-evocation checks.

Six core checks — `arh doctor` on a fresh project, the three `arh submit`
execution checks and the Singularity-runtime check — require a site whose
`runtime_image`, `runtime_sha256` and `nextflow_prefix` are actually populated.
Pointing `ARH_TEST_SITE` at the repository's own `config/site.md` template, which
leaves those empty, fails them. This is a property of the site, not of the code.

## Field checks of the post-0.3.0 mechanisms (2026-10-06)

These were run by hand on the maintainers' Slurm cluster, beyond the suites above:

- **GPU.** A task labelled `gpu` saw the host's TITAN RTX through `--nv` on a local
  executor (`test_gpu_process_runs_with_nv` with `ARH_TEST_GPU=1`, and
  `arh doctor --smoke gpu`). On Slurm, a task labelled `gpu` with `accelerator 1` was
  sent to the `gpu` partition with `--gres=gpu:1`; it waited behind other users' GPU jobs
  and had not started when this page was written, so no Slurm GPU task has yet been
  observed running.
- **A second image.** A process labelled `image_seqkit` ran on Slurm in a pulled
  `seqkit 2.9.0` biocontainer with the image's own `PATH`; `trace.tsv` recorded the image.
  The first attempt failed because Nextflow needs `ps` in every container and the
  declared image's `PATH` hid the task environment's; the task environment's `bin/` is
  now appended after the image's own.
- **Detach.** `arh submit --detach` returned in 1.1 s on Slurm, and `arh status --running`
  showed the submission's trace counts while it ran.
- **Input integrity.** `arh inputs check` on a field study's ONT data flagged the CRAM
  whose truncation had silently cost a truth set (no CRAM end-of-file container) and
  passed the CRAM and VCF of the re-run that replaced it.
- **Smoke test.** `arh doctor --smoke` with an immutable input and a sealed input inside
  it reported the input read-only and the sealed path hidden; it also caught a false
  positive in its own first version (`[ -s ]` is true for an empty directory).
- **Report numbers.** On eleven concluded reports of the field study, the results gate's
  number check left 0 to 22 of 65 to 178 numbers unmatched per report, mostly values
  computed in the prose (differences, interval half-widths) or quoted from other
  iterations.

## Earlier runs

Local validation on 2026-09-10 passed 137 core protocol checks and 31 boundary
regressions. After the field fixes listed in the [changelog](../CHANGELOG.md), a
re-run on 2026-09-11 passed 137/137 core checks and 37/37 boundary regressions.
The counts have grown since because regressions were added, not because coverage
was restated.

Observed behaviors across those runs included native local success, cached
resume, real Slurm success, deliberate task failure propagated to the
controller, and rejection of a write to an immutable input inside a compute-node
container. The real-Slurm and cache-reuse observations come from those earlier
runs; the 2026-09-17 baseline above was a local-executor run and does not
re-establish them.

One bounded Claude review returned **QUALIFIED**. Five predeclared follow-up
probes passed: final-adapter local success, Slurm success, Slurm failure,
concurrent review refusal, and confirmation of the packaged Nextflow jar.
These probes were authored by the producing family, not independently rerun
by the reviewer. The original review remains unchanged.

## Retained limits

Remaining limits include mutable host environment storage, controller writes
outside task-container protections, PBS execution beyond the conformance matrix,
GPU tasks on a scheduler (routed but not yet observed running), and model overhead
beyond submitted prompt/output limits. Sealed inputs are hidden from tasks, not from
the agent's own shell, and declared inputs are checked for truncation, not hashed. This is a cooperative
research protocol, not containment for hostile workflow code or a scientific
truth guarantee.

The original append-only audit records stay in the maintainer's local study.
They include machine-specific paths and runtime data and are not included in
this source release. This page is a publication summary, not a replacement for
the original evidence. GitHub Actions runs the suite on every push; that
validation becomes independently visible once the repository is public.
