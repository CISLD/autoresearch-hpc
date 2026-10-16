# Integrations

AutoResearch HPC keeps its own code to what the protocol needs: binding records to hashes and
refusing steps. Where a maintained tool already does a job, ARH calls it or links to it instead.
Every integration is optional; without the tool, ARH falls back to a simpler built-in behaviour
or leaves the job to the operator.

Each was checked on 2026-10-16 in a scratch home and a scratch, git-tracked ARH project on a
RHEL 9 cluster login node.

| Tool | Version checked | What ARH uses it for | Without it |
|---|---|---|---|
| [Entire CLI](https://github.com/entireio/cli) | 0.11.5 | transcripts, agent, model and tokens of the agent sessions behind an iteration | `arh sessions` lists ARH's own activity log only |
| [gitleaks](https://github.com/gitleaks/gitleaks) | 8.30.1 | maintained credential rules for every request ARH sends and every log it keeps | ARH's built-in token patterns |
| [basic-memory](https://github.com/basicmachines-co/basic-memory) | 0.23.2 | searching recorded findings (`knowledge/`) | a word match |
| [Omnigent](https://github.com/omnigent-ai/omnigent) | 0.18.0 | an iteration controller command for `arh dispatch` | harness CLIs directly (the default) |

## Entire CLI: agent sessions and transcripts

Entire records each agent session and, at every commit, stores a checkpoint (transcript, prompts,
tool calls, files, tokens) as a git ref and adds an `Entire-Checkpoint: <id>` trailer to the
commit. ARH reads those trailers for the commits that touched an iteration, and with `entire` on
PATH asks it for each checkpoint's agent, model, session and tokens.

```bash
cd <study>                                  # must be a git repository
entire enable --agent claude-code --telemetry=false --skip-push-sessions
# work as usual; commit iteration files; then
arh sessions -n N                           # checkpoints, with agent, model and tokens
entire checkpoint explain <id>              # the session itself
```

`entire enable` installs its hooks in the project's `.claude/settings.json` (or the agent's own
project configuration), not in your home directory. The conclusion receipt
(`metadata/conclusions.jsonl`) records the checkpoint ids and, with Entire installed, the model
each session ran: evidence that the harness configuration alone does not give. Checkpoints stay
local unless you push them (`--skip-push-sessions`); transcripts can hold host paths and data
excerpts, so check them before publishing a repository.

## gitleaks: credential rules ARH does not maintain

`secret_scanner = auto` (the default, `.arh/config/harnesses.md`) applies gitleaks's rules on top
of the built-in patterns whenever `gitleaks` is on PATH. That covers `arh ask`, `arh delegate`,
`arh evoke`, dispatch briefs and session logs, and `arh memory add`. A Slack webhook URL, which no
built-in pattern models, is refused and redacted. `secret_scanner = gitleaks` stops a request when
gitleaks is missing; `builtin` never calls it. Install the release binary on PATH:
<https://github.com/gitleaks/gitleaks/releases>.

## basic-memory: searching findings

`arh memory add` writes each finding of a concluded iteration as a Markdown file with YAML front
matter under `knowledge/`. To search them with basic-memory:

```bash
bm project add arh-knowledge <study>/knowledge
# in basic-memory's config.json: "disable_permalinks": true, "ensure_frontmatter_on_sync": false
bm reindex --project arh-knowledge
```

and in `.arh/config/harnesses.md`:

```text
memory_search_cmd = bm tool search-notes {query} --project arh-knowledge
```

Then `arh memory search QUERY` hands the query to basic-memory, which also serves the findings to
any MCP-capable agent (`bm mcp`). The two settings matter: by default basic-memory rewrites each
note's front matter on sync (quotes, lists, a permalink). ARH still reads a rewritten finding, but
the file is then no longer as ARH wrote it.

## Omnigent: not usable on this cluster yet

Omnigent can start an agent headless (`omnigent run --harness codex -p ...`), so it could be an
`iteration_controller` command for `arh dispatch`. On the RHEL 9 login node it did not run: its
managed terminals need tmux 3.3 or newer (the node has 3.2), and its Claude SDK path started Claude
Code but lost the connection (`ECONNRESET`), while plain `claude -p` worked from the same home. It
is labelled alpha; ARH has no Omnigent-specific code, and a site where it runs can name it in a
harness command template like any other CLI. Telemetry: `OMNIGENT_DISABLE_TELEMETRY=1`.

## Harness logins under a fresh home

`arh replicate` (and `arh dispatch` with `dispatch_home = fresh`) run agents with a fresh home
holding only the login files in `fresh_home_files`. Checked with real logins: Claude Code and
Codex. OpenCode started and reached its provider but could not be confirmed (the account was out
of credits); the Gemini CLI entry is untested. A fresh home also hides a harness's user-level
settings, so pin the model in the harness command template.
