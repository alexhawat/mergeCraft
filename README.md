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

3. **Commit and push** the scaffolded workflow, then trigger it by opening a PR, commenting `@mergecraft ...`, or running it manually from the Actions tab.

That's it — no server, dashboard, or account to sign up for.

## Authentication

mergeCraft is BYOK: it never talks to a proprietary backend, only directly to
the provider you configure. You can authenticate either with a **subscription**
(no metered API billing) or a traditional **API key**.

| Provider | Subscription (recommended) | API key |
|----------|-----------------------------|---------|
| Anthropic Claude | `mergecraft auth claude` → saves `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` (Claude Pro/Max) | `ANTHROPIC_API_KEY` secret |
| OpenAI Codex | `mergecraft auth codex` → saves `CODEX_AUTH_JSON` from `codex login --device-auth` (ChatGPT Plus/Pro/Team/Enterprise) | `OPENAI_API_KEY` secret |

Using a subscription means the GitHub Action authenticates as *you* through the
official `claude` / `codex` CLIs — the same credential your local coding agent
already uses — instead of paying per-token via a separate API key. Run the
relevant `mergecraft auth ...` command from the repo you want reviewed; it
detects the `origin` remote and stores the secret with `gh secret set`
automatically (or prints the manual `Settings → Secrets` steps if `gh` isn't
authenticated).

Only set the env var(s) for the provider(s) you actually use — see the
workflow example below, where the unused lines are commented out.

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
          # Codex / OpenAI — pick one:
          # CODEX_AUTH_JSON: ${{ secrets.CODEX_AUTH_JSON }}               # subscription (mergecraft auth codex)
          # OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}                 # or API key
```

### Local config

Create `.mergecraft/config.yaml` (see [`examples/config.yaml`](examples/config.yaml)):

```yaml
model: anthropic/claude-sonnet
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
| `mergecraft watch --pr N` | Stream PR/issue timeline as JSONL |
| `mergecraft diff-review` | Offline local git/patch review (no GitHub PR posting) |
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
```

`--dry-run` materializes the unified diff and prints the Review prompt without
invoking an agent (no LLM keys required).

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
