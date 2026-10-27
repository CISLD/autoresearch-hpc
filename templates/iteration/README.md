# Iteration {{N}} — {{TITLE}}

**Status: DRAFT (claimed {{DATE}}); arh gate predeclare stamps the freeze date here.**
**Claimed by:** {{AGENT}} (`CLAIM.json`).

> Complete every section below, then run `arh gate predeclare -n {{N}}`. The gate
> freezes this file's hash. After that it is immutable: a correction is a new
> iteration, never an edit to this one.

## 1. Question

<state the single question this iteration answers, and why it is not already
answered by an earlier iteration>

## 2. Estimand

<the quantity being estimated, in its own units — not the test, the quantity.
State it precisely enough that someone could compute it a different way and get
a comparable number. Most silent failures in a discovery loop are a technically
correct computation of the wrong quantity.>

## 3. Instrument

<tools and exact versions, the container image each runs in, references and
their accessions, and the seed. Name an image declared in site.md so the run is
pinned; an unpinned tool is not an instrument.>

Code this iteration imports from another iteration's `scripts/` is declared
here, so its hash is frozen with this plan and checked at every submit
(space-separated, relative to the project root; leave empty if none):

```arh-config
imports =
```

Commands the instrument depends on, one per line, are run once in their image by
`arh gate predeclare` before the plan is frozen, so a wrong flag or a missing
tool fails here and not on the first real task (`runtime` is the task image;
`name:` selects `image_<name>`; lines starting with `#` are skipped):

```arh-smoke
# runtime: python3 -c 'import sklearn; print(sklearn.__version__)'
# vg: vg call --help
```

## 4. Acceptance criteria

<what must be true for this iteration to have run correctly, checked before any
interpretation: input integrity, record-count reconciliation, expected row and
sample counts, non-empty outputs. These are gates on the run, not on the result.>

## 5. Negative controls

<the set expected to be null, named here and not after the result. State how it
would behave if the pipeline were working, and if it were not.>

## 6. Detection limit

<the smallest effect this design could detect, in the units of the estimand,
with the basis for that number. A candidate may be excluded by a stated
detection limit; it may never be excluded by an unexamined threshold.>

## 7. Prediction

<what you expect to happen, recorded before you know. A prediction that turns
out wrong is a result worth keeping — record it, do not revise it.>

## 8. Limits of the conclusion

This iteration inherits the project's standing rules:

{{RULES}}

<add any limit specific to this design: what it cannot separate, what it does
not measure, and which of its outputs remain candidates rather than findings.>
