<p align="center">
  <img src="docs/assets/banner.png" alt="autoresearch-hpc — auditable AI-assisted research on HPC. An agent pre-declares an experiment (arh claim, arh new, arh gate predeclare), executes it through Nextflow, Slurm/PBS and Apptainer, then reviews and records it: append-only, reproducible, auditable." width="100%">
</p>

<p align="center">
  <a href="https://github.com/HudoGriz/autoresearch-hpc/actions/workflows/test.yml"><img alt="Tests" src="https://github.com/HudoGriz/autoresearch-hpc/actions/workflows/test.yml/badge.svg"></a>
  <a href="docs/validation.md"><img alt="Status: experimental" src="https://img.shields.io/badge/status-experimental-orange"></a>
  <a href="PROTOCOL.md"><img alt="Protocol 0.3.0" src="https://img.shields.io/badge/protocol-0.3.0-blue"></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-green"></a>
  <a href="https://doi.org/10.5281/zenodo.22937869"><img alt="DOI" src="https://zenodo.org/badge/DOI/10.5281/zenodo.22937869.svg"></a>
</p>

<p align="center">
  <strong>Declare the question. Freeze the plan. Run it on your cluster. Critique the result. Keep the evidence.</strong>
</p>

<p align="center">
  <a href="#setup">Setup</a> ·
  <a href="#run-one-declared-experiment">Run an experiment</a> ·
  <a href="#the-research-loop">Research loop</a> ·
  <a href="#skills-and-cli">Skills + CLI</a> ·
  <a href="PROTOCOL.md">Protocol</a> ·
  <a href="docs/validation.md">Validation</a>
</p>

---

AutoResearch HPC (`arh`) is a research-protocol layer for **AI-assisted experimentation on infrastructure you already own**. A coding agent can propose and implement an experiment; `arh` makes the boundaries mechanical — claim an iteration, pre-declare it before results exist, execute it through the configured HPC stack, preserve failures, have a model from another family review it, and write the outcome into an append-only record.

It is **not** a scheduler, a workflow engine or an autonomous research daemon. It sits on top of the stack you already run and makes the *research process* inspectable.

> [!NOTE]
> **Two layers, one workflow.** **Skills** tell an agent *how to conduct the research task*; the **`arh` CLI** enforces the parts that should not depend on an agent remembering the rules.

## Setup

You need a login node with a scheduler (Slurm, PBS, or neither for local runs) and Apptainer or Singularity. Nothing else — no pre-installed Conda or micromamba, and nothing is written to your shell configuration.

```bash
git clone https://github.com/HudoGriz/autoresearch-hpc.git
export PATH="$PWD/autoresearch-hpc/bin:$PATH"

arh init /shared/my-study --bootstrap   # detect the scheduler, build the pinned Nextflow environment
cd /shared/my-study
arh site detect                         # list your queues and their limits, propose site.md values
arh doctor                              # what is still missing, if anything
```

`arh init` detects Slurm/PBS and the available Singularity/Apptainer command; `--bootstrap` also prepares the pinned host-side Nextflow/Python environment. `arh site detect` fills the gap `arh init` cannot — which queue to use and what it permits. It prints a block for you to paste and never writes `site.md` itself, because choosing a queue is a policy decision. Run inside a project it also checks existing settings against the machine, catching a missing queue or an oversized request before a job is rejected.

