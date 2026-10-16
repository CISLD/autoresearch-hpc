# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions are protocol/tooling versions; see `PROTOCOL.md`.

## [Unreleased]

Changes from the field feedback of a 34-iteration structural-variant study run on Slurm and
Singularity with two producer accounts and two verifier families, and from an external review
of v0.3.0 (2026-10-13) that probed the gates directly. **Protocol 0.3.0**: studies need
`arh migrate --apply`, which starts the freeze journal.

### Changed (external review of v0.3.0)
- **An `UNSOUND` verdict no longer concludes an iteration by itself.** v0.3.0 accepted
  `SOUND`, `QUALIFIED` and `UNSOUND` alike once the hashes matched, and three benchmark
  iterations concluded on an `UNSOUND` review. `arh gate results` now fails until each
  `UNSOUND` review is answered in `REVIEW_RESPONSE.md` with `Verdict: rebutted, because
  <reason>`; `Verdict: accepted` leaves the iteration unconcluded, and a later, milder review
  does not answer an earlier one. `unsound_review = allow` (`project.md`) restores the old
  behaviour. The ledger's cross-check column shows the verdicts (`QUALIFIED`,
  `UNSOUND (rebutted, withdrawn)`) instead of `yes`, and `--skeleton` adds the verdict line.
  `PROTOCOL.md` §6.8.
- **A rebuttal is judged by a reviewer.** Any rebuttal of three words or more let an
  `UNSOUND` iteration conclude, so the producer still judged its own case.
  `arh ask --rebuttal -n N` now sends the review, the rebuttal and the unchanged evidence to
  a reviewer (by default the one who said `UNSOUND`), who answers `ADJUDICATION: WITHDRAWN`
  or `MAINTAINED` in a `REBUTTAL_*` record bound to the review and to the rebuttal's text.
  With `unsound_review = require-adjudication`, the new default, the gate passes only on
  `WITHDRAWN`; a `MAINTAINED` answer blocks in every mode but `allow`.
  `ask_max_adjudications` (default 1) limits judgments per review. `require-rebuttal` keeps
  the unjudged rebuttal. `PROTOCOL.md` §6.8.
- **Integrations instead of custom code** ([docs/integrations.md](docs/integrations.md)): Entire
  CLI for agent sessions and transcripts, gitleaks for credential rules, basic-memory for
  searching findings, each optional and checked on 2026-10-16 with the versions named there.
  Omnigent was tried as a controller command and does not run on a RHEL 9 node yet (tmux 3.3
  needed).
- **gitleaks's maintained rules are applied when it is installed.** ARH's credential check
  (`arh ask`, `delegate`, `evoke`, dispatch briefs and logs, `arh memory`) used only a short
  built-in list of token shapes. With `secret_scanner = auto`, the default, gitleaks's rules are
  applied on top whenever `gitleaks` is on PATH, so new key formats are caught without ARH tracking
  them (checked with gitleaks 8.30.1: a Slack webhook URL the built-in list misses is refused and
  redacted). `gitleaks` requires it; `builtin` skips it.
- **Findings carried forward come only from concluded iterations.** Agent memory tools keep
  whatever the agent saw, unchecked, where only one harness reads it. `arh memory add -n N TEXT`
  accepts a finding only once iteration N has passed the results gate and writes it to
  `knowledge/F<N>.<k>.md`, plain Markdown with YAML front matter citing the declaration and
  report hashes, the reviews and their verdicts, so any harness, reviewer or Markdown tool can
  read it. `--supersedes ID` marks an earlier finding superseded without deleting it; a finding
  whose iteration no longer holds its conclusion is listed as stale. `arh context` shows the
  current findings as an index, `arh memory show ID` one in full. `arh memory search QUERY`
  hands the search to a Markdown knowledge tool named in `memory_search_cmd` (checked with
  basic-memory 0.23.2, which must be told not to rewrite notes: `disable_permalinks = true`,
  `ensure_frontmatter_on_sync = false`), or falls back to a word match. Findings that such a tool
  has reformatted still read. `PROTOCOL.md` §8.8.
