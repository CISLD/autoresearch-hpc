---
name: cross-check
description: Have a different agent harness review an iteration as adversary, re-implementer, estimand auditor, or gotcha scanner before concluding it.
---

# Cross-check with a foreign harness

```bash
arh ask --role adversary -n N
arh ask --role reimplementer -n N --harness codex
arh ask --role estimand-auditor -n N
arh ask --role gotcha-scanner -n N
```

A same-family review can reproduce the producer's reasoning errors. `arh ask`
therefore requires a distinct configured model family for a review that satisfies
the results gate. `--same-family` records a weaker check.

Configure harnesses in `.arh/config/harnesses.md`.

A provider refusal is not a review and spends no round. Exit 75 is a usage or rate
limit, authentication or a timeout: retry after a bounded wait; the reset time
printed is an upper bound, not a schedule. Exit 77 means
the provider refused the content; `arh ask` then tries each harness in
`verifier_fallback`, which must be another model family than the producer's.

Every run writes a `CROSSCHECK_<role>_<harness>_<timestamp>.md` record and
execution metadata. The verdict is **evidence, not a ruling**. Evaluate each
finding, record dispositions and reasons, and preserve disagreements rather than
silently deleting inconvenient review output.

The reviewer is asked to number its findings (`F1:`, `F2:` ...). Answer each in
`REVIEW_RESPONSE.md` by its id, with a decision word (accepted, rejected, fixed,
deferred, disputed) and the reason; with several reviews, put each review's
answers under a heading that names its `CROSSCHECK_...` file. `arh gate results`
lists every finding and fails while one is unanswered (`review_response` in
`project.md`).

An `UNSOUND` verdict is answered as a whole, in the same place:
`Verdict: rebutted, because <reason>` when the iteration stands despite it, or
`Verdict: accepted` when it does not. An accepted one leaves the iteration
unconcluded, and the correction is a new iteration. A second, milder review does
not answer the first.

A rebuttal is then judged by a reviewer, not by you:

```bash
arh ask --rebuttal -n N            # the reviewer who said UNSOUND answers WITHDRAWN or MAINTAINED
```

The judgment is written to `REBUTTAL_<harness>_<timestamp>.md`, bound to the
review and to your rebuttal's text; editing the rebuttal afterwards voids it.
The gate passes only on `WITHDRAWN` (`unsound_review = require-adjudication`,
the default). A `MAINTAINED` verdict stands: leave the iteration unconcluded and
correct it in a new one. One judgment per review (`ask_max_adjudications`).
