---
name: replicate
description: Reconstruct a result as a discovery DAG, freeze it, then have agents independently re-implement from that specification without the original code.
---

# Discovery DAG and blind replication

The object under verification is the path from inputs to claim, not only the
final number.

```bash
arh dag init   -n N
arh dag check  -n N
arh dag freeze -n N
```

The DAG should expose orphan nodes, branch counts and decisions that narrative
reports can hide. Once frozen, it becomes the replication specification.

```bash
arh replicate -n N --agents 3 --harnesses codex,opencode,claude
arh replicate report -n N
```

Each agent runs with a fresh home directory (`replicate_home = fresh` in
`.arh/config/harnesses.md`): your harness's memory, history and plugins stay out
of a session that is meant to be blind, and only the login files listed in
`fresh_home_files` are linked in. If a harness cannot log in that way, add
its login file to that list rather than switching to `inherit`; an inherited
home is named in the report as unverified blindness.

Agents report values, set membership and ambiguities they had to resolve. Treat
agreement as evidence rather than confirmation; the useful signal in a fan-out
is disagreement, contested membership and specification ambiguity.