- **The record names the agent sessions behind an iteration.** Every `arh` command on an
  iteration appends to `metadata/activity.jsonl` with `ARH_SESSION` and the agent process it
  ran under: the nearest ancestor whose program, or the script an interpreter runs, is one of the
  configured harness commands, so it works for any harness without knowing it. A session id a
  harness reports in an environment variable is added when `session_env` names one (the
  template names Claude Code's). Transcripts are not
  captured by ARH: when the project is a git repository recorded by Entire CLI, the
  `Entire-Checkpoint` trailers of commits that touched the iteration are linked instead.
  `arh sessions -n N` shows all of it, and the conclusion receipt lists the sessions and
  checkpoints. `PROTOCOL.md` §8.7.
- **Per-iteration controllers (`orchestration = per-iteration`).** A main controller session
  claims iterations and runs `arh dispatch -n N --brief FILE`, which starts a fresh controller
  session for iteration N through the configured harness command template (any agent CLI, or a
  meta-harness such as Omnigent), optionally under `dispatch_launcher` (e.g. `srun`). The
  controller pre-declares, calls the executor and the verifier, runs the results gate and hands
  back a summary with `arh dispatch report`; `arh dispatch status` lists dispatches and
  outcomes, and `arh wait` waits for controllers. While a controller holds an iteration, `arh`
  refuses changes to it from every other session; one controller per iteration;
  `max_parallel_iterations` caps how many run. The controller's stdout and stderr are kept under
  `metadata/dispatch/NNN/` with credential-shaped text removed and hashed in `run.json`. The
  verifier must differ in family from both the controller and the executor. `single`, the
  default, keeps today's behaviour. `PROTOCOL.md` §6d; conformance E20–E22.
- **Blind replicators no longer see the operator's home.** `arh replicate` gave an agent only
  the frozen DAG, but the harness still read the operator's home directory, where Claude Code's
  auto-memory, Codex's memories, claude-mem and chat history can hold the original code or its
  results. Replicators now run with a fresh home (`replicate_home = fresh`, the default) into
  which only the login files in `fresh_home_files` are linked; `fresh_home_env_unset` drops
  variables such as `CLAUDE_CONFIG_DIR` that point back at the real configuration. Each agent's
  `HOME.json` records it, with the command template it ran, and `arh replicate report` says so.
  A fresh home also hides the harness's user-level settings (model, permissions, MCP servers,
  hooks), so `arh replicate` says to pin what an agent needs in its command template. Per-
  iteration controllers can start with a fresh home too (`dispatch_home = fresh`). The login
  files are `fresh_home_files` and the dropped variables `fresh_home_env_unset`. The launcher now splits harness
  commands as `arh ask` does: a quoted argument in a command template broke replication.
- **Attempts per question are counted.** An agent could run several iterations on one question
  and conclude the one that worked, and the ledger showed only that one. `arh claim` takes
  `--question ID` or `--continues N` (default: the iteration is its own question), a passing
  `arh gate results` writes a conclusion receipt (`metadata/conclusions.jsonl`, the hashes it
  rested on), and the ledger's status block lists every question tried more than once with each
  concluded iteration as "attempt k of n". The Results column says `concluded` while the
  receipt still matches the evidence; `arh status --json` adds the attempt. `PROTOCOL.md` §8.6.
- **The review policy is bound at claim.** `require_crosscheck`, `review_response` and
  `unsound_review` were read from `project.md` when the gate ran, so a producer could relax
  the rule its own iteration was judged by. `arh claim` records them in `CLAIM.json`
  (`review_policy`) and the gate uses the recorded values. `PROTOCOL.md` §6.9.
- **Empty sections no longer freeze.** A pre-declaration with every required heading present
  and every body empty froze. Each required section now needs text that is not the template's
  own. `PROTOCOL.md` §3.1.
- **A plan is frozen once.** Deleting `PREDECLARATION.sha256` while `results/` was moved aside
  let an edited plan be frozen again and concluded. `arh gate predeclare` now appends every
  freeze to `.arh/freezes.tsv`, a hash chain, and refuses an iteration the journal already
  holds, or one that already has a run receipt or a review. `arh gate results` fails when the
  freeze is not the journalled one. `arh claim` marks new iterations `freeze_journal: true` so
  `arh migrate` never backfills a row that was removed. `PROTOCOL.md` §3.5–§3.7.
