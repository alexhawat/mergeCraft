# mergeCraft

Standalone **BYOK** GitHub Action for AI-powered PR review — inspired by prior
work including [pullfrog](https://github.com/pullfrog/pullfrog) and CodeRabbit.

No proprietary SaaS account is required. Settings, learnings, and secrets
come from your repo and GitHub Actions secrets.

## Requirements

- Python **3.14+**
- [uv](https://docs.astral.sh/uv/)
- Provider API keys (Anthropic, OpenAI/Codex, Gemini, OpenRouter, …) as needed

## Quick start

```bash
# Install locally
uv sync --extra dev
uv run mergecraft --help

# Scaffold config + example workflow into a consumer repo
uv run mergecraft init
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
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
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
```

With no `staticChecks`, mergecraft discovers `lint` / `format-check` / `typecheck` / `ci-static` targets in your `Makefile` instead.

Learnings live in `.mergecraft/learnings.md` and are seeded/persisted across runs.

## What the review checks

[**REVIEW-CHECKS.md**](REVIEW-CHECKS.md) lists every check a mergecraft review applies, grouped — code lenses, mechanical gates, PR hygiene, how findings are graded and filtered, and what it deliberately never reports.

## CLI

| Command | Purpose |
|---------|---------|
| `mergecraft init` | Scaffold `.mergecraft/config.yaml` + example workflow |
| `mergecraft auth codex` / `auth claude` | Store credentials via `gh secret set` |
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
payload required. With `status_checks: enabled`, PR runs post the `mergecraft` and
`mergecraft-approval` commit-status checks (gate on the latter). An explicit
`~mergecraft` payload event still takes precedence when provided.

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


## License

MIT
