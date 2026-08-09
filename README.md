# mergeCraft

Standalone **BYOK** GitHub Action for AI-powered PR review — inspired by prior
work including [pullfrog](https://github.com/pullfrog/pullfrog) and CodeRabbit.

No proprietary SaaS account is required. Settings, learnings, and secrets
come from your repo and GitHub Actions secrets — **you bring your own
Claude subscription, API key, or other provider credential.**

## Requirements

- Python **3.14+**
- [uv](https://docs.astral.sh/uv/)
- [GitHub CLI (`gh`)](https://cli.github.com), authenticated (`gh auth login`) — used by `mergecraft auth` and `mergecraft init`
- A credential for at least one provider — see [Authentication](#authentication) below

## Get started in 3 steps

1. **Install and scaffold** in the repo you want reviewed (not yet published to
   PyPI, so install straight from git):

   ```bash
   uv tool install "git+https://github.com/alexhawat/mergeCraft@pre-0.0.1"
   mergecraft init   # writes .mergecraft/config.yaml + .github/workflows/mergecraft.yml
   ```

   Working on mergeCraft itself instead? Clone it and run
   `uv sync --extra dev && uv run mergecraft --help`.

2. **Authenticate** — pick one:

   ```bash
   mergecraft auth claude   # use your Claude Pro/Max subscription (no per-token API billing)
   # or
   mergecraft auth codex    # use your ChatGPT subscription (ChatGPT Plus/Pro/Team/Enterprise)
   ```

   Either command saves the credential as a GitHub Actions secret in the current repo via `gh secret set`. No API key required.

3. **Commit and push** the scaffolded workflow, then trigger it by opening a PR or running it manually from the Actions tab.

> **Comment-driven invocation is authorized.** A comment on an issue or PR will start a run only when (a) its author has one of `OWNER` / `MEMBER` / `COLLABORATOR` association with the target repo, **and** (b) the workflow is not running under `pull_request_target` (the default refuses comment invocation in that event — opt in with `with: allow_pr_target_comments: 'true'` only on workflows whose `if:` already gates comment triggers to trusted authors). The authorization decision reads `comment.author_association` from the payload, **never** the comment body — so an attacker cannot elevate themselves by writing `author_association: OWNER` into a comment. Strangers, first-time contributors, and `NONE`-association commenters cannot start a run. See [issue #72](https://github.com/alexhawat/mergeCraft/issues/72).

That's it — no server, dashboard, or account to sign up for.

## Authentication

mergeCraft is BYOK: it never talks to a proprietary backend, only directly to
the provider you configure. You can authenticate either with a **subscription**
(no metered API billing) or a traditional **API key**.

| Provider | Subscription (recommended) | API key |
|----------|-----------------------------|---------|
| Anthropic Claude | `mergecraft auth claude` → saves `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` (Claude Pro/Max) | `ANTHROPIC_API_KEY` secret |
| OpenAI Codex | `mergecraft auth codex` → saves `CODEX_AUTH_JSON` from `codex login --device-auth` (ChatGPT Plus/Pro/Team/Enterprise) | `OPENAI_API_KEY` secret |
| Google Gemini | `mergecraft auth gemini` → saves `GEMINI_API_KEY` from a pasted AI Studio key | `GEMINI_API_KEY` or `GOOGLE_GENERATIVE_AI_API_KEY` secret |
| Cursor Cloud | `mergecraft auth cursor` → saves `CURSOR_API_KEY` from a pasted Cursor API key | `CURSOR_API_KEY` secret |

Using a subscription means the GitHub Action authenticates as *you* through the
official `claude` / `codex` CLIs — the same credential your local coding agent
already uses — instead of paying per-token via a separate API key. Gemini uses
the official `gemini` CLI with an API key from Google AI Studio. **Cursor Cloud**
(issue #13 Phase A) runs a remote cloud agent via the Cursor API — there is no
local `cursor` CLI harness in mergeCraft yet (Phase B deferred). Run the
relevant `mergecraft auth ...` command from the repo you want reviewed; it
detects the `origin` remote and stores the secret with `gh secret set`
automatically (or prints the manual `Settings → Secrets` steps if `gh` isn't
authenticated).

Only set the env var(s) for the provider(s) you actually use — see the
workflow example below, where the unused lines are commented out.

**Codex subscription example** — set `CODEX_AUTH_JSON` and point the repo at a
Codex-family model:

```yaml
# .mergecraft/config.yaml
model: openai/gpt-codex
```

```yaml
# workflow env (subscription path)
env:
  CODEX_AUTH_JSON: ${{ secrets.CODEX_AUTH_JSON }}
```

**OpenAI API key example** — set `OPENAI_API_KEY` and point the repo at any
`openai/*` model (same Codex CLI harness as the subscription path):

```yaml
# .mergecraft/config.yaml
model: openai/gpt
```

```yaml
# workflow env (API key path)
env:
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

**Gemini API key example** — set `GEMINI_API_KEY` and point the repo at a
curated `google/*` slug (`gemini-pro` → `google/gemini-3.1-pro-preview`,
`gemini-flash` → `google/gemini-3.5-flash`):

```yaml
# .mergecraft/config.yaml
model: google/gemini-3.1-pro-preview
```

```yaml
# workflow env (API key path)
env:
  GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

**Cursor Cloud example** — set `CURSOR_API_KEY` and point the repo at
`cursor/cloud-agent` (remote cloud agent; local Cursor CLI deferred):

```yaml
# .mergecraft/config.yaml
model: cursor/cloud-agent
```

```yaml
# workflow env (Cloud Agent API path)
env:
  CURSOR_API_KEY: ${{ secrets.CURSOR_API_KEY }}
```

### Consumer workflow

```yaml
# .github/workflows/mergecraft.yml
name: mergeCraft
on:
  workflow_dispatch:
    inputs:
      prompt:
        type: string
        description: Agent prompt

jobs:
  mergecraft:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
      issues: write
      id-token: write
    steps:
      - uses: actions/checkout@v5
      - name: Run agent
        uses: alexhawat/mergeCraft@pre-0.0.1
        with:
          prompt: ${{ inputs.prompt }}
        env:
          # Claude — pick one:
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}  # subscription (mergecraft auth claude)
          # ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}           # or API key
          # Codex / OpenAI — pick one (see Authentication above):
          # CODEX_AUTH_JSON: ${{ secrets.CODEX_AUTH_JSON }}               # subscription (mergecraft auth codex)
          # OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}                 # API key + model: openai/gpt
          # Gemini — API key (mergecraft auth gemini):
          # GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}                 # + model: google/gemini-3.1-pro-preview
          # Cursor Cloud — API key (mergecraft auth cursor; local CLI deferred):
          # CURSOR_API_KEY: ${{ secrets.CURSOR_API_KEY }}                 # + model: cursor/cloud-agent
```

Ready-made workflow files live under [`examples/workflows/`](examples/workflows/):

- [`mergecraft.yml`](examples/workflows/mergecraft.yml) — minimal getting-started
  example (`pull_request` + `workflow_dispatch`; comment triggers omitted — see
  issue #72).
- [`mergecraft-hardened.yml`](examples/workflows/mergecraft-hardened.yml) — use
  this one when the review is a **required check** (`pull_request_target`,
  wait-for-CI, approval enforcement).

Both are rendered from templates in `scripts/example_workflows/` (`make examples`
to regenerate; CI fails on drift).

### Where the workflow must live (`pull_request_target`)

Under GitHub's Nov 2025 policy (**effective 2025-12-08**), a
`pull_request_target` workflow is resolved from the repository's **default
branch** — not from the PR's base branch. Three consequences:

- The **default-branch copy runs for every PR**, whatever base branch the PR
  targets.
- A PR that **edits the workflow cannot review itself** with its own changes;
  updates take effect on the **next** PR after merge.
- If your **trunk is not the default branch**, a copy of the workflow on the
  trunk is **inert**. It never runs, must be hand-mirrored onto the default
  branch forever, and the two copies drift.

This matters when `main` is a stub (for example, only `LICENSE`) while real work
lands on another branch such as `pre-0.0.1`: keep
`.github/workflows/mergecraft.yml` on **`main`** (or whichever branch GitHub
lists as default), not only on the trunk. mergeCraft itself is an example —
there is no **mergeCraft review** workflow under `.github/workflows/` yet (CI,
release, Docker, and CodeQL workflows exist; only `mergecraft.yml` is missing),
and the default branch does not match the development trunk.

### `pull_request` vs `pull_request_target`

| Trigger | When to use | Trade-off |
|---------|-------------|-----------|
| `pull_request` | The review job is **not** a required check | Simpler and safer — no repository secrets in scope for fork PRs |
| `pull_request_target` | The review job **is** a required check | Runs with secrets; must never execute PR-authored code |

GitHub **skips** `pull_request` workflows when `refs/pull/N/merge` cannot be
built — i.e. whenever the PR has a **merge conflict**. If the review job is a
required check, that leaves the check permanently missing and the PR
unmergeable even after the conflict is fixed. `pull_request_target` still fires
on `synchronize` in that state.

The cost of `pull_request_target` is that it runs with repository secrets in
scope, so the workflow must not execute PR-authored scripts or checkout untrusted
code. Use same-repo guards, `push: disabled`, and `shell: disabled` in
mergeCraft config. **If the review is not a required check, prefer plain
`pull_request`.**

### Pin parity across copies

Many repos pin the action SHA in more than one place — the workflow, a Makefile
variable for local `mergecraft diff-review`, a devcontainer, or docs. Gate those
copies against each other in CI. The non-obvious part:

> Read the workflow side from the **default branch**, not from the working tree:
>
> ```bash
> git show origin/main:.github/workflows/mergecraft.yml
> ```

Comparing a working-tree copy that never executes against a local pin verifies
two values that do not matter, while the pin that actually runs goes unchecked.
A SHA bumped only on the default branch stays invisible to a gate that reads the
PR checkout.

- **Bump order: default branch first, local pin second.** The gate compares
  against the default branch, so reversing the order fails until the default
  branch catches up.
- The gate should **skip with a warning** when the default-branch ref is
  unreachable (offline local runs) and **hard-fail under `CI`** — otherwise a
  network hiccup turns the check into a decorative no-op.

### Local config

Create `.mergecraft/config.yaml` (see [`examples/config.yaml`](examples/config.yaml)):

**Single model (legacy scalar):**

```yaml
model: anthropic/claude-sonnet
push: restricted
shell: restricted
prApproveEnabled: false
signedCommits: false
```

**Ordered preference list** — try each entry in order; optional per-slug backups via
`modelFallbacks`; runtime skips entries without credentials and advances on retryable
provider failures:

```yaml
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
modelFallbacks:
  anthropic/claude-sonnet:
    - anthropic/claude-opus
push: restricted
shell: restricted
prApproveEnabled: false
signedCommits: false
staticChecks:                 # mechanical gates the reviewer runs; optional
  - name: lint
    command: make lint
# analyzers:                    # deterministic catalog tools (see REVIEW-CHECKS.md)
#   enabled: true               # omit for auto-detect from changed paths
#   inlineBudget: 8
#   overrides:
#     actionlint:
#       enabled: true
```

With no `staticChecks`, mergecraft discovers `lint` / `format-check` / `typecheck` / `ci-static` targets in your `Makefile` instead.

**Analyzers** (actionlint, zizmor, ShellCheck, Hadolint in this release) run deterministically from YAML manifests when paths match — the reviewer calls `run_analyzers` early and places verified hits inline or in `### 🔧 Mechanical findings`. You can override enablement in `analyzers:`; editing the catalog remains possible but is not the headline workflow (D19).

Learnings live in `.mergecraft/learnings.md` and are seeded/persisted across runs.

## What the review checks

[**REVIEW-CHECKS.md**](REVIEW-CHECKS.md) lists every check a mergecraft review applies, grouped — code lenses, mechanical gates, PR hygiene, how findings are graded and filtered, and what it deliberately never reports.

## CLI

| Command | Purpose |
|---------|---------|
| `mergecraft init` | Scaffold `.mergecraft/config.yaml` + example workflow |
| `mergecraft auth claude` | Save a Claude Pro/Max subscription token (`CLAUDE_CODE_OAUTH_TOKEN`) via `gh secret set` |
| `mergecraft auth codex` | Save a ChatGPT subscription credential (`CODEX_AUTH_JSON`) via `gh secret set` |
| `mergecraft auth gemini` | Save a Gemini API key (`GEMINI_API_KEY`) via `gh secret set` |
| `mergecraft auth cursor` | Save a Cursor Cloud API key (`CURSOR_API_KEY`) via `gh secret set` |
| `mergecraft models list` | List curated model slugs and whether local credentials are detected |
| `mergecraft models set <slug> [<slug>…]` | Write an ordered `models:` preference list to `.mergecraft/config.yaml` |
| `mergecraft models show` | Show effective model order (config + `MERGECRAFT_MODEL`) and which slug would win now |
| `mergecraft watch --pr N` | Stream PR/issue timeline as JSONL |
| `mergecraft diff-review` | Offline local git/patch review (no GitHub PR posting); optional `--json` for structured findings |
| `mergecraft gha` | Action runtime entry (used by Docker Action) |
| `mergecraft gha token [--post]` | Installation token mint / post write-back |

Bin: `mergecraft` (not the upstream `mergecraft` / `pf` names).

### Offline diff review

```bash
# Review uncommitted + branch changes vs origin/main (auto-detected base)
uv run mergecraft diff-review

# Explicit base / model / output file
uv run mergecraft diff-review --base origin/main --model anthropic/claude-sonnet -o review.md

# Review an existing patch without git
uv run mergecraft diff-review --diff changes.patch --dry-run

# Structured findings JSON (machine-readable Finding[] for benchmarks/scoring)
uv run mergecraft diff-review --diff changes.patch --json findings.json
```

`--dry-run` materializes the unified diff and prints the Review prompt without
invoking an agent (no LLM keys required). With `--json`, `--dry-run` does not
create the JSON file.

## Action inputs

Same contract as upstream mergecraft: `prompt`, `prompt_file`, `timeout`, `model`,
`cwd`, `push`, `shell`, `status_checks`, `output_schema`, `token` → output `result`.

### Native event triggers

The Action reads the native `GITHUB_EVENT_PATH` / `GITHUB_EVENT_NAME`, so
workflows can trigger on `pull_request` (e.g. auto-review on open/sync),
`issue_comment`, or `pull_request_review_comment` events and the agent gets PR
context (number, branch, `is_pr`) automatically — no hand-built `~mergecraft` JSON
payload required. With `status_checks: enabled`, PR runs always post the `mergecraft`
and `mergecraft-approval` commit-status checks. The approval check has three
outcomes: `success` when mergeCraft would approve, `failure` when it would not,
and `neutral` when the review did not complete (agent crash, timeout, or no
approval recorded). GitHub branch protection treats `neutral` as non-blocking by
default — gate on `success`/`failure` explicitly in your enforce step if you
require a completed review. An explicit `~mergecraft` payload event still takes
precedence when provided.

## Development

```bash
make setup      # uv sync + pre-commit
make lint       # ruff + loguru-only
make typecheck  # mypy strict
make test       # pytest
make ci         # full gate
```

Coding style and CI patterns are adapted from
[sevn-bot/sevn@pre-0.0.1](https://github.com/sevn-bot/sevn/tree/pre-0.0.1)
(Python 3.14, uv, loguru, Makefile-gated Ruff/mypy/pytest). This repo does
**not** include a workflow that invokes `mergecraft/mergecraft`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contributor workflow.

## Security

BYOK by design: your provider credentials and repo contents never leave
GitHub Actions / your machine and this repo's own code. See
[SECURITY.md](SECURITY.md) to report a vulnerability, and
[REVIEW-CHECKS.md](REVIEW-CHECKS.md) for what a review does (and never does).

## License

MIT — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