- **`arh ledger check` reads the claim registry and the journal.** A deleted concluded
  iteration left it passing. It now fails when a claimed number has no directory, when the
  journal does not chain, and when a frozen iteration and the journal disagree. §8.3.

### Added (external review of v0.3.0)
- `freeze_anchor` (`project.md`): a command run at each freeze, with `{iteration}` and
  `{sha256}`, whose first output line is journalled; point it at a pushed commit, a
  timestamping service or a scheduler job comment to give freezes a time the project cannot
  rewrite. If it fails, nothing is frozen.
- `arh gate results` reports the runs of the iteration and names files a completed run used
  that were edited and run again (§5.9a).
- Conformance scenarios E14–E22 (E16 now also covers an unjudged, a maintained and a
  withdrawn rebuttal); E1's description now says what it tests (unfilled placeholders).

### Fixed
- `harness/README.md` described an earlier ten-study state of the replication benchmark; its
  counts now match the eleven-study record the paper reports.

### Added
- **Durable knowledge lives in the project.** Operator directives, data locations and tool
  facts reached a study only through one harness's private memory, which no other harness,
  account or reviewer could read. `arh init` now scaffolds `DIRECTIVES.md` beside `GOTCHAS.md`,
  and `arh migrate` adds both to older studies. The agent contract gains rule 10 (facts that
  outlive a session are written to the project, private memory may only point to them), and
  `PROTOCOL.md` §8.4 states it. `arh claim` records the files' hashes in `CLAIM.json`,
  `arh ask` points the reviewer at the directives and records their hashes in the review record,
  `arh delegate` gives the executor the directives in full, and `arh context` reports whether
  they changed since the claim. `arh doctor` warns when a file is missing, when `AGENTS.md`
  lacks the rule, and when a gotcha has no assertion.