When `arh doctor` prints `Ready`, [run your first iteration](#run-one-declared-experiment).

**Or hand the setup to your coding agent.** Give Claude Code, Codex, OpenCode, Cursor or Copilot this repository and ask:

> Set up AutoResearch HPC for this project. Inspect the repository instructions first, detect my scheduler and container runtime, run the automatic bootstrap, configure the harness integration, then run `arh doctor` and resolve the required setup checks. Do not modify the scientific project or data beyond what AutoResearch HPC setup requires.

The repository ships `AGENTS.md`, reusable skills and harness adapters, so the agent can follow its own setup path.

Air-gapped clusters, staging micromamba or the task image yourself, and sharing environments between projects are covered in [HPC execution](docs/hpc-execution.md#fast-setup).

Project state lives under `.arh/`:

```text
.arh/config/site.md        scheduler, resources, runtime and shared paths
.arh/config/project.md     immutable inputs and standing project rules
.arh/config/harnesses.md   producer / verifier harnesses and model families
.arh/config/generators.md  optional external research generators; disabled by default
```

> [!TIP]
> `arh` finds the study by walking up from the working directory. Agent harnesses often reset the shell's directory between commands, so `export ARH_PROJECT=/shared/my-study` to make every command resolve the study from anywhere.

## Run one declared experiment

```bash
N=$(arh claim -t "Does the proposed method improve the declared metric?")
arh new -n "$N"

# Complete iterations/iterationN/README.md before any result exists.
arh gate predeclare -n "$N"

arh env create analysis python=3.12 numpy=2.1   # pinned, locked, replayable
arh submit "iterations/iteration${N}/scripts/experiment.nf" -n experiment
arh wait -n "$N"                                # block until submissions and reviews finish

# Write results/report/iterationN_report.md.
arh ask --role adversary -n "$N"
arh gate results -n "$N"
arh ledger render && arh ledger check
```

Or hand the workflow to a configured agent and ask it to **use the Iterate skill** for one research question. The skill describes the procedure; the CLI still supplies the enforcement.

To resume without conversation history:

```bash
arh status
arh next
arh context -n N
```

`PROGRESS.md` inside the study is the authoritative project state. A project should be resumable cold from what is on disk rather than from an old chat transcript.

What outlives a session is written into the study as well: `DIRECTIVES.md` holds the operator's directives, data locations and external findings, and `GOTCHAS.md` the failure modes that produce plausible output. Agents write there, not to a harness's private memory, which no other harness, account or reviewer can read. A site can share one `site_gotchas` file across all of its projects.

## The research loop

```mermaid
flowchart LR
    Q["Research question"] --> D["1 · Pre-declare"]
    D --> E["2 · Execute"]
    E --> R["3 · Review & record"]
    R -. "next question" .-> Q
```

| Phase | What happens | Core interface | Durable evidence |
|---|---|---|---|
| **1 · Pre-declare** | Claim one question, define the estimand, controls, detection limit and acceptance criteria, then freeze the plan once | `arh claim` · `arh new` · `arh gate predeclare` | `CLAIM.json` · `README.md` · `PREDECLARATION.sha256` · `.arh/freezes.tsv` |
| **2 · Execute** | Run the declared workflow with pinned scientific tooling on the configured compute backend | `arh env` · `arh submit` · `arh run` · `arh wait` | scripts · workflow metadata · run receipts · logs · results |
| **3 · Review & record** | Report the declared quantity, cross-check it, answer every numbered finding and rebut or accept an `UNSOUND` verdict, gate the result and update the project record | `arh ask` · `arh gate results` · `arh ledger` | report · cross-check record · review response · `PROGRESS.md` |

Phase 2 runs on infrastructure you already know:

```text
Nextflow controller  →  Slurm / PBS / local  →  Singularity / Apptainer tasks
```

The controller stays on the host so it can see the site's scheduler. Scientific dependencies run in the declared task image; shared paths and site policy live in configuration, not inside the workflow. GPU processes (`label 'gpu'`), processes in a second pinned image (`label 'image_<name>'`) and verifications (`arh verify run`) take the same path and get the same receipt; work that cannot is recorded with `arh note`.

## What gets recorded

```text
my-study/
├── PROGRESS.md                      authoritative resume point / ledger
├── AGENTS.md                        harness-agnostic agent contract
├── DIRECTIVES.md                    operator directives, data inventory, external findings
├── GOTCHAS.md                       silent failure modes, each with an assertion
├── .arh/config/                     site, project and harness settings
├── .arh/registry.tsv · freezes.tsv  every claim, and every freeze in a hash chain
├── rules/                           standing research rules
├── iterations/
│   └── iterationN/
│       ├── CLAIM.json
│       ├── README.md                pre-declaration written before results
│       ├── PREDECLARATION.sha256    frozen declaration hash
│       ├── FREEZE.json              decisions a confirmation applies, frozen before it reads sealed data
│       ├── scripts/  resources/  metadata/
│       ├── results/  logs/          results, run receipts, traces
│       ├── CROSSCHECK_*.md          foreign-family reviews
│       └── REVIEW_RESPONSE.md       what was done about each finding and each UNSOUND verdict
└── verification/                    re-examinations of existing results
```

Failed attempts, nulls, killed controls and superseded conclusions stay visible. A correction becomes a **new iteration**; the old evidence is not rewritten to make the history cleaner.

## Skills and CLI

**Skills are agent playbooks** — how to approach a research action and which checks matter. **`arh` commands are deterministic operations** — they create state, freeze declarations, launch execution, validate gates and maintain the record.

| Skill / workflow | What the agent is being asked to do | Main `arh` machinery underneath |
|---|---|---|
| **[Iterate](skills/iterate/SKILL.md)** | Run one complete research iteration | `claim` → `new` → `gate predeclare` → `submit/run` → `ask` → `gate results` → `ledger` |
| **[Cross-check](skills/cross-check/SKILL.md)** | Critique an iteration from a defined role | `arh ask --role ...` |
| **[Verify](skills/verify/SKILL.md)** | Re-examine an existing result without rewriting history | `arh verify new/gate/run/conclude` |
| **[Arms](skills/arms/SKILL.md)** | Track parallel sub-analyses with explicit fates | `arh arm ...` |
| **[Replicate](skills/replicate/SKILL.md)** | Reimplement from a frozen specification, blind to the original code | `arh dag ...` · `arh replicate ...` |
| **[Ledger](skills/ledger/SKILL.md)** | Maintain and check the authoritative research record | `arh ledger render/check` |
| **[Evoke](skills/evoke/SKILL.md)** | Select and invoke a configured specialist generator as an advisory proposal engine | `arh evoke ...` |
| **[Ponytail](skills/ponytail/SKILL.md)** | Coding, debugging, refactoring and dependency choices | coding guidance; not a protocol gate |

`harness/install.sh` copies all eight into a project. For **Claude Code** they land in `.claude/skills/` and appear as `/iterate`, `/cross-check`, `/verify`, `/arms`, `/replicate`, `/ledger`, `/evoke` and `/ponytail`; Codex and OpenCode read the same contract through their adapters. The portable source of truth remains `skills/` and `AGENTS.md`.

The separation matters: an agent may choose to *use the Iterate skill*, but it is `arh gate predeclare` that refuses a late or altered pre-declaration.

## Beyond the basic loop

The diagram above is a research loop, not the discovery DAG.

```bash
arh arm new ...             # parallel sub-analysis inside one iteration
arh verify new OBJECT       # re-examine an existing result
arh dag init -n N           # reconstruct the discovery path, inputs to claim
arh dag freeze -n N         # freeze that specification
arh replicate run ...       # blind reimplementation from the frozen DAG
arh evoke list              # optional specialist generators available at this site
arh freeze -n N PATH...     # freeze a confirmation's decisions; only then may it read sealed inputs
arh doctor --smoke [gpu]    # one real task through the scheduler and image: what can it see?
arh inputs check            # are the declared CRAM/BAM/VCF inputs whole?
arh submit WF.nf --detach   # a run that outlives the session; arh status --running follows it
```

Held-out data can be declared as `sealed_inputs`. Until an iteration freezes the artefacts its confirmation applies (model, thresholds, decision rules, scripts), its runs see empty mounts in place of the sealed paths, and a workflow that names one is refused. Every read after the freeze is logged, so how many times the held-out data were used is part of the record.

Disagreement between replicators is treated as useful evidence; agreement is not promoted to scientific confirmation by majority vote.

External generators are invoked, not bundled. Biomni, AI Scientist v2 and
Agent Laboratory have first-class registry entries, all disabled by default.
Their responses stay advisory until selected work passes the ordinary
pre-declaration, pinned execution and review path. See
[External generators](docs/external-generators.md).

## Why this layer exists

| Existing component | Keep using it for | AutoResearch HPC adds |
|---|---|---|
| **Nextflow** | scheduling, workflow execution, caching | declared iterations and iteration-owned evidence |
| **Slurm / PBS / local** | compute allocation | a portable execution target rather than a new scheduler |
| **Singularity / Apptainer** | scientific environments | pinned task execution tied to the record |
| **Claude / Codex / OpenCode** | implementation and critique | harness-portable rules, bounded review and explicit model-family provenance |
| **Biomni / AI Scientist v2 / Agent Laboratory** | optional specialist generation | a bounded request, retained invocation receipt and an advisory-only output boundary |

The framework does **not** treat model agreement as scientific truth. Cross-family critique is evidence to assess, not orthogonal validation. Claims still need whatever independent scientific validation their domain requires.

## Validation and boundaries

AutoResearch HPC is **experimental and pre-1.0**. On 2026-10-06 the suite passed **173 / 173 core protocol checks** and **98 boundary regressions** against a configured local site, and the **protocol conformance matrix** (`test/conformance.py`, thirteen injected violations) passed in full on a local site and on Slurm with the project on shared CephFS; the v0.3.0 release passed its eleven-scenario matrix on Slurm with claims raced from four compute nodes. Internal field deployment exposed review, submission and provenance defects, now represented by regression tests.

```bash
# ARH_TEST_SITE must point at a site.md with runtime_image, runtime_sha256 and
# nextflow_prefix populated — the template in config/ leaves them empty.
export ARH_TEST_SITE=/absolute/path/to/configured/local/site.md
test/run_tests.sh
python3 test/test_hardening.py
python3 test/conformance.py --site "$ARH_TEST_SITE"   # E1-E13; writes conformance.json
bash examples/mean-shift/check.sh
```

This is a cooperative research-integrity system, not a hostile-code sandbox or a trusted timestamp authority. Local hashes detect later changes; they do not prove temporal priority against an actor who controls the filesystem. External model services receive the context supplied to them, so local execution does not imply air-gapped inference.

[Tested behavior and retained limitations →](docs/validation.md)

## Documentation

| | |
|---|---|
| **Protocol** | [Normative protocol v0.3.0](PROTOCOL.md) |
| **Agent contract** | [AGENTS.md](AGENTS.md) |
| **HPC execution** | [Nextflow, schedulers, containers, receipts and stopping a run](docs/hpc-execution.md) |
| **Skills & model budget** | [Skills, harnesses and bounded review](docs/skills-and-token-budget.md) |
| **External generators** | [Select, configure and safely evoke specialist research systems](docs/external-generators.md) |
| **Unattended agents** | [Running producer and reviewer sessions headless](docs/headless.md) |
| **Validation** | [Tested behavior and limitations](docs/validation.md) |
| **Related work** | [What this composes with, and what it is not](docs/related-work.md) |
| **Migration / hardening** | [`arh migrate` for 0.1 studies, and implementation notes](docs/migration-hardening.md) |
| **Changes** | [CHANGELOG.md](CHANGELOG.md) |
| **Contributing** | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Cite this software

Each release is archived on Zenodo. Cite the version you actually ran.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22937869.svg)](https://doi.org/10.5281/zenodo.22937869)

| | DOI |
|---|---|
| **This project**, any version | [`10.5281/zenodo.22937869`](https://doi.org/10.5281/zenodo.22937869) |
| **v0.3.0** specifically | [`10.5281/zenodo.22937870`](https://doi.org/10.5281/zenodo.22937870) |

The concept DOI above always resolves to the latest release; the version DOI
pins one. [`CITATION.cff`](CITATION.cff) carries the same metadata in a form
GitHub's "Cite this repository" button and most reference managers can read.

```bibtex
@software{autoresearch_hpc,
  title   = {AutoResearch HPC: an auditable protocol for AI-assisted research on HPC},
  author  = {{AutoResearch HPC contributors}},
  version = {0.3.0},
  year    = {2026},
  doi     = {10.5281/zenodo.22937869},
  url     = {https://github.com/HudoGriz/autoresearch-hpc}
}
```

## Built on existing work

AutoResearch HPC is an independent project. Two upstream sources are vendored, pinned to an upstream commit and recorded with their licences under [`third_party/`](third_party/):

- **[Ponytail](https://github.com/DietrichGebert/ponytail)** (MIT) — the default coding guidance in [`skills/ponytail/`](skills/ponytail/SKILL.md), used unmodified. No upstream hooks, MCP server or auxiliary skills are installed.
- **[ARIS](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep)** — one review rubric, adapted into the [`adversary` cross-check role](skills/cross-check/roles/adversary.md). The upstream multi-round orchestration is not installed.

Beyond the execution stack in [Why this layer exists](#why-this-layer-exists), it depends on rather than reimplements [micromamba](https://github.com/mamba-org/mamba) for the pinned host controller and task environments, and follows the [`AGENTS.md`](https://agents.md/) cross-harness instruction convention.

Optional generators follow the same composition rule: their source and
environments are not vendored. `arh evoke` can call independently installed
[Biomni](https://github.com/snap-stanford/Biomni),
[AI Scientist v2](https://github.com/SakanaAI/AI-Scientist-v2) or
[Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory) through
a site-owned wrapper and retain what was sent, returned and executed.

The design borrows pre-registration from clinical trials and psychology's replication reform, and append-only records from lab notebooks and version control. [`docs/related-work.md`](docs/related-work.md) sets out what that means here, and which systems this composes with rather than competes against.
