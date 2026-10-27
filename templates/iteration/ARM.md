# Iteration {{N}} · Arm {{ARM}} — {{TITLE}}

**Status: DRAFT (claimed {{DATE}}); arh gate predeclare stamps the freeze date here.**
Inherits iteration {{N}}'s question, estimand and standing rules. This file
states only what is *specific to this arm*.

## 1. What this arm tests

<the sub-question, and why it is a separate arm rather than part of another>

## 2. Acceptance criteria

<gates on this arm's run, checked before interpretation. An arm can fail its
criteria while its siblings pass; that is the point of arms.>

## 3. Negative control

<the set expected to be null in THIS arm. An arm without its own control
inherits nothing useful from its siblings.>

## 4. Fate

Set on conclusion to exactly one of:

| fate | meaning |
|---|---|
| `CONCLUDED` | ran, produced an interpretable result |
| `NULL` | ran cleanly, found nothing above its detection limit |
| `INFEASIBLE` | could not be run as designed — say what stopped it |
| `KILLED_BY_CONTROL` | produced a positive that its own negative control also produced |
| `ABANDONED` | dropped before completion — say why |

**`INFEASIBLE` and `KILLED_BY_CONTROL` are results and must be reported.** An
arm quietly dropped because it did not work is the commonest way a multi-arm
iteration overstates itself: the surviving arms look like the whole design.

**Fate:** `PLANNED`
