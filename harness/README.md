# Harness wiring

One source of truth — `AGENTS.md` at the repo root — is served to each harness
in its own idiomatic form. These files point at the contract rather than
restate it.

Install into a project with:

```bash
./harness/install.sh <project-dir> [harness...]
```

| harness | reads | this directory provides |
|---|---|---|
| Claude Code | `CLAUDE.md`, `.claude/skills/` | symlink to `AGENTS.md`; skills copied in |
| Codex CLI | `AGENTS.md`, `.codex/config.toml` | profile with the protocol approval posture |
| OpenCode | `AGENTS.md`, `opencode.json` | agent definitions per cross-check role; pin a model, or its family stays `mixed` |
| Cursor / Copilot | `AGENTS.md` | nothing extra needed |

For reviews, `claude/review.sh` and `codex/review.sh` wrap the CLIs so `arh ask`
records token usage (`{usage}` in the command template; see `config/harnesses.md`).
Running producer sessions unattended is covered in
[`docs/headless.md`](../docs/headless.md).

Adding a harness means keys in `.arh/config/harnesses.md`
(`harness_<n>_cmd`, `harness_<n>_family`, and the name in `harnesses`) plus any
native config here. Use `arh doctor` to check the configured producer/verifier
families and installed CLIs.

## What has actually been exercised

A shipped entry is not evidence that a harness works. These combinations ran headless, on a
Slurm cluster, through the replication benchmark of September 2026 that the SoftwareX paper
reports: eleven published studies and one informed re-run, 153 producer sessions. The counts
are from its run records. Anything absent from the table ships as configuration only.

| harness | as producer | as verifier |
|---|---|---|
| Claude Code 2.1.270–2.1.281 | Claude Opus 5: 116 sessions; Claude Sonnet 5: 12 sessions | 19 reviews with a verdict; 7 calls failed without a recorded error |
| Codex CLI 0.154.0–0.155.0 | GPT-6 Astra, `xhigh` effort: 22 sessions | 17 reviews with a verdict; 63 calls stopped by usage limits, 5 by content refusals |
| OpenCode 1.14.50 | Kimi K3 (`opencode-go/kimi-k3`): 3 sessions | 12 reviews with a verdict from Kimi K3 (3 more calls exited 0 without one); attempted with a Qwen model, none completed |
| Gemini CLI | not exercised | not exercised |
| Cursor, Copilot | not exercised | not exercised |

A review record stores the verifier's CLI build, not its model, so the verifier column names
no model. Of 126 reviewer calls, 75 (60%) failed, 63 of them on usage limits: an unattended
study needs a fallback verifier (`verifier_fallback`) or it waits. Verdicts are counted from the
studies' `CROSSCHECK_*.md.json` records; a call that exits 0 without a `VERDICT:` line is not a
review.
