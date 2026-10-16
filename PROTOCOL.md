# The AutoResearch HPC protocol, v0.3.0

Normative specification. `MUST`, `MUST NOT`, `SHOULD` and `MAY` are used in the
RFC 2119 sense. `README.md` explains the tooling; this file defines what a
conforming implementation enforces.

## 1. Objects

**Project** — a directory containing `.arh/`, a ledger, and zero or more
iterations. **Iteration** — a numbered, append-only directory answering one
question. **Verification** — a re-examination of an object an iteration already
produced. **Finding** — one typed claim. **Cross-check** — one review of an
iteration by a configured foreign harness.

## 2. Claiming

2.1 An iteration number MUST be obtained by an operation atomic against
concurrent agents. Directory creation is the reference mechanism.

2.2 An agent MUST NOT create an iteration directory by any other means.
Consulting a registry and creating the directory afterwards is a race.

2.3 A claim MUST record holder, timestamp and question.

2.4 Numbers are never reused. An abandoned iteration keeps its number and is
marked `ABANDONED`.

2.5 Work on a claimed iteration SHOULD be attributable to the session doing it,
and a session that takes over an iteration another session holds SHOULD record
the takeover and its reason.

## 3. Pre-declaration

3.1 An iteration MUST carry a pre-declaration written **before any result
exists**, containing at minimum: question, estimand, instrument, acceptance
criteria, negative controls, detection limit and prediction. Each MUST have
content of its own: a heading with nothing under it, or with only the
template's text, declares nothing.

3.2 The estimand MUST be stated as a quantity in its own units precisely enough
that an independent implementation could compute a comparable number.

3.3 The detection limit MUST be stated in the units of the estimand. A candidate
MAY be excluded by a declared detection limit; it MUST NOT be excluded by an
unexamined threshold.

3.4 Negative controls MUST be named in the pre-declaration, not selected after
the result.

3.5 A conforming implementation MUST refuse to accept a pre-declaration for an
iteration whose results already exist, or that already has a run receipt or a
review.

3.6 On acceptance, the pre-declaration MUST be cryptographically frozen. After
freezing it MUST NOT be modified. A design change is a **new iteration**. Each
freeze MUST be recorded once in an append-only, hash-chained journal kept
outside the iteration; an iteration the journal records MUST NOT be frozen
again, even when its freeze file is gone. A freeze MAY be anchored outside the
project (a pushed commit, a timestamping service, a scheduler record), which is
what gives it a time an actor controlling the project cannot rewrite.

3.7 Any operation accepting results MUST verify the frozen hash, and that the
freeze is the one the journal recorded, and MUST fail if either no longer
matches.

3.8 A pre-declaration gate MUST NOT overwrite an existing freeze. Missing
configured standing-rule files MUST fail the gate.

3.9 A confirmation on held-out data MUST be preceded by a write-once freeze
that records the hash of every artefact carrying a decision it applies (model,
thresholds, decision rules, code). A run of that iteration MUST be refused when
any frozen artefact no longer matches.

## 4. Append-only

4.1 An iteration MUST NOT be modified to change its conclusion.

4.2 A correction MUST be a new iteration stating what the earlier one got
wrong. Superseded files MUST remain intact.

4.3 Supersession MUST be recorded in the superseding entry. The superseded entry
MUST NOT be edited to be correct in hindsight.

4.4 A standing rule that proves wrong MUST be corrected by a dated amendment
that leaves the original text visible.

## 5. Execution

5.1 Every scientific tool that produces a result MUST run from a declared,
content-pinned image. A path or mutable tag alone is not a reproducibility pin.

5.2 Declared immutable inputs MUST be mounted read-only and MUST NOT be written.

5.3 All output MUST be written under the project root.

5.4 Randomness MUST be seeded and the seed recorded. Inputs MUST be sorted where
order could affect the result.

5.5 Acceptance criteria MUST be evaluated before the result is interpreted. A
run failing its criteria has no result to interpret.

5.6 A step that can discard data while exiting zero MUST be guarded by an
assertion that the data survived. “The tool ran without error” is not evidence.

5.7 Local waited jobs MUST propagate execution failure. Execution metadata MUST
identify the code/workflow, environment and completion status sufficiently to
bind the record to the run. Complete replayable provenance is a stronger goal
than conformance to this clause.

