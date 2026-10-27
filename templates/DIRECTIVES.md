# Directives and durable knowledge — {{PROJECT}}

Facts that must outlive any one agent session: what the operator decided, where
the data are, and what was learned outside the project. `arh context` shows every
session the current directives below; every agent writes here, not to a harness's
private memory, as soon as it learns such a fact. Private memory may keep a
pointer to this file, never the fact itself: no other harness, account or
reviewer can see it.

Entries are dated and append-only. A directive that changes gets a new entry
naming the one it supersedes. Each entry says where it came from and under which
conditions it holds, so a later session can tell whether it is still current.

`arh claim` records this file's hash, `arh delegate` hands it to an executor,
and `arh ask` points the reviewer at it, so a review checks the work against the
same directives the producer followed.

## Current directives

<Every directive still in force, one line each, with the dated entry below it
comes from. `arh context` prints this section in full; without it a session has
to read this whole file. Update it when a directive is added or superseded.>

## Operator directives

<!-- One entry per directive, newest last.

### YYYY-MM-DD — short title
**Source:** who gave it, and where (message, meeting, issue)
**Directive:** verbatim, or a close paraphrase
**Applies to:** iterations, data, scopes
**Supersedes:** an earlier entry, or none
-->

## Data inventory

<!-- Where the data are. Declare each location in immutable_inputs in
.arh/config/project.md, or in sealed_inputs if only a frozen confirmation may
read it.

### YYYY-MM-DD — dataset
**Location:** absolute path
**What it is:** samples, assay, version, provenance
**Checked:** date and how (checksum, samtools quickcheck, record count)
-->

## External findings

<!-- Literature, tool release notes, upstream benchmarks: anything learned
outside the project that a design depends on.

### YYYY-MM-DD — title
**Source:** citation, DOI or URL
**Finding:** what it says, in one or two sentences
**Holds under:** versions, data, conditions
**Last checked:** date
-->
