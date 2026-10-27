# Project configuration

Everything about **this study**: what is immutable, where the record lives, and
which standing rules every iteration inherits. Site details belong in
`site.md`; this file survives a move between clusters.

## Paths

`immutable_inputs` is a space-separated list of directories that must never be
written to. `arh guard` aborts on any write path outside the project root or
inside one of these, and `arh run` binds each of them read-only.

## Sealed inputs

`sealed_inputs` lists held-out data that only a frozen confirmation may read:
an external validation sample, a test split, a truth set kept for the end.
`arh submit` covers each sealed path with an empty read-only mount, and refuses a
workflow, params file or iteration script that names one, unless the iteration
has a valid `FREEZE.json` (`arh freeze -n N MODEL THRESHOLDS ...`). A run of
such an iteration reads them read-only and appends the read to
`.arh/unseals.tsv`, so every use of the held-out data is on record. `arh run`
never reads them, and `arh guard` refuses writes to them. Do not put an
immutable input inside a sealed one; a sealed path inside a broader immutable
input is covered as well.

## Standing rules

`rules` names files under `rules/` that every iteration inherits. Each rule is a
Markdown file with an `arh-config` block declaring how it is enforced. Rules are
conclusion boundaries — they constrain what an iteration may claim, not what it
may compute.

## Closing the review

`review_response` decides what `arh gate results` does when a review's numbered
findings (`F1:`, `F2:` ...) are not answered in `REVIEW_RESPONSE.md` with a
decision (accepted, rejected, fixed, deferred, disputed): `require` fails the
gate, `warn` reports them, `off` skips the check. Reviews that number no findings
are not checked. `arh gate results -n N --skeleton` prints a response to start
from.

`unsound_review` decides what an `UNSOUND` verdict does. The review's part of
`REVIEW_RESPONSE.md` answers it with `Verdict: rebutted, because <reason>` or
`Verdict: accepted`; an accepted one leaves the iteration unconcluded, and the
correction goes into a new one. With `require-adjudication` (the default) a
rebuttal is not enough on its own: `arh ask --rebuttal -n N` puts it to a
reviewer, by default the one who said `UNSOUND`, and the gate passes only when
the reviewer answers `WITHDRAWN`. A `MAINTAINED` answer blocks the iteration in
every mode but `allow`. `require-rebuttal` accepts the producer's rebuttal
without a judgment, and `allow` restores the behaviour of v0.3.0, which
concluded an iteration whatever its verdict, and only reports it. Every `UNSOUND`
review needs its answer, so asking again for a milder verdict does not help.

`require_crosscheck`, `review_response` and `unsound_review` are recorded in
`CLAIM.json` when an iteration is claimed, and `arh gate results` judges the
iteration by those values: an edit made here afterwards applies to iterations
claimed after it.

`report_numbers` decides what the gate does with numbers in the report (with a
decimal point or a percent sign) that match no file under `results/` at the
precision written: `warn` lists them, `require` fails, `off` skips. Numbers that
appear in the pre-declaration and the Cross-check section are not checked.

## Pre-declaration

`required_sections` is a comma-separated list of headings an iteration README
must contain, each with text under it, before any result may be recorded.
`arh gate predeclare` enforces this, then freezes the file hash and appends it to
the freeze journal `.arh/freezes.tsv`, a hash chain that records each iteration's
freeze once; `arh gate results` fails if the README changed after the freeze or
if the freeze is not the journalled one.

`freeze_anchor` is an optional shell command run at every freeze, before
anything is written, with `{iteration}` and `{sha256}` substituted. Its first
output line is recorded in the journal. Point it at something the project
cannot rewrite: a commit pushed to a remote, an RFC 3161 timestamping service,
or a scheduler job whose comment carries the hash (Slurm's accounting database
timestamps it). If the command fails, nothing is frozen. Empty means no anchor:
the journal then detects a second freeze, but proves no time.

```arh-config
ledger            = PROGRESS.md
iterations_dir    = iterations
verification_dir  = verification

immutable_inputs  =
sealed_inputs     =
rules             = association-not-causation null-is-upper-bound negative-controls-required detection-limit-stated
required_sections = Question, Estimand, Instrument, Acceptance criteria, Negative controls, Detection limit, Prediction
require_crosscheck = true
# arh status flags an open iteration as STALE after this many hours without arh activity.
lease_stale_hours = 24
review_response   = require
unsound_review    = require-adjudication
report_numbers    = warn
# What a task may write: ro lets it write only its iteration's results/ and its run's work directory,
# so a task cannot change a frozen plan, a review, a receipt or another iteration; rw is the old
# behaviour, which projects without this key keep.
task_project_access = ro
# Scripts already in scripts/ when the plan is frozen are pinned with it. A run after one of them
# changed: warn (reported, and recorded in the run receipt), refuse, or off.
frozen_scripts    = warn
freeze_anchor     =
```
