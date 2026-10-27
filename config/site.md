# Site configuration

Everything about **this machine or cluster**: how jobs are submitted, how tools
are containerised, where images live. Nothing here is scientific — swap this one
file to move a project to a different cluster.

Settings live in the fenced `arh-config` block below as `key = value`. Text
outside the block is documentation and is ignored.

## Scheduler

`scheduler` selects how `arh submit` launches work.

| value | submit | status | notes |
|---|---|---|---|
| `slurm` | Nextflow → Slurm | `squeue` | the usual HPC case |
| `pbs`   | Nextflow → PBS | `qstat` | best-effort |
| `local` | Nextflow local | Nextflow trace | laptops, CI, the test suite |

`arh init` detects Slurm/PBS when their client commands are present; override it
with `--scheduler` or edit this file. Slurm resource keys become Nextflow process
settings or cluster options.

`arh init` only tests whether a scheduler's client commands exist — it cannot know
which queue you should use or what that queue permits. Run `arh site detect` for
that: it lists the queues visible to you with their walltime, core, memory and
generic-resource limits, reports the accounts and QOS you can charge to, and prints
a proposed block to paste below. It never writes this file, because choosing a queue
is a policy decision. Run inside a project it also checks the settings already here
against the machine, which catches a queue name that does not exist or a request
larger than any node in it before a job is rejected.

## Containers

`container_runtime` records the site command available for container execution.
`arh init` detects `singularity` or `apptainer` when present. Scientific tasks
must still use the configured digest-pinned runtime image.

| value | behaviour |
|---|---|
| `apptainer` / `singularity` | clean task execution with project RW and immutable inputs RO |
| `docker` | local/container development with the same bind policy |
| `none` | direct host execution — smoke tests only, not reproducible research |

Declare auxiliary images as `image_<name> = <path or URI>`, then refer to them
by `<name>`. A bare name resolves under `image_dir`.

A workflow process runs in a declared image instead of the task image when it
carries the label `image_<name>` (`label 'image_vg'`). The image must be a local
file with `image_<name>_sha256`; `arh submit` checks the digest, gives the
process the image's own `PATH` (read from the image, or `image_<name>_path`), and
records the image and digest in the run receipt and in `trace.tsv`.

## GPUs

A process labelled `gpu` (or nf-core's `process_gpu`), or one with an
`accelerator` directive, runs with `--nv`. On Slurm it is sent to
`gpu_partition` (default: `slurm_partition`) with `--gres=gpu[:gpu_type]:N`, N
being the accelerator count (default 1). `gpu_constraint` becomes
`--constraint`, and `gpu_extra` is appended as is. Use the type or the
constraint to keep a task off cards with too little memory for it.

## Shared knowledge

`site_gotchas` names a Markdown file of pitfalls that belong to this machine
rather than to one study: a tool release that mis-handles a flag, a scheduler
quirk, a truncated shared input. Every project on the site that points at the
same file reads it, so a lesson costs one project instead of each of them.
`arh ask` and `arh delegate` point reviewers and executors at it, `arh claim`
records its hash, and `arh doctor` checks that it is readable. Leave it empty
when there is no shared file.

```arh-config
scheduler         = local
container_runtime = singularity

# Host controller. `arh init --bootstrap` can populate this automatically.
nextflow_prefix =
# Task container. scripts/setup-runtime.sh records its digest.
runtime_image =
runtime_sha256 =
runtime_prefix =
nextflow_version = 26.04.6
# HTML report and timeline per submission: html, gzip or none. They are ~1.9 MB a run;
# trace.tsv and the run receipt are always kept.
nextflow_reports = html
# Run when Nextflow exits, attached or detached, with ARH_RUN_EXIT, ARH_RUN_NAME, ARH_RUN_ATTEMPT,
# ARH_RUN_OWNER and ARH_RUN_SIGNAL set, e.g. a mail or a file a cron watcher reads. Empty: nothing.
on_exit =
# Retry a failed task up to this many times (0: the first failure stops the run). For sites where
# tasks fail on cluster events; every retry stays in trace.tsv and the receipt records the setting.
task_retries = 0
# arh status --running marks a run STARVED when its tasks wait in the queue and none has started or
# finished for this many hours.
starve_hours = 6

# --- SLURM ---------------------------------------------------------------
slurm_partition   =
slurm_account     =
slurm_time        = 01:00:00
slurm_cpus        = 1
slurm_mem         = 4G
slurm_extra       =

# --- GPUs (processes labelled gpu/process_gpu, or with accelerator) -----
gpu_partition     =
gpu_type          =
gpu_constraint    =
gpu_extra         =

# --- PBS -----------------------------------------------------------------
pbs_queue         =

# --- containers ----------------------------------------------------------
image_dir         = .arh/images
# image_samtools  = /opt/images/samtools_1.21.sif
# image_samtools_sha256 = <sha256 of that file>
# image_python    = docker://python@sha256:<64 lowercase hexadecimal digits>

extra_binds       =

# --- shared knowledge ----------------------------------------------------
site_gotchas      =
```

Non-smoke runs require declared content identity. Local image files use
`image_<name>_sha256`; remote references require `@sha256:...`. Changing a local
image without changing its declared digest fails before execution.