- **`arh freeze` and `sealed_inputs`: held-out data that only a frozen confirmation can read.**
  A study's most important safeguard, that its external sample was scored only after a
  configuration was chosen without it, lived in hand-written scripts, and the hand-written guard
  hashed the model but not the thresholds file that carried the decision rule (field feedback
  #21, #29). `arh freeze -n N PATH...` writes a write-once `FREEZE.json` with the hash of every
  file under each path, after the pre-declaration is frozen. Paths in `sealed_inputs`
  (`project.md`) are covered by empty read-only mounts in every `arh submit` and `arh run`
  container, Nextflow's automounts are off for such runs, and a workflow, params file or iteration
  script that names a sealed path is refused, unless the run belongs to an iteration whose freeze
  is valid. That run binds them read-only, records the freeze in `run.json` and appends the read
  to `.arh/unseals.tsv`. `arh submit` refuses a run whose frozen files changed, `arh gate results`
  fails on one, `arh freeze list` and `arh status` show every freeze and which iterations read
  each sealed input, and `arh guard` refuses writes into them. `harness/install.sh` denies the
  harness's own reads of sealed paths where the harness can express it (Claude Code, OpenCode).
  `PROTOCOL.md` gains §3.9 and §5.8.
- **Nothing that produces a result runs without a receipt.** In the field study every GPU arm,
  a verification recount and a second tool image ran outside `arh submit`, so none had a run
  receipt, and reviews flagged it (field feedback #14, #18, #33, #34, #35, #41).
  - **GPUs:** a process labelled `gpu` or `process_gpu`, or with an `accelerator` directive,
    runs with `--nv`, and on Slurm goes to `gpu_partition` with `--gres=gpu[:gpu_type]:N`,
    `--constraint` and `gpu_extra` from `site.md`. The generated settings are label-aware
    closures, so a process with several labels gets all of them.
  - **Images by label:** `label 'image_<name>'` runs a process in a declared, digest-checked
    local image with that image's own `PATH`; the receipt records the images and `trace.tsv`
    gains a `container` column.
  - **Imports:** a plan declares code it takes from other iterations (`imports =` in an
    `arh-config` block). Their hashes are frozen into `PREDECLARATION.sha256`, `arh submit`
    refuses a run in which one changed, and other iterations' scripts that are named but not
    declared are hashed as `referenced_sha256`, with a warning.
  - **Verifications run and conclude:** `arh verify run OBJECT WORKFLOW` submits through the
    same path as an iteration; `arh verify conclude` checks the frozen plan, a `RESULT.md` with
    one `OUTCOME:` line and a successful receipt of the plan (or `--without-run REASON`), and
    writes `CONCLUDED.json`. `arh verify new --of N` records the target, and the ledger and
    `arh status` list verifications beside the iterations they check.
  - **`arh note -n N [--job ID] TEXT`** records work that ran outside `arh submit`.
    `arh status` counts notes, `arh context` shows them, and `arh gate results` warns about
    them and about results that no receipt accounts for.
- **Unattended runs that outlive a session, and sessions that end mid-iteration** (field
  feedback #11, #35, #36). `arh submit --detach` starts the run in its own session and returns
  once it holds its launch lock. `arh status --running` lists live submissions with their trace
  counts, running reviews, and the Slurm state of noted job ids. Every command that acts on an
  iteration records itself in the iteration's lease (`metadata/lease.json`); `arh status` lists
  open iterations with their holder and idle time, a command from another agent, user, host or
  `ARH_SESSION` warns, and `arh lease take -n N --reason TEXT` makes a takeover explicit.
- **Checks that catch a broken run before it runs** (field feedback #5, #37, #38).
  `arh doctor --smoke [gpu]` runs one framework task through the configured scheduler and image
  and reports what it sees: the task environment, a writable project, read-only immutable inputs,
  hidden sealed inputs and a GPU. An `arh-smoke` block in a pre-declaration lists commands that
  `arh gate predeclare` runs once in their image before freezing; the output's hash is frozen with
  the plan. `arh inputs check` reads the end-of-file marker of CRAM 3 and BGZF files (and with
  `--deep` decompresses gzip) under the declared inputs, caches passing results by size and
  modification time, and records them where run receipts cite them; `arh submit` warns when a
  declared input failed. On the field study's data it flags the truncated CRAM that cost a truth
  set and passes the re-run that replaced it.
- **Closing the review loop** (field feedback #12, #16). Reviewers are asked to number their
  findings (`F1:`, `F2:` ...). `arh gate results` lists every numbered finding of every
  eligible review and whether `REVIEW_RESPONSE.md` answers it with a decision (accepted,
  rejected, fixed, deferred, disputed), per review section when there are several, and fails
  while one is unanswered (`review_response = require | warn | off`; reviews without numbered
  findings are not checked). `arh gate results -n N --skeleton` prints a response to start from.
- **Reported numbers traced to results files.** The results gate lists numbers in the report
  (with a decimal point or a percent sign) that match no file under `results/` at the precision
  written, as is or as a percentage of a fraction; numbers from the pre-declaration, version
  strings and the Cross-check section are skipped (`report_numbers = warn | require | off`). On
  eleven reports of the field study it flagged 0 to 22 of 65 to 178 numbers each, mostly values
  computed in the prose or quoted from other iterations.
- **Credential scan before anything leaves the site.** `arh ask`, `arh delegate` and
  `arh evoke` refuse to send a plan, report, task or note carrying something shaped like a
  credential (cloud, GitHub, model-provider and chat tokens, private keys, assigned secrets);
  a dry run warns. `secret_scan = off` in `harnesses.md` disables it.
- **`site_gotchas` in `site.md`** names a Markdown file of tool and cluster pitfalls shared by
  every project on the machine, so a lesson is paid for once per site instead of once per
  project. It is read, hashed and checked like the project's own files, and
  `harness/install.sh` makes its directory reachable from each harness.

### Changed
- `arh verify gate` refuses to overwrite an existing freeze, as `arh gate predeclare` always
  has (§3.8); it used to rewrite `PREDECLARATION.sha256`.
- The ledger's generated status block lists verifications. A ledger rendered by 0.3.0 is
  reported as stale by `arh ledger check` until `arh ledger render` runs once.

## [0.3.0] — 2026-09-24

Most fixes below were found during internal field deployment on a Slurm +
Singularity workflow with a separately configured reviewer. The source research
material is intentionally not part of this software release; the failure classes
that mattered are preserved as tests and generic documentation instead.

### Added
- **`test/conformance.py`, the protocol conformance matrix.** One injected violation per
  protocol boundary (E1-E11), each checked for its specified refusal, written as JSON with the
  commit it ran on. The matrix had moved out of the repository with the publication material,
  so CI no longer ran it. CI now runs it on every push. It also accepts a Slurm or PBS site, so
  task failure, interruption and the read-only input mount can be checked on a real scheduler,
  and `--claim-launcher` races the concurrent claims from several nodes on a shared filesystem.
- **`harness/README.md` says which harnesses and models have actually run.** `config/harnesses.md`
  ships entries for four harnesses; only three had produced or reviewed a project. A table now
  gives the harness builds, models and counts from the replication benchmark's run records.
- **Harness access is generated from the project and checked.** A harness may enforce its own
  boundary at the project root while the declared `immutable_inputs` sit outside it; headless,
  OpenCode rejected such a read instead of asking, so a producer could not read its own data and
  nothing named the cause. `harness/install.sh` now writes the entries each harness needs
  (OpenCode `permission.external_directory`, Claude Code `permissions.additionalDirectories`),
  and `arh doctor` checks that every declared input is reachable.
- **`web_access = allow | deny` in `harnesses.md`.** Whether a producer may look results up was
  solved differently by each adapter, or not at all. With `deny`, `harness/install.sh` turns the
  harness's web tools off (OpenCode `webfetch`/`websearch`, Claude Code `WebFetch`/`WebSearch`),
  `arh doctor` fails if any are on, and `AGENTS.md` states the rule.
- **The review terms are bound to the iteration at claim.** A frozen pre-declaration fixed
  the science, but the terms of the cross-check (`verifier`, `verifier_fallback`,
  `require_foreign_family`, the review bounds) lived in `.arh/config/harnesses.md`, which nothing
  froze, so a producing agent could edit the rules of its own review without a trace. `arh claim`
  now keeps a copy of the file in `metadata/harnesses.claimed.md` and its hash in `CLAIM.json`,
  and every review record carries the hash in force when it ran. A review under changed terms
  counts only if it records why: `arh ask` refuses before any model call unless given
  `--terms-changed REASON`, the record keeps the reason and the changed keys, and
  `arh gate results` refuses a review whose terms differ from the claim's without one. Records
  and claims older than the hash are judged as before. `arh status` reports a change per iteration.
- **An accepted review that deviates from the default says so.** `arh gate results` called every
  eligible review "foreign", including a same-family review accepted under
  `require_foreign_family = false`. It now lists each review with its verdict and marks one taken
  from the producer's own family, or under changed review terms, with the reason.
- **Optional external generators via `arh evoke`.** Biomni, AI Scientist v2 and
  Agent Laboratory now have disabled-by-default registry entries. ARH sends a
  bounded request through a site-owned, shell-free command adapter and retains
  request/config hashes, version, response, artifacts and exit status under the
  iteration. No upstream source is vendored, and generated output is advisory:
  it cannot satisfy a results gate. The Evoke skill selects a tool only when its
  specialist workflow materially fits and requires a request preview plus an
  explicit per-run external-code/data acknowledgement.
- **`arh site detect`** probes the machine and proposes a `site.md` block instead of
  leaving every resource key to be typed by hand. `arh init` only tested whether a
  scheduler's client commands existed, so `slurm_partition`, `slurm_account` and the
  time/cpu/memory defaults were hand-filled for each project — the same edit twelve
  times across a replication benchmark, with a wrong queue name only surfacing when
  the first job was rejected. It lists the queues visible to you with their walltime,
  core, memory and generic-resource limits, reports the accounts and QOS you can
  charge to (saying so plainly when `sacctmgr` is unreachable rather than quietly
  proposing none), and inside a project checks the current settings against the
  machine, failing on a queue that does not exist or a request larger than any node
  in it. It never writes the file: choosing a queue is a policy decision. Schedulers
  are a table of probes rather than hardcoded branches, and one the framework cannot
  yet drive is reported with what adding it needs instead of being silently treated
  as `local`.
- **`arh wait [-n N]`** blocks until an iteration's submissions and reviews have
  finished. Headless sessions get no completion notice and end when their reply
  ends: in a replication benchmark, Claude Code producers that backgrounded work and
  ended their reply to wait lost two rounds in each of two studies.
- **`arh env create NAME pkg=version ...`** solves a scientific environment once
  inside the task image, writes a replayable lock (`.arh/NAME-explicit.lock`, hashed
  by every run receipt) and prints the prefix. Without packages it rebuilds from the
  lock and verifies the package list. A built environment does not change; a new
  package set is a new name. Producers had built environments in several different
  ways, unpinned until someone locked them, one of them in the background.
- **Content-policy refusals are their own outcome.** `arh ask` exits 77 when the
  provider refuses the content itself (Codex flagged a public RNA-seq count table as
  a biological risk). Like a limit, it spends no review round. Each harness in the
  new `verifier_fallback` setting is then tried in turn; `arh doctor` checks their
  families.
- `arh ask` prints the provider's own refusal line. The review record keeps it, its
  kind (`limit`, `auth` or `refusal`) and any stated reset time (`retry_hint`).
- **Review token usage.** A command template may pass `{usage}`, a file the reviewer
  writes token counts or cost to; the record stores it as `usage`.
  `harness/claude/review.sh` and `harness/codex/review.sh` do this for the two CLIs.
- **Shared environments.** `arh init --env-cache DIR` (or `ARH_ENV_CACHE` for the
  setup scripts) builds the pinned host and task environments once per pin set and
  reuses them across projects; each project used to build its own, about 1.5 GB.
- `nextflow_reports = html | gzip | none` in `site.md`. The HTML report and timeline
  were 99% of a submission's evidence bytes (1.9 MB per run).
- `arh submit WORKFLOW.nf --lint` runs `nextflow lint` with the pinned controller,
  before any attempt directory exists.
- `AGENTS.md` shows a minimal workflow for `arh submit` (what a task sees, where the
  evidence goes, how packages are declared), says how to run unattended, and says
  that a failed acceptance criterion is a result to report, not a reason to stop.
  Producers had read ARH internals to work out how to submit, and one stopped a study
  as blocked on a failed criterion. `arh next` says the same and points to `arh wait`
  while work is running. The iterate and cross-check skills match.
- `docs/headless.md`: lessons from driving producers and reviewers unattended on Slurm.

### Changed
- **`ask_max_input_bytes` defaults to 48000 (was 24000).** One real iteration, a frozen
  pre-declaration plus its report plus the role prompt, came to about 30.5 kB, so the old
  default could not send the artefact under review; three benchmark studies raised it
  independently. The refusal already names the size of each part.
- **`verifier_fallback` now also covers provider limits.** `arh ask` tried the fallback
  list only after a content refusal (exit 77) and gave up on a usage limit (exit 75),
  telling the agent to sleep until the reset the provider stated. That time is not
  reliable: a provider once named a reset five days out, and a probe 44 minutes later
  succeeded. A limit now moves on to the next fallback verifier, and the advice in
  `arh ask`, `AGENTS.md` and `docs/headless.md` treats a stated reset as an upper
  bound to re-probe within, not a schedule.
- `arh migrate` also refreshes a study's copies of `AGENTS.md` and `skills/` from the
  framework, after a backup; skills the study added are kept. Agents read those
  copies, so a framework update never reached them. `arh doctor` warns when they differ.
- The review lock records its owner: `arh wait` tells a running review from a dead
  one, and a lock left by a dead process on the same host is reclaimed instead of
  refusing every later review.
- A reviewer's stderr beyond 16 KB keeps its last 8 KB, where CLIs print refusals.
- CI runs on pushes to every branch, not only `main`.
- `docs/skills-and-token-budget.md` states that the bounds cover reviews only;
  producer sessions are not bounded by `arh`.

### Fixed
- **A non-local `ARH_TEST_SITE` is an error, not a result.** Both test suites copied the file
  into the toy project verbatim, so a Slurm `site.md` submitted real jobs and reported 142 of
  143 tests passing, which read as a protocol failure. They now refuse a missing file or a
  `scheduler` other than `local` before running anything.
- **`schema/claim.schema.json` matches what `arh claim` writes.** The schema forbids unknown
  properties but lacked `inferred_agent` and `inferred_from`, and CI only checked that it
  parses. A test now validates a real `CLAIM.json` against it.
- **Reviews no longer die on stderr volume.** `codex exec` echoes the whole
  prompt to stderr, and the 16 KB stderr cap SIGKILLed every review whose prompt
  exceeded it (exit 66). The dead attempt still spent a review round. Only
  stdout, the review itself, is bounded now; stderr is truncated on disk but
  drained.
- **Provider refusals no longer consume a review round.** `codex exec` exits 0
  on "You've hit your usage limit". Refusals (quota, rate limit,
  authentication) are recorded with `provider_error: true`, exit 75, and are
  named in `arh gate results`.
- **Standing rules are checked before a review is dispatched.** They used to run
  only in `arh gate results`, after the review, so a one-word fix to the report
  invalidated the hash-bound review and cost a second round. `arh ask` now
  refuses a report that the results gate would reject (non-blind roles).
- **Review responses have a home.** The report template and the `iterate` skill
  asked for the cross-check evaluation to be written into the report after
  review, which invalidated the review. The evaluation now goes in
  `REVIEW_RESPONSE.md` at the iteration root; follow-up computation goes through
  `arh verify`.
- **A running submission can be stopped cleanly.** The wrapper forwards
  SIGTERM/SIGINT/SIGHUP to Nextflow (a second signal escalates to SIGKILL),
  records the signal in `run.json` and releases the launch lock. Signalling it
  used to kill it before the lock was released, so every later submit under that
  name refused. The lock records its owner in `owner.json`. A lock left by a dead
  process on the same host is reclaimed atomically; bare, live or remote locks
  still refuse.
- **Run receipts hash the scripts a workflow calls.** `run.json` records
  `script_sha256` for every file under the iteration's `scripts/`. It used to
  hash only the workflow, so two runs that did different things could have
  identical receipts.
- **Setup scripts no longer race.** `setup-nextflow.sh` and `setup-runtime.sh`
  serialise their rewrite of `site.md`. Both now record replayable `@EXPLICIT`
  locks; plain `micromamba list --explicit` output has a header and cannot be
  passed to `--file`. A duplicated `.arh` branch left in both scripts by the
  rename is gone.
- The "not inside a project" error names `ARH_PROJECT`, the override for
  harnesses that reset the working directory between commands. The README and
  `AGENTS.md` document it.
- The 0.2.0 notes below were garbled by the automated rename. They described a
  compatibility layer that 0.2.0 does not ship, and now match the code.
- Leftover `discovery-loop` names: the Claude Code `PATH` example (it pointed at
  `../discovery-loop/bin`), the Codex profile, the adversary role and the test
  banner.
- **`arh ledger render` no longer adds a second status table.** Given a ledger whose
  status block uses another marker (a 0.1 ledger's), it used to append a second
  table, and `arh ledger check` still passed. `render` now refuses and names the
  marker. `check` now fails whenever the table differs from a fresh render
  (stale, missing or duplicated), not only when an iteration number is absent.
- `arh doctor` compares the protocol recorded in `.arh/VERSION` with the
  framework's, and names `arh migrate` on a mismatch.
- The review-size refusal states the prompt's size, the limit and the size of
  each part. It used to ask for "a smaller explicit evidence packet", which no
  option supplies.
- `arh gate results` warns when a reviewed iteration has no `REVIEW_RESPONSE.md`
  (protocol 6.5 requires every finding to be evaluated).

### Added
- `scripts/lock-env.sh` exports an existing conda/micromamba environment as a
  replayable `@EXPLICIT` lock. It can also recreate the environment and verify
  that the package list is identical.
- `docs/hpc-execution.md` covers pulling the runtime image, run receipts and
  caching, stopping a submission, and Nextflow strict syntax (a Groovy `import`
  is a compile error that surfaces only after submit).
- **`arh migrate [DIR] [--apply]`** moves a 0.1 study to the current layout: state
  directory, fences, ledger markers, `site.md` paths, `AGENTS.md`, `skills/` and
  `.arh/VERSION`. It is a dry run by default and writes a backup before changing
  anything. It never touches iteration or verification files, and running it
  again changes nothing
  ([docs/migration-hardening.md](docs/migration-hardening.md)).
- Standing rules may set `scope = paragraph`, so a forbidden term must be
  qualified in the same paragraph rather than anywhere in the document. The
  default stays `document`, so existing reports are judged as before.
- `harness_<name>_version_cmd`: its first output line is stored in each review
  record as `verifier_version`. The shipped harnesses declare one.
- Regression tests for the above: `test_migrate_legacy_study`,
  `test_ledger_render_refuses_a_foreign_status_block`,
  `test_ledger_check_detects_a_stale_table`, `test_rule_scope_paragraph`,
  `test_review_records_verifier_version`,
  `test_doctor_names_a_protocol_mismatch` and
  `test_gate_warns_without_review_response`.
- Six regression tests: `test_verbose_stderr_does_not_abort_review`,
  `test_provider_error_does_not_consume_round`,
  `test_rule_violation_blocks_review_before_dispatch`,
  `test_sigterm_to_wrapper_releases_lock`,
  `test_dead_owner_lock_reclaimed_and_scripts_hashed` and
  `test_live_owner_lock_is_kept`.
- **Publication-readiness track:** a publication roadmap, a pre-specified
  evaluation plan, a venue-neutral short-paper draft, and a synthetic
  deterministic mean-shift example that is checked in CI.

### Changed
- Host bootstrap no longer requires micromamba to be installed beforehand. The
  pinned standalone binary is downloaded on demand, SHA-256 verified, cached
  under the project `.arh/tools/` directory, and recorded in `micromamba.lock`.
  Explicit `--micromamba` / staged-binary use remains available for offline HPCs.
- The README uses the full-resolution banner (`docs/assets/banner.png`). The
  low-resolution JPEG and the unreferenced WebP are gone. Setup steps are
  numbered consistently, and the README documents SSH cloning and
  `ARH_PROJECT`.
- Publication-facing documentation now uses synthetic or generalized examples
  rather than details copied from the internal source study.

## [0.2.0] — 2026-09-11

### Changed
- Renamed the public CLI from `dl` to **`arh`** (AutoResearch HPC) across
  commands, paths and documentation. Project state lives in `.arh/`,
  configuration fences are `arh-config`, and environment variables use the
  `ARH_` prefix (`ARH_HOME`, `ARH_PROJECT`, `ARH_TEST_SITE`). There is no
  compatibility layer: `dl`, `.dl/`, `dl-config` and `DL_*` are no longer
  recognised.
- `arh init` now discovers Slurm/PBS/local and Singularity/Apptainer defaults,
  supports `--bootstrap`, `--micromamba`, `--runtime`, and `--scheduler`, and
  points directly to `arh doctor` for remaining setup work.
- `arh doctor` now diagnoses the host Nextflow environment, runtime image digest,
  scheduler clients, harness families and standing rules, with concrete fix
  commands for missing setup.
- The normative protocol is now **0.2.0**. The former “unreleased hardening
  amendment” has been integrated into the relevant normative sections instead
  of living outside the released specification.
- Protocol §10 now explicitly identifies **eight** mechanically enforced
  boundaries, matching the conformance suite.

### Added
- `arh arm` — parallel sub-analyses with their own acceptance criteria,
  negative control and recorded fate.
- `arh dag` — reconstruct and freeze the path a result took.
- `arh replicate` — fan-out blind replication from the frozen DAG.
- `arh next` — deterministic next-action guidance.
- `arh status --json` — machine-readable state.
- `arh verify` — explicit verification track.
- CI integration, shellcheck/schema validation, citation metadata, security and
  contribution guidance.

### Hardened
- Cross-check eligibility is hash-bound to the declaration, report and review,
  with concrete producer/verifier families and successful invocation metadata.
- Pre-declaration freezes cannot be silently overwritten.
- Harness argument parsing avoids shell evaluation and uses bounded execution.
- Local execution propagates failures and records execution metadata.
- Non-smoke container execution requires declared image identity.
- Relative immutable input paths are normalized before write checks.

### Migration
- Use `arh` in scripts and documentation from this release onward.
- New projects store configuration and framework state in `.arh/`.
- 0.1 studies (`.dl/`) must be migrated before `arh` can open them; see
  [docs/migration-hardening.md](docs/migration-hardening.md). Frozen iteration
  files are not rewritten.

## [0.1.0] — 2026-09-08

First working version of the discovery-loop protocol and tooling.

### Added
- Normative protocol and mechanically enforced pre-declaration boundaries.
- Initial `arh` CLI with claim, new, gate, ask, run, submit, guard, ledger,
  status and doctor commands.
- Pluggable scheduler/container configuration and portable agent instructions.
- Initial schemas, skills and regression tests.

### Fixed
- Pre-declaration placeholder detection, multi-word required sections, and the
  first live Codex non-interactive dispatch issues.
