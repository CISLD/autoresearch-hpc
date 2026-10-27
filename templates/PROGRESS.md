# PROGRESS — {{PROJECT}}

**Single source of truth for project state.** Last updated: **{{DATE}}**.

This file exists so state never has to be reconstructed from chat history.
Anyone — person, agent or harness — picking this project up reads this file first
and knows what is done, what is running and where to resume.

> **Maintenance rule.** Update this file whenever an iteration changes status.
> Run `arh ledger render` to regenerate the status table, and `arh ledger check`
> to prove the table still matches what is on disk.

---

## Current state

<Kept current by whoever changes the state: what is concluded, what runs, what is
blocked and what comes next, in a few lines. `arh context` prints this section and
not the rest of the file, so a resuming session starts here. History goes below.>

## 1. The study in one box

| Item | Value |
|---|---|
| Question |  |
| Design |  |
| Units / n |  |
| Primary data |  |
| Immutable inputs |  |
| Reference / baseline |  |

## 2. Conventions that must not be broken

- **Iterations are append-only.** Corrections are new iterations; superseded
  files remain intact.
- **Pre-declaration precedes results.** `arh gate predeclare` freezes the README
  hash; `arh gate results` refuses a changed declaration.
- **Claim before you create.** `arh claim` is the only supported way to take an
  iteration number.
- **Immutable inputs stay immutable.** Bind them read-only and keep output under
  the project root.
- **Standing rules are inherited.** See `rules/`.

## 3. Status

<!-- arh:status:begin -->
<!-- arh:status:end -->

## 4. What each iteration established

<one paragraph per concluded iteration: the claim, strongest limit, and any
supersession. Never rewrite the superseded entry.>

## 5. Currently running

<job ids, what they are, where their logs land>

## 6. Resume points — do these next

<the next actions, most recent first, with enough context for a cold resume>