5.8 Inputs a project declares sealed MUST NOT be readable by a run unless the
run's iteration holds a valid freeze (§3.9). Every run that can read them MUST be
recorded with the freeze it ran under.

5.9 Computation that produces or checks a result SHOULD run through the
receipt-producing execution path, including GPU work, auxiliary tool images and
verifications. Computation that runs outside it MUST be recorded in the project
as having done so. Code a plan imports from another iteration MUST be named in
that plan and bound to it by hash.

5.9a One frozen plan MAY be executed more than once, since a run can fail or a
review can find a bug. An implementation SHOULD report when a file a completed
run used is edited and run again within the same iteration, so that the report
says which run each result comes from.

5.10 Declared inputs SHOULD be checked for integrity (at least that a
compressed or container file is complete) before a run reads them, and the
result SHOULD be recorded with the run.

## 6. Cross-checking

6.1 Before an iteration is concluded, it SHOULD be reviewed by a harness in a
**different model family** from the producer.

6.2 An implementation MUST record producing and verifying model families and
MUST mark a same-family check as materially weaker.

6.2a The different-family requirement is a heuristic, not a proof. It reduces
one source of correlated error; it does not establish statistical independence
or scientific truth.

6.3 A `reimplementer` MUST NOT read the original implementation.

6.4 A re-implementation MUST compare membership, not only counts, when the
object being reproduced is a set.

6.5 A cross-check verdict is evidence, not a ruling. Findings MUST be evaluated
on their merits and rejected objections MUST be recorded with reasons. An
implementation SHOULD identify each finding and check that the record answers
it before a result is accepted.

6.6 A required cross-check MUST have a successful invocation record, exactly one
recognized verdict, concrete producer/verifier family declarations, and matching
hashes for the reviewed declaration, report and review text. The families MUST
differ unless the project's recorded policy accepts same-family review
(`require_foreign_family = false`). A review accepted under that policy MUST
record the policy it ran under and MUST be reported as a same-family check. A
per-review same-family override MUST NOT satisfy a required check.

6.7 The review terms in force when an iteration is claimed (verifier, fallbacks,
family policy and review bounds) MUST be bound to that iteration. A review taken
under different terms MUST NOT satisfy a required check unless it records the
reason for the change.

6.8 A review whose verdict is `UNSOUND` MUST NOT let the iteration conclude
unless the record answers that verdict with a reasoned rebuttal and a reviewer,
shown the rebuttal and the unchanged evidence, withdraws the verdict. Every
`UNSOUND` review needs its own answer: a later, milder review of the same
evidence does not answer it. A reviewer's judgment of a rebuttal MUST be bound
to the review and to the rebuttal's text, and a maintained verdict MUST block
the iteration whichever reviewer gave it. A producer that agrees with the
verdict leaves the iteration unconcluded and corrects it in a new one. A project
MAY accept an unjudged rebuttal (`unsound_review = require-rebuttal`) or relax
the rule (`unsound_review = allow`); the verdicts of the eligible reviews and how
each `UNSOUND` one stands MUST appear in the ledger either way.

6.9 The review policy in force when an iteration is claimed (whether a review
is required, how findings must be answered, what an `UNSOUND` verdict requires)
MUST be bound to that iteration; a later change of the project's policy MUST
NOT apply to it.

## 6b. Arms

6b.1 An iteration MAY be divided into arms — parallel routes to its one
question. An arm MUST carry its own acceptance criteria and negative control.

6b.2 Every arm MUST receive exactly one fate: `CONCLUDED`, `NULL`, `INFEASIBLE`,
`KILLED_BY_CONTROL` or `ABANDONED`.

6b.3 `INFEASIBLE`, `KILLED_BY_CONTROL` and `ABANDONED` are reportable outcomes
and MUST NOT be omitted. Ten attempted arms with one hit is a different claim
from one attempted arm with one hit.

## 6c. Discovery DAG and blind replication

6c.1 A load-bearing result SHOULD have its path reconstructed as a discovery
DAG: inputs, nodes, decisions and terminal claim.

6c.2 The DAG MUST state how many distinct paths exist from inputs to claim and
how many were reported. The difference contributes to the multiple-testing
denominator.

