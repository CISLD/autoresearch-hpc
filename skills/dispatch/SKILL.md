---
name: dispatch
description: Work as a main controller that plans questions and dispatches each iteration to its own controller session, then reads the summaries they hand back.
---

# Main controller and per-iteration controllers

With `orchestration = per-iteration` in `.arh/config/harnesses.md`, you are the
main controller: you talk to the operator, decide which questions to pursue,
claim iterations and dispatch each to a fresh controller session. You do not
pre-declare, run or review an iteration yourself.

```bash
arh claim -t "the question" [--continues M]     # returns N
arh dispatch -n N --brief brief.md --detach     # a controller session owns N until it reports
arh dispatch status                             # running controllers and their hand-backs
arh wait -n N                                   # block until N's controller has finished
```

The brief says what the iteration is to find out and anything the controller
must know (earlier results it builds on, operator directives). The controller
pre-declares, implements (itself or through `arh delegate --role executor`),
has the work reviewed with `arh ask`, runs the results gate and hands back a
summary with `arh dispatch report`. Read that summary and the ledger, not the
controller's transcript; the transcript is kept, with credential-shaped text
removed, under `iterations/iterationN/metadata/dispatch/`.

While a controller holds an iteration, `arh` refuses to change it from any
other session, yours included. Every dispatched iteration stays in the record
and counts as an attempt at its question: dispatching several and keeping the
one that worked shows as several attempts in the ledger.

The reviewer must come from a different model family than both the iteration
controller and the executor. `max_parallel_iterations` limits how many
controllers run at once, and `dispatch_launcher` can start them under the site
scheduler.
