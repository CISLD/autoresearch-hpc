# Harness configuration

Which agent CLIs are available, how to invoke each non-interactively, and which
model family each belongs to.

The model family matters. A model reviewing its own output can reproduce the
same reasoning errors, so `arh ask` refuses a verification role from the same
configured family unless `--same-family` explicitly records a weaker check.

## Invocation

Each harness declares a command template. `{prompt}` is substituted with the
composed prompt; `{cwd}` with the working directory.

| harness | non-interactive form |
|---|---|
| `claude` | `claude -p "…"` |
| `codex` | `codex exec --skip-git-repo-check "…"` |
| `opencode` | `opencode run "…"` |
| `gemini` | `gemini -p "…"` |

## Roles

`arh ask --role <role>` composes a prompt from
`skills/cross-check/roles/<role>.md`. Shipped roles are `adversary`,
`reimplementer`, `estimand-auditor` and `gotcha-scanner`.

```arh-config
# Each iteration is bound to this file as it stood when the iteration was claimed. Changing it
# afterwards changes that iteration's review terms: arh ask then needs --terms-changed REASON.
harnesses = claude codex opencode

harness_claude_cmd      = claude -p {prompt}
harness_claude_family   = anthropic
harness_claude_version_cmd = claude --version

harness_codex_cmd       = codex exec --skip-git-repo-check {prompt}
harness_codex_family    = openai
harness_codex_version_cmd = codex --version

# OpenCode routes to several providers, so it has no model family until one is pinned.
# Left as `mixed` it cannot produce or verify an eligible review; pin the model and
# name its family, for example:
#   harness_opencode_cmd    = opencode run -m opencode-go/kimi-k3 {prompt}
#   harness_opencode_family = moonshot
harness_opencode_cmd    = opencode run {prompt}
harness_opencode_family = mixed
harness_opencode_version_cmd = opencode --version

harness_gemini_cmd      = gemini -p {prompt}
harness_gemini_family   = google
harness_gemini_version_cmd = gemini --version

# Who does what. `producer` is the agent that claims and pre-declares; `orchestrator` and
# `executor` split that work when you want one model planning and another implementing, and
# `arh delegate --role executor -n N` hands a bounded task to the named harness. Leave the two
# unset to keep a single agent doing both. `arh delegate list` shows what is configured.
producer     = claude
orchestrator =
executor     =

# How the work is driven. single: one producer session runs each iteration (arh delegate is
# optional). per-iteration: a main controller session talks to you, claims iterations and runs
# arh dispatch -n N, which starts a fresh controller session that owns iteration N: it
# pre-declares, calls the executor and the verifier, and hands back a summary. The verifier must
# then differ in model family from both the iteration controller and the executor.
orchestration = single
# The harness each dispatched iteration runs in (default: producer). Any CLI with a command
# template above can be one, including a meta-harness such as Omnigent.
iteration_controller =
max_parallel_iterations = 2
# A prefix for the controller's command, e.g. `srun -t 08:00:00 --mem 8G` to run it as a job
# (the compute node then needs to reach the model provider). Empty runs it here.
dispatch_launcher =
# Seconds before a controller is stopped; 0 for no limit.
dispatch_timeout = 0
# Environment for controllers, which run headless and must wait in the foreground.
dispatch_env = CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1

# Environment variables in which a harness reports its own session id. Every arh command on an
# iteration records the first one set in metadata/activity.jsonl, so the record names the agent
# sessions that acted on it (arh sessions -n N). Add your harness's variable if it sets one.
session_env = CLAUDE_CODE_SESSION_ID

verifier   = codex
# Whether a cross-check must come from a different model family than the producer. Keep this
# true unless you have a reason: a model does not reliably catch its own reasoning errors, so a
# same-family review is a weaker check. Set it false to accept an adversarial review from the
# producer's own family as a full cross-check -- and record why beside this line. Every review
# stores the value in force when it ran, so changing it later never revalidates or invalidates a
# review already taken.
require_foreign_family = true
# deny for a blinded study, where a producer must not look published results up:
# harness/install.sh then turns each harness's web tools off, and arh doctor checks them.
web_access = allow
# arh ask, arh delegate and arh evoke refuse to send a plan, report or task that carries something
# shaped like a credential (an API key, a token, a private key). off only for a recorded reason.
secret_scan = on
# Tried in order when the verifier cannot review: it refuses the content (arh ask exit 77) or is
# out of quota (exit 75). Each needs a concrete model family other than the producer's, e.g.:
# verifier_fallback = gemini
verifier_fallback =

ask_timeout = 900
# Delegations fall back to ask_timeout when delegate_timeout is unset.
delegate_timeout =
delegate_max_output_bytes = 262144
# One real iteration is a frozen pre-declaration (~16 kB) plus a report (~13 kB) plus the role
# prompt: ~30 kB. 24000 was too small to send the artefact under review (2026-09-16).
ask_max_input_bytes = 48000
ask_max_output_bytes = 8000
ask_output_words = 500
ask_max_rounds = 2
# How many times one UNSOUND review's rebuttal may be put to a reviewer (arh ask --rebuttal).
ask_max_adjudications = 1

# Blind replicators (arh replicate) run with a fresh home directory, so memory stores, chat
# history and plugins in your home (Claude Code auto-memory, Codex memories, claude-mem ...)
# cannot carry the original into a blind session. Only these login files are linked in, each as
# SOURCE or SOURCE:DEST (SOURCE relative to your home or absolute, $VARS expanded; DEST relative
# to the fresh home). Missing sources are skipped. `inherit` turns the fresh home off.
replicate_home = fresh
replicate_home_files = $CLAUDE_CONFIG_DIR/.credentials.json:.claude/.credentials.json .claude/.credentials.json $CODEX_HOME/auth.json:.codex/auth.json .codex/auth.json .local/share/opencode/auth.json .gemini/oauth_creds.json
# Variables that would point a harness back at your own configuration directory.
replicate_env_unset = CLAUDE_CONFIG_DIR CODEX_HOME
```

