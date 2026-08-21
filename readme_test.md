<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/mark-dark.svg">
  <img src="assets/brand/mark-light.svg" alt="mergeCraft logo" width="120"/>
</picture>

# mergeCraft

**AI-powered PR review as a standalone, BYOK GitHub Action.**
No SaaS account. No dashboard. Your repo, your keys, your reviewers.

[![CI](https://github.com/alexhawat/mergeCraft/actions/workflows/ci.yml/badge.svg)](https://github.com/alexhawat/mergeCraft/actions/workflows/ci.yml)
[![CodeQL](https://github.com/alexhawat/mergeCraft/actions/workflows/codeql.yml/badge.svg)](https://github.com/alexhawat/mergeCraft/actions/workflows/codeql.yml)
[![Docker](https://github.com/alexhawat/mergeCraft/actions/workflows/docker.yml/badge.svg)](https://github.com/alexhawat/mergeCraft/actions/workflows/docker.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![uv](https://img.shields.io/badge/install-uv-261230.svg)](https://docs.astral.sh/uv/)

[Agent skill](skills/mergecraft/SKILL.md) · [AGENTS.md](AGENTS.md) · [llms.txt](llms.txt)

[**For LLM / Agents**](#for-agents) ·
[Problem](#problem) ·
[How it works](#how-it-works) ·
[Install](#install) ·
[Features](#features) ·
[Docs](#docs)

</div>

---

<span id="for-agents"></span>

## For LLM / Agents

> ### Skip all this — I just want my LLM to do it.
>
> Open your coding agent in the repo you want reviewed, hit the copy button on
> the block below, and paste. That is the whole install.

```text
Set up mergeCraft (BYOK AI PR review) in this repository.

Reference: https://github.com/alexhawat/mergeCraft/blob/main/AGENTS.md

Do all of this yourself, without asking me, except where step 4 says STOP:

1. Ensure `uv` is on PATH. If it is missing, install it:
     curl -LsSf https://astral.sh/uv/install.sh | sh     # macOS/Linux
     powershell -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
   Do NOT install Python. uv downloads a compatible interpreter on its own.

2. Install the CLI:
     uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"
     mergecraft --version

3. Scaffold config + workflow (non-interactive, writes no secrets):
     mergecraft init
   This creates .mergecraft/config.yaml, .github/workflows/mergecraft.yml,
   and .mergecraft/learnings.md.

4. STOP and hand the credential step back to me. Do not read, generate, guess,
   echo, or commit any API key, token, or .env file. Print the single command
   you want me to run, picking the provider from this list and asking me which
   one I have:
     mergecraft auth claude     # Claude Pro/Max subscription
     mergecraft auth codex      # ChatGPT Plus/Pro/Team/Enterprise
     mergecraft auth gemini     # Google AI Studio key
     mergecraft auth cursor     # Cursor Cloud key
     mergecraft auth nous       # Nous Portal key
     mergecraft auth tokenhub   # Tencent TokenHub key
     mergecraft auth minimax    # MiniMax key
   Any other OpenAI-compatible endpoint also works — if I say "something else",
   read docs/authentication.md and set up the custom-provider env pair instead.
   Each command stores a GitHub Actions secret for me via `gh secret set`.

5. After I confirm the credential is stored, set `models:` in
   .mergecraft/config.yaml to a fallback chain whose first entry matches the
   provider I authenticated. Then run `mergecraft doctor` and fix anything it
   reports that is not the credential itself.

6. Commit ONLY .mergecraft/config.yaml, .mergecraft/learnings.md, and
   .github/workflows/mergecraft.yml on a new branch. Never commit secrets.
   Open a pull request titled "ci: add mergeCraft AI PR review".

7. That PR is the first review target. Tell me to watch the `mergecraft-approval`
   check on it, and that I can re-run a review any time by commenting
   `@mergecraft review`.

Finally, print a short summary: provider chosen, files added, PR link, and the
exact command I still need to run (if any).
```

### Also teach your agent to *use* mergeCraft

The prompt above installs the reviewer. This one installs mergeCraft's own
knowledge into your agent, so *"review my diff"* and *"why did the mergecraft
check fail?"* work natively afterwards.

```text
Install the mergeCraft agent skill into this repo so you know its CLI,
config keys, exit codes, and failure modes.

1. Fetch the skill:
     git clone --depth 1 https://github.com/alexhawat/mergeCraft /tmp/mergecraft-src

2. Copy skills/mergecraft/ to the path your agent reads. Almost every agent
   now shares one location -- the Agent Skills standard path:

     .agents/skills/mergecraft/   -> Codex, Cursor, OpenCode, Gemini CLI,
                                     OpenClaw
     .claude/skills/mergecraft/   -> Claude Code (it does NOT read
                                     .agents/skills/); OpenCode reads it too
     hermes skills install        -> Hermes Agent (uses ~/.hermes/skills/)

   If your agent is none of these, copy AGENTS.md and llms.txt to the repo
   root -- every agent reads those.

3. Also copy commands/ to your agent's slash-command directory if it has one
   (Claude Code: .claude/commands/).

4. rm -rf /tmp/mergecraft-src

5. Confirm by summarising, from the skill you just installed: what the
   `mergecraft-approval` check is a function of, and what exit code 11 means.
```

<details>
<summary><b>Per-agent one-liners</b> — Claude Code, Cursor, Codex, OpenCode, Gemini, Copilot, OpenClaw, Hermes</summary>

<br/>

**Claude Code** — the only *packaged* install. Skill + slash commands in one step:

```text
/plugin marketplace add alexhawat/mergeCraft
/plugin install mergecraft@mergecraft
```

Then: `/mergecraft-setup` to scaffold, `/mergecraft-review` to review a local diff.

**Cursor** (chat or composer):

```text
Read https://github.com/alexhawat/mergeCraft/blob/main/AGENTS.md and set
mergeCraft up in this repo. Install the CLI with uv (uv fetches its own Python —
do not install Python), run `mergecraft init`, wire .mergecraft/config.yaml, and
open a PR with the workflow. Print the `mergecraft auth <provider>` command for
me to run myself — never touch credentials. Then copy the repo's
skills/mergecraft/ into .agents/skills/mergecraft/ so you keep the knowledge.
```

**Codex CLI / ChatGPT cloud agent:**

```text
Task: make this repo use mergeCraft for AI PR review.
Read https://github.com/alexhawat/mergeCraft/blob/main/AGENTS.md first.
Create a branch that adds .github/workflows/mergecraft.yml, pinning the action
to a full 40-character commit SHA you resolved from the repo (never an invented
tag), plus a .mergecraft/config.yaml whose `models:`
chain starts with openai/gpt-5.3-codex. Open a PR. I will add the
CODEX_AUTH_JSON secret myself — do not handle credentials.
```

**OpenCode** — mergeCraft's generic multi-provider harness; use it when your
model is not Anthropic/OpenAI/Google:

```text
Set up mergeCraft in this repo per
https://github.com/alexhawat/mergeCraft/blob/main/AGENTS.md, using the opencode
harness. Install with uv, run `mergecraft init`, then set in
.mergecraft/config.yaml:
    harness: opencode
    models: ["<my-provider>/<my-model>"]
Read docs/authentication.md and tell me exactly which
MERGECRAFT_CUSTOM_PROVIDER_BASE_URL / MERGECRAFT_CUSTOM_PROVIDER_API_KEY pair
to set as GitHub secrets for my endpoint. Do not handle the key yourself.
Copy skills/mergecraft/ into .agents/skills/mergecraft/. Open a PR.
```

**Gemini CLI:**

```text
Set up mergeCraft in this repo. Follow
https://github.com/alexhawat/mergeCraft/blob/main/AGENTS.md. Install with uv
(do not install Python), run `mergecraft init`, set `models:` to
["google/gemini-3.1-pro-preview"] in .mergecraft/config.yaml, and open a PR
with the workflow. Print `mergecraft auth gemini` for me to run — do not
handle the API key.
```

**GitHub Copilot** (CLI or VS Code) — Copilot already reads
[`.github/copilot-instructions.md`](.github/copilot-instructions.md), which
points at `AGENTS.md`:

```text
Following AGENTS.md, add mergeCraft PR review to this repo: uv tool install the
CLI, `mergecraft init`, commit the config + workflow on a branch, open a PR, and
print the `mergecraft auth` command for me. Do not commit secrets.
```

**OpenClaw / Hermes / any autonomous shell agent** — these have no mergeCraft
package; give them the machine-readable entry point and let them plan:

```text
Read https://raw.githubusercontent.com/alexhawat/mergeCraft/main/llms.txt —
it is a curated map of this project's docs. Then read AGENTS.md and
docs/authentication.md. Goal: install mergeCraft as the PR reviewer for the
repo in the current working directory.

Constraints:
  - `uv` is your only prerequisite; it provisions Python itself.
  - `mergecraft init` is non-interactive and safe to run unattended.
  - `mergecraft auth *` is interactive and MUST be escalated to a human.
    Never fabricate, log, or commit a credential.
  - `mergecraft review --agent` streams versioned JSONL on stdout — use that,
    not screen-scraping, if you want to consume review results.
  - Exit codes are contractual: 0 pass, 10 findings, 11 blocking, 20
    inconclusive, 30 config error, 40 provider/infra, 50 timeout.
    See docs/EXIT-CODES.md.

Produce a plan, execute it, then open a PR and report the escalation you need.
```

</details>

### What the agent still needs from you

| | Why | How long |
|---|---|---|
| **One provider credential** | `mergecraft auth …` is an interactive login (or a key paste). A well-behaved agent stops here rather than touching your secrets. | ~1 minute, once |
| **`gh` logged in** *(optional)* | Lets `mergecraft auth` store the secret for you via `gh secret set`. Without it, you get the secret name to paste into GitHub Settings. | ~1 minute, once |

Everything else — install, scaffold, config, commit, PR — is unattended.
`mergecraft init` writes no secrets and needs no network.

### Why agents are good at this

| Surface | What it gives an agent |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Cross-vendor setup + contribution guidance, read natively by Codex, Cursor, OpenCode, Gemini CLI and Copilot |
| [`skills/mergecraft/SKILL.md`](skills/mergecraft/SKILL.md) | Agent-Skills package: setup checklist, CLI map, config keys, troubleshooting |
| [`llms.txt`](llms.txt) · [`llms-full.txt`](llms-full.txt) | Curated doc map, and the full corpus in one file |
| [`.claude-plugin/`](.claude-plugin/plugin.json) · [`commands/`](commands/) | Claude plugin manifest and `/mergecraft-setup` · `/mergecraft-review` |
| `mergecraft review --agent` | Versioned JSONL event stream (`run_started` · `phase` · `finding` · `verdict` · `run_finished`) for orchestrators |
| `mergecraft review --json out.json` | Structured findings on disk |
| [`docs/EXIT-CODES.md`](docs/EXIT-CODES.md) | Contractual exit codes — branch on them instead of parsing text |
| `mergecraft doctor` | Self-diagnosis of git, providers, analyzers, auth, config and MCP wiring |
| `mergecraft mcp serve` | The reviewer's own MCP tool surface, Bearer-authenticated |

> **Reviewing *with* an agent, locally:** `mergecraft review` works offline on a
> local diff, worktree, or cloned repo — no GitHub Action required.
> See [`docs/cli.md`](docs/cli.md).

<sub>Skill paths follow the [Agent Skills](https://agentskills.io/specification)
open standard, verified against each tool's own docs on 2026-08-21. `AGENTS.md` at the
repo root is the fallback every one of them reads.</sub>

---

## Problem

Three reasons teams pick mergeCraft over hosted reviewers:

### Hosted SaaS → BYOK

Bring your own Claude Pro/Max or ChatGPT subscription, an API key, or any
OpenAI-compatible endpoint. Credentials and code stay inside GitHub Actions and
this repo's code — no proprietary backend.

### Vibes → evidence + verifier

Deterministic analyzers settle mechanically checkable facts; the LLM only judges
what is left, and a second read-only verifier re-reads every Critical/Major
finding before it is published.

### Lock-in → MIT Action

One Docker action, one YAML workflow, MIT-licensed Python you can read end to end.
Inspired by [pullfrog](https://github.com/pullfrog/pullfrog) and CodeRabbit.

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/diagrams/pipeline-dark.svg">
  <img src="assets/diagrams/pipeline-light.svg" alt="mergeCraft review pipeline: PR event through trust tier, analyzers, review agent, verifier, and typed findings">
</picture>

A pull request event resolves a **trust tier**, runs the matching **analyzers**,
then a **review agent** and a read-only **verifier** produce **typed findings**
that drive inline comments, the `mergecraft-approval` check, and optional SARIF
upload. Trust-tier details and advanced workflow patterns live in
[`docs/workflows.md`](docs/workflows.md).

## Install

*Prefer to let an agent do this? [Jump back up.](#for-agents)*

> **Requirements:** [uv](https://docs.astral.sh/uv/) and one provider credential.
> uv provisions its own Python — you do not need a system Python.
> An authenticated [GitHub CLI](https://cli.github.com) is optional, and only
> makes `mergecraft auth` store the secret for you.
> Other paths (Docker-only, no local install at all): [`docs/install.md`](docs/install.md).

1. **Install the CLI and scaffold the repo:**

```bash
uv tool install "merge-craft @ git+https://github.com/alexhawat/mergeCraft"
mergecraft init   # writes .mergecraft/config.yaml + .github/workflows/mergecraft.yml
```

2. **Authenticate** a provider (subscription recommended — no metered API billing):

```bash
mergecraft auth claude   # Claude Pro/Max
# or: codex · gemini · cursor · nous · tokenhub · minimax
```

The credential is stored as a GitHub Actions secret via `gh secret set`. Add
`--scope local` to write a local `.env` instead, for offline `mergecraft review`.
More providers, custom gateways and model chains:
[`docs/authentication.md`](docs/authentication.md).

3. **Trigger a review** — open a pull request, comment `@mergecraft review`, or
   run the workflow via `workflow_dispatch`.

```bash
mergecraft doctor   # optional: verify git, providers, analyzers, auth, config, MCP
```

### Example 1 — auto-review every PR

```yaml
# .github/workflows/mergecraft.yml
name: mergeCraft
on:
  pull_request:
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write
  issues: write
  id-token: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: alexhawat/mergeCraft@9cdd46d2f5521e663ad8f895ccd87b8fe8c15301
        env:
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
```

> Pin to a full commit SHA (as above) or a git tag once one exists — never a tag
> that is not in the repository. To verify a published image's Cosign signature,
> see [CONTRIBUTING.md § Verify a published image](CONTRIBUTING.md#verify-a-published-image).

More patterns — comment triggers, fork-safe `pull_request_target`, SARIF,
scheduled runs: [`docs/workflows.md`](docs/workflows.md).

## Features

| | |
|---|---|
| 🔍 **Deep PR review** | Correctness, risk, blast-radius and hygiene lenses; inline findings + narrative verdict |
| 🧰 **Deterministic analyzers** | actionlint, zizmor, ShellCheck, Hadolint and more — verified hits only |
| ✅ **Structural approval gate** | `mergecraft-approval` is a pure function of typed findings |
| 🔁 **Model fallback chains** | Ordered `models:` with per-slug fallbacks — see [`docs/authentication.md`](docs/authentication.md#chain-semantics--model-37--w4) |
| 🛡️ **Trust tiers** | Fork PRs and `pull_request_target` degrade to untrusted: no secrets, read-only analyzers |
| 🤖 **Agent-native** | `--agent` JSONL protocol, contractual exit codes, MCP server, shipped skill + plugin |
| 📡 **SARIF upload (opt-in)** | Publish analyzer findings to GitHub code scanning |
| 📈 **Tracing (opt-in)** | Span trees to JSONL, Logfire, or OTLP — [`docs/TRACING.md`](docs/TRACING.md) |
| 💻 **Offline mode** | `mergecraft review` on local diffs, worktrees, or cloned repos |

**Terminal verdict (default: enforce).** A run without a validated
`submit_review_verdict` reports `inconclusive`. Set `gates.terminal_verdict: shadow`
in `.mergecraft/config.yaml` to log diagnostics only.

## Authentication

| Provider | Subscription (recommended) | API key |
|----------|-----------------------------|---------|
| Anthropic Claude | `mergecraft auth claude` → `CLAUDE_CODE_OAUTH_TOKEN` | `ANTHROPIC_API_KEY` |
| OpenAI Codex | `mergecraft auth codex` → `CODEX_AUTH_JSON` | `OPENAI_API_KEY` |
| Google Gemini | `mergecraft auth gemini` → `GEMINI_API_KEY` | `GEMINI_API_KEY` |
| Cursor Cloud | `mergecraft auth cursor` → `CURSOR_API_KEY` | `CURSOR_API_KEY` |
| Nous Portal | — | `mergecraft auth nous` → `NOUS_API_KEY` |
| Tencent TokenHub | — | `mergecraft auth tokenhub` → `TOKENHUB_API_KEY` |
| MiniMax | — | `mergecraft auth minimax` → `MERGECRAFT_CUSTOM_PROVIDER_API_KEY` |
| **Anything OpenAI-compatible** | — | `MERGECRAFT_CUSTOM_PROVIDER_BASE_URL` + `…_API_KEY` (indexed `_1`, `_2`, … for several at once) |
| Logfire tracing | `mergecraft auth logfire` | see [`docs/TRACING.md`](docs/TRACING.md) |

Harnesses: `claude` · `codex` · `gemini` · `opencode` · `cursor`. When `harness:`
is unset, mergeCraft infers it from the model slug; OpenAI-compatible models
route to the OpenCode harness. Full matrix:
[`docs/compatibility-matrix.md`](docs/compatibility-matrix.md) ·
[`docs/authentication.md`](docs/authentication.md).

## Docs

| Doc | What it covers |
|-----|----------------|
| [`AGENTS.md`](AGENTS.md) | Agent entry point — consumer setup and contributing |
| [`docs/install.md`](docs/install.md) | Action vs CLI vs Docker install paths |
| [`docs/authentication.md`](docs/authentication.md) | Providers, custom gateways, model fallback chains |
| [`docs/workflows.md`](docs/workflows.md) | Examples 2–6, trust tiers, `pull_request_target` gotchas |
| [`docs/cli.md`](docs/cli.md) | Full `mergecraft` command reference |
| [`docs/action-reference.md`](docs/action-reference.md) | Every Action `with:` input and output |
| [`docs/EXIT-CODES.md`](docs/EXIT-CODES.md) | Contractual CLI exit codes |
| [`REVIEW-CHECKS.md`](REVIEW-CHECKS.md) | Every check a review applies — lenses, gates, grading |
| [`docs/ANALYZERS.md`](docs/ANALYZERS.md) | Analyzer catalog, trust tiers, SARIF upload |
| [`docs/compatibility-matrix.md`](docs/compatibility-matrix.md) | Supported events, agents, providers, shell/push modes |
| [`SECURITY.md`](SECURITY.md) | Threat model, trust tiers, reporting |
| [`docs/`](docs/) | Full generated index |

## Development

```bash
make setup      # uv sync + pre-commit
make lint       # ruff
make typecheck  # mypy strict
make test       # pytest
make ci         # full gate
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contributor workflow.

## License

MIT — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