6c.3 A node declared in DAG tables but absent from its graph MUST be reported.

6c.4 Once frozen, the DAG is the only permitted specification for a blind
replication, and the original implementation MUST NOT be provided to the
replicating agent. A conforming implementation MUST enforce this by construction
within the cooperative protocol boundary rather than only instructing the agent.

6c.5 Replication MAY fan out across several agents/harnesses. Implementations
MUST report divergence: differing values, contested set membership and the
ambiguities each agent resolved.

6c.6 Agreement among replicating agents MUST NOT be reported as confirmation.
The evidential content of a fan-out is its disagreement, not a majority vote.

## 7. Reporting

7.1 The pre-declared quantity MUST be reported, including when another number is
more attractive.

7.2 A null result MUST be reported as an upper bound with its detection basis.
“No effect” MUST NOT stand alone.

7.3 A result without appropriate orthogonal validation MUST be labelled a
candidate.

7.4 Causal language MUST NOT be used unless the design supports it.

7.5 Negative-control behaviour MUST be reported.

7.6 A prediction that missed MUST be recorded as such and MUST NOT be revised.

7.7 A number a report states SHOULD be traceable to a results file of the
iteration, at the precision written.

## 8. The ledger

8.1 A project MUST maintain a single authoritative state file.

8.2 It MUST be sufficient to resume the project cold without conversation
history.

8.3 Generated sections MUST be reproducible from what is on disk, and an
implementation MUST provide a consistency check. The check MUST fail when an
iteration the claim registry lists has no directory, when the freeze journal
does not chain, and when a frozen iteration and the journal disagree.

8.4 Facts a later session needs — operator directives, data locations,
external findings a design depends on, and silent failure modes — MUST be
recorded in project files that every harness and reviewer can read. An agent's
private memory MAY point to them; it MUST NOT be their only record.

8.5 A verification's outcome MUST be recorded with the frozen plan and the runs
it rests on, and shown beside the iteration it verifies.

8.6 An iteration MUST name the question it addresses when it is claimed, and a
passing results gate MUST record the evidence the conclusion rests on. The
ledger MUST report each concluded iteration with the number of iterations that
addressed its question before and after it, concluded or not, so that a result
is never shown without the attempts that preceded it.

## 9. The operator

9.1 An operator challenge to a result MUST trigger a new iteration, never an
instruction to edit the old one.

9.2 The challenge SHOULD be recorded verbatim as the new iteration's motivation.
The operator's objections are part of the scientific record.

## 10. Conformance

An implementation conforms to protocol 0.3.0 if it mechanically refuses
violations of §2.1, §3.1, §3.5, §3.6, §3.7, §4.1, §5.2, §6.8 and §6c.4 — **nine
mechanically enforced boundaries** — implements the review-integrity checks of
§6.6, §6.7 and §6.9, and the record checks of §8.3 and §8.6. The remainder MAY
be enforced by review or additional tooling.

A project that declares sealed inputs relies on §3.9 and §5.8 as well, and a
conforming implementation MUST refuse both mechanically: a run whose frozen
artefacts changed, and a run that would read a sealed input without a valid
freeze.

`test/run_tests.sh` asserts those boundaries and the hardened review contract;
`test/conformance.py` injects one violation per boundary and records the refusals.

## 11. Security and evidence boundary

The protocol is a cooperative research-integrity system, not a hostile-code
sandbox or trusted timestamp authority. Local hashes detect later changes but do
not prove temporal priority against an actor controlling the filesystem. The
freeze journal detects a second freeze, a removed row and a deleted iteration;
an actor who rewrites the whole chain is outside this boundary unless freezes
are anchored outside the project (§3.6). Workflow tasks can write anywhere in the
project except declared inputs; the hashes detect such writes to declarations
and reviewed evidence afterwards, they do not prevent them. A
blind-review directory does not by itself prevent an agent from reading files it
has OS permission to access. The review terms and policy bound at claim (§6.7,
§6.9) are recorded in files the producer can write: the binding stops a
relaxation made through the configuration, not a forged claim record. Container
digests identify bytes but do not prove determinism or scientific validity.

External model services receive the context supplied to them. Local/HPC compute
does not imply air-gapped inference. These limits MUST NOT be described as
stronger guarantees in user-facing documentation.