## Refusals, fallbacks and token usage

`arh ask` exits 75 when the provider refuses the call on a usage or rate limit, or on
authentication, and prints the provider's own line with any reset time it states. It
exits 77 when the provider refuses the content itself (a safety classifier). Neither
consumes a review round. After either, each harness in `verifier_fallback` is tried in
turn. A stated reset time is an upper bound, not a schedule: retry after a bounded wait.

A command template may contain `{usage}`, a file path the command can write a JSON
object of token counts or cost to; `arh ask` stores it in the review record as `usage`.
The framework's `harness/claude/review.sh` and `harness/codex/review.sh` do this. The
prompt stays the first argument, `{usage}` the second, CLI options follow:

    harness_claude_cmd = /path/to/autoresearch-hpc/harness/claude/review.sh {prompt} {usage} --model <model>
    harness_codex_cmd  = /path/to/autoresearch-hpc/harness/codex/review.sh {prompt} {usage} -m <model>

Command templates are parsed as quoted arguments without shell evaluation; use
a wrapper script for pipelines or environment setup. Reviews from `mixed` or
`unknown` families cannot satisfy the required foreign-family gate, and that
applies to the **producer's** family as much as the verifier's — so a router CLI
used as the producer must pin its model too. `arh doctor` and `arh ask` both
refuse such a configuration rather than letting it fail at the results gate. An unchanged
eligible review is reused without a model call. Deterministic execution, status
and context assembly do not call a model.

`harness_<name>_version_cmd` (optional) runs once before each review. Its first
output line is stored in the review record as `verifier_version`, so a verdict
can be traced to the CLI build that produced it. The family alone does not
identify the model. When the provider's default model must not drift between
reviews, pin it in the command template itself (for example
`codex exec -m <model> --skip-git-repo-check {prompt}`).
