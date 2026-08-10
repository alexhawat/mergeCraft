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

> **Comment-driven invocation is authorized.** A comment on an issue or PR will start a run only when (a) its author has one of `OWNER` / `MEMBER` / `COLLABORATOR` association with the target repo, **and** (b) the workflow is not running under `pull_request_target` (the default refuses comment invocation in that event — opt in with `with: allow_pr_target_comments: 'true'` only on workflows whose `if:` already gates comment triggers to trusted authors). The authorization decision reads `comment.author_association` from the payload, **never** the comment body — so an attacker cannot elevate themselves by writing `author_association: OWNER` into a comment. Strangers, first-time contributors, and `NONE`-association commenters cannot start a run. Full rules and the two opt-in knobs: [Comment-trigger authorization](#comment-trigger-authorization) · [issue #72](https://github.com/alexhawat/mergeCraft/issues/72).

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
| Nous Research (DeepSeek V4 Flash) | `mergecraft auth nous` → saves `NOUS_API_KEY` from a pasted Portal key | `NOUS_API_KEY` secret (or `MERGECRAFT_CUSTOM_PROVIDER_API_KEY` alias — see [issue #57](https://github.com/alexhawat/mergeCraft/issues/57)) |
| Cursor Cloud | `mergecraft auth cursor` → saves `CURSOR_API_KEY` from a pasted Cursor API key | `CURSOR_API_KEY` secret |
| Nous Portal | — (API key) | `mergecraft auth nous` → saves `NOUS_API_KEY` |
| Tencent TokenHub | — (API key) | `mergecraft auth tokenhub` → saves `TOKENHUB_API_KEY` (Hy3 and any TokenHub model) |

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

> **Codex inside a container runner.** Codex CLI runs its own bubblewrap +
> Landlock sandbox on Linux. Inside a container that is already namespaced — a
> Docker container action, or a runner without unprivileged user namespaces —
> bubblewrap cannot create a nested namespace and **every** Codex call fails
> before doing any work, including a bare `pwd`. mergeCraft reports that
> explicitly rather than letting `continue-on-error` swallow it as an empty
> review. If the runner is already ephemeral and isolated, skip the redundant
> nested sandbox:
>
> ```yaml
> - uses: alexhawat/mergeCraft@v0
>   with:
>     codex_sandbox: danger-full-access
> ```
>
> mergeCraft never sets this itself — whether a second sandbox is redundant is a
> fact about *your* runner. mergeCraft's own `shell` and `push` controls are
> unaffected either way; they remain the security boundary. See
> [issue #70](https://github.com/alexhawat/mergeCraft/issues/70).

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

**Nous Portal example** — set `NOUS_API_KEY` and point the repo at the
`nous/deepseek/deepseek-v4-flash` catalog slug. The opencode harness consumes
the env var under its `MERGECRAFT_CUSTOM_PROVIDER_API_KEY` contract (PR #79),
so the canonical wire re-passes the secret:

```yaml
# .mergecraft/config.yaml
model: nous/deepseek/deepseek-v4-flash
```

```yaml
# workflow env (API key path)
env:
  NOUS_API_KEY: ${{ secrets.NOUS_API_KEY }}
  MERGECRAFT_CUSTOM_PROVIDER_API_KEY: ${{ secrets.NOUS_API_KEY }}
  MERGECRAFT_CUSTOM_PROVIDER_BASE_URL: https://inference-api.nousresearch.com/v1
```

`mergecraft auth nous` writes `NOUS_API_KEY`; setting the two harness env vars
explicitly on the step is the same contract `.github/workflows/mergecraft.yml`
uses. See [issue #57](https://github.com/alexhawat/mergeCraft/issues/57).

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

**Nous Portal example** — set `NOUS_API_KEY` and use a `nous/…` model (opencode
harness; no `MERGECRAFT_CUSTOM_PROVIDER_*` required):

```yaml
# .mergecraft/config.yaml
model: nous/deepseek/deepseek-v4-flash
```

```yaml
env:
  NOUS_API_KEY: ${{ secrets.NOUS_API_KEY }}
```

**TokenHub (Hy3 and any TokenHub model)** — set `TOKENHUB_API_KEY` and use
`tokenhub/<model-id>` (e.g. `tokenhub/hy3`, `tokenhub/deepseek-v4-flash`):

```yaml
# .mergecraft/config.yaml
model: tokenhub/hy3
```

```yaml
env:
  TOKENHUB_API_KEY: ${{ secrets.TOKENHUB_API_KEY }}
  # optional override:
  # TOKENHUB_BASE_URL: https://tokenhub-intl.tencentcloudmaas.com/v1
```

Operators can still set `MERGECRAFT_CUSTOM_PROVIDER_BASE_URL` +
`MERGECRAFT_CUSTOM_PROVIDER_API_KEY` to point any `provider/model` prefix at a
generic OpenAI-compatible endpoint; those env vars override the Nous/TokenHub
presets when both are present.

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
          # Nous Portal — API key (mergecraft auth nous):
          # NOUS_API_KEY: ${{ secrets.NOUS_API_KEY }}                     # + model: nous/deepseek/deepseek-v4-flash
          # TokenHub — API key (mergecraft auth tokenhub; hy3 + any TokenHub model):
          # TOKENHUB_API_KEY: ${{ secrets.TOKENHUB_API_KEY }}             # + model: tokenhub/hy3
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
# ciEvidence:                   # reuse CI you already ran (see REVIEW-CHECKS.md)
#   gates:                      # <gate name>: <exact GitHub check-run name>
#     lint: Verify (drift gates)
#   sarifArtifacts:             # workflow artifacts whose SARIF to ingest
#     - ruff-sarif
# analyzers:                    # deterministic catalog tools (see REVIEW-CHECKS.md)
#   enabled: true               # omit for auto-detect from changed paths
#   inlineBudget: 8
#   overrides:
#     actionlint:
#       enabled: true
```

With no `staticChecks`, mergecraft discovers `lint` / `format-check` / `typecheck` / `ci-static` targets in your `Makefile` instead.

The Action image has no `make`, no repo venv, and none of your pinned toolchains, so those gates often report `unavailable` even when your own CI just proved them. `ciEvidence.gates` maps a gate to the exact check-run name that proves it, and a **passing** declared run reports the gate as `satisfied-by-ci` instead. Declaration is required — a check run merely *named* like a gate proves nothing — and with no `ciEvidence` block mergecraft never reads your check runs at all.

**Analyzers** (actionlint, zizmor, ShellCheck, Hadolint in this release) run deterministically from YAML manifests when paths match — the reviewer calls `run_analyzers` early and places verified hits inline or in `### 🔧 Mechanical findings`. You can override enablement in `analyzers:`; editing the catalog remains possible but is not the headline workflow (D19).

The Action's `analyzers:` input picks how much of the catalog is eligible:

| value | meaning |
|-------|---------|
| `off` | the analyzer tools are not registered at all |
| `auto` *(default)* | detect from changed paths and provision what is needed |
| `full` | same selection as `auto`, with the baked image tools provisioned up front |
| `untrusted-only` | trust-aware: only analyzers needing no secrets, no network, and no PR-authored command construction |

Under `pull_request_target` and fork-head pull requests the trust tier is `untrusted`, and `auto` resolves to `untrusted-only` there — so a hardened workflow gets mechanical signal without loosening `shell:`. Anything the mode excludes is reported as a skipped row with a named reason, never as a failure. An unrecognised value also resolves to `untrusted-only`, with a warning, rather than silently widening to `auto`. `full` is a request to provision more tooling; it is never a trust override and cannot re-admit an analyzer the trust tier excluded. The generated matrix in [`docs/ANALYZERS.md`](docs/ANALYZERS.md) shows what each combination selects.

### SARIF upload to code scanning (opt-in)

Analyzer findings can also be published as GitHub code-scanning alerts, which keeps mechanical signal readable when the review narrative is thin or when findings overflowed the inline comment budget. It is **off by default** and requires `security-events: write`:

```yaml
permissions:
  contents: read
  pull-requests: write
  security-events: write   # required — without it GitHub answers 403

jobs:
  review:
    steps:
      - uses: alexhawat/mergeCraft@<sha>
        with:
          sarif_upload: enabled
```

`.mergecraft/config.yaml`'s `analyzers.sarifUpload: true` does the same; the `sarif_upload` action input wins in both directions when it is set, and an unrecognised value resolves to disabled with a warning.

Only findings from catalog analyzers this run's trust tier, `shell:` policy and `analyzers:` mode actually admitted are uploaded, after secret redaction — CI-sourced findings (which carry pipeline log excerpts) and agent narrative are never uploaded. The upload is complementary evidence, never a gate: a missing permission, a repository without code scanning, or a transport error is logged at `warning` and the review still completes. Details in [`docs/ANALYZERS.md`](docs/ANALYZERS.md#sarif-upload-to-code-scanning-39).

## Learnings — staging and promotion

`.mergecraft/learnings.md` holds durable cross-run context (test commands, conventions, gotchas, architecture notes) seeded into every review. Since this file is **attacker-controllable input** in any non-maintainer context (a fork PR body, a contributor comment, an agent-written entry from prior untrusted text), entries are now provenance-gated (D10, #74):

- **Every persisted entry carries a provenance record** (`run_id`, `pr_number`, `source_field`, `author_login`, `author_association`, `trust_tier`, `timestamp`) rendered as a structured HTML comment line immediately above the entry.
- **New entries land in `## Staging` by default.** Only entries whose author association is `OWNER`/`MEMBER`/`COLLABORATOR` may be promoted into `## Active`, and promotion is opt-in via `autopromoteLearnings: true` in `.mergecraft/config.yaml`.
- **Quarantined entries never reach the reviewer prompt.** The active section is the only one `build_learnings_section()` reads; staging entries are visible to the audit (`mergecraft learnings staging`) but not to the model.
- **Active entries are fenced at seed time** via the W4 nonce fence (`mergecraft.utils.fence`). An entry carrying a forged closing delimiter cannot restructure the instruction block — the entry is wrapped in a nonce-bound envelope before the model reads it.

The default is **fail-closed**: a reviewer reading the active section sees only maintainer-authored entries, and a fork PR's attempt to inject `Learning:` text into `.mergecraft/learnings.md` is quarantined and surfaced for human review rather than silently promoted. To restore the legacy auto-promote behaviour (where every entry the agent wrote during a run landed in the file verbatim), set:

```yaml
# .mergecraft/config.yaml
autopromoteLearnings: true
```

Inspect what was seeded into a given run with `mergecraft learnings influence --repo PATH --json` — the listing names each entry's heading and its originating run id / author / tier so the audit can answer "which learnings entered this review?" without reading the whole file.

## What the review checks

[**REVIEW-CHECKS.md**](REVIEW-CHECKS.md) lists every check a mergecraft review applies, grouped — code lenses, mechanical gates, PR hygiene, how findings are graded and filtered, and what it deliberately never reports.

> [!NOTE]
> **LLM judges are a secondary signal here, never the gate.** Before a `Critical` or `Major`
> finding is published, a second read-only agent (`mergecraft-verifier`) re-reads the cited code
> and returns confirm / downgrade / drop. That judge runs **after** the deterministic checks —
> analyzers and your repo's own gates settle every mechanically checkable fact first, and the
> judge never overrules a tool result. Its model is pinned per provider (a different tier from the
> agent that wrote the finding) and its model, provider, judge version and rubric version are
> logged with every verdict, so a verdict stays auditable after a model default changes. On a
> high blast-radius change (migrations, auth, secrets, irreversible infra), one judge cannot
> retire a finding on its own. Treat judge output as evidence, not as a merge decision.

## CLI

| Command | Purpose |
|---------|---------|
| `mergecraft init` | Scaffold `.mergecraft/config.yaml` + example workflow |
| `mergecraft auth claude` | Save a Claude Pro/Max subscription token (`CLAUDE_CODE_OAUTH_TOKEN`) via `gh secret set` |
| `mergecraft auth codex` | Save a ChatGPT subscription credential (`CODEX_AUTH_JSON`) via `gh secret set` |
| `mergecraft auth gemini` | Save a Gemini API key (`GEMINI_API_KEY`) via `gh secret set` |
| `mergecraft auth nous` | Save a Nous Portal API key (`NOUS_API_KEY`) via `gh secret set` |
| `mergecraft auth cursor` | Save a Cursor Cloud API key (`CURSOR_API_KEY`) via `gh secret set` |
| `mergecraft auth nous` | Save a Nous Portal API key (`NOUS_API_KEY`) via `gh secret set` |
| `mergecraft auth tokenhub` | Save a TokenHub API key (`TOKENHUB_API_KEY`) via `gh secret set` |
| `mergecraft models list` | List curated model slugs and whether local credentials are detected |
| `mergecraft models set <slug> [<slug>…]` | Write an ordered `models:` preference list to `.mergecraft/config.yaml` |
| `mergecraft models show` | Show effective model order (config + `MERGECRAFT_MODEL`) and which slug would win now |
| `mergecraft watch --pr N` | Stream PR/issue timeline as JSONL |
| `mergecraft diff-review` | Offline local git/patch review (no GitHub PR posting); optional `--json` for structured findings |
| `mergecraft gha` | Action runtime entry (used by Docker Action) |
| `mergecraft gha token [--post]` | Installation token mint / post write-back |
| `mergecraft config tracing` | Show resolved tracing config with the logfire token redacted |
| `mergecraft traces <run-id>` | Read back local JSONL traces for a run id (re-redacts on render) |
| `mergecraft learnings influence [--repo PATH] [--json]` | List active + staging learnings entries with their provenance record (run id, author, trust tier, timestamp) |
| `mergecraft learnings active [--repo PATH] [--json]` | List only the active (promoted) entries |
| `mergecraft learnings staging [--repo PATH] [--json]` | List only the staging (quarantined) entries |

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

## Tracing

Tracing is opt-in and **off by default** — a repo that does not declare a
`tracing:` block in `.mergecraft/config.yaml` never touches the filesystem
and never makes a network call. When enabled, mergeCraft writes a per-run
span tree (review, agent turn, tool call, LLM call) to local JSONL files
and, behind the optional `[tracing]` extra, to remote OTLP endpoints
(Logfire or any self-hosted collector). Full reference:
[`docs/TRACING.md`](docs/TRACING.md).

```yaml
# .mergecraft/config.yaml
tracing:
  enabled: true
  retentionDays: 30
  redaction: true
  sinks:
    - type: jsonl_file
      path: .mergecraft/traces/
    # Behind `pip install merge-craft[tracing]`:
    # - type: logfire        # requires tokenRef or MERGECRAFT_LOGFIRE_TOKEN
    # - type: otel           # requires endpoint
```

Wire tracing from the Action without editing config:

```yaml
- uses: alexhawat/mergecraft@<ref>
  with:
    tracing: "true"
    tracing-to: local_files   # or `logfire` / `otel`
    logfire-token: ${{ secrets.LOGFIRE_TOKEN }}
    otel-endpoint: https://otel.internal.example.com:4318/v1/traces
- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: mergecraft-traces
    path: .mergecraft/traces/
```

Inspect a run after the fact:

```bash
uv run mergecraft config tracing     # resolved sinks, token redacted
uv run mergecraft traces <run-id>    # read back local spans
```

> Enabling a **remote** sink (`logfire`, `otel`) exports reviewed-repo
> content — the prompts the reviewer received, the tool inputs and outputs
> it produced, and the model's reasoning — to the configured endpoint
> using the operator's token or API key. **BYOK** means the operator owns
> both the credential and the responsibility for what leaves the runner.
> Scope workflows at the GitHub Actions level
> (`if: github.event.pull_request.head.repo.fork == false`) when the
> reviewer should not exfiltrate fork-PR content. See `docs/TRACING.md`
> (D15).

## Action inputs

Same contract as upstream mergecraft: `prompt`, `prompt_file`, `timeout`, `model`,
`cwd`, `push`, `shell`, `status_checks`, `output_schema`, `token` → output `result`,
plus `allow_pr_target_comments` (default `false`) — see
[Comment-trigger authorization](#comment-trigger-authorization) — and
`sarif_upload` (default `disabled`, needs `security-events: write`) — see
[SARIF upload to code scanning](#sarif-upload-to-code-scanning-opt-in).

Tracing inputs (`tracing`, `tracing-to`, `logfire-token`, `otel-endpoint`) — see
[Tracing](#tracing).

### Native event triggers

The Action reads the native `GITHUB_EVENT_PATH` / `GITHUB_EVENT_NAME`, so
workflows can trigger on `pull_request` (e.g. auto-review on open/sync),
`issue_comment`, or `pull_request_review_comment` events and the agent gets PR
context (number, branch, `is_pr`) automatically — no hand-built `~mergecraft` JSON
payload required. Comment events are subject to the authorization gate below.
With `status_checks: enabled`, PR runs always post the `mergecraft`
and `mergecraft-approval` commit-status checks.

The approval check is **structural**: its conclusion is a pure function of the
typed `Finding` list, the run's completion state, and the trust tier. Narrative
(`create_pull_request_review(approved=true|false)`) is recorded as an advisory
input only — it is never the sole positive input. The wire-shape has three
outcomes:

- `success` — run completed, trust tier is trusted, no `Critical` or `Major`
  finding in the list, and at least one finding attests the review ran.
- `failure` — at least one `Critical` or `Major` finding. The agent's
  `approved=true` cannot outvote a blocker.
- `neutral` — run crashed / timed out / produced no findings, **or** trust tier
  is `untrusted` (fork PR / `pull_request_target`).

GitHub branch protection treats `neutral` as non-blocking by default. The
hardened example workflow ships an enforce step (`Fail when mergeCraft would
not approve`) that flips `neutral` to blocking — wire it into your branch
protection rule if you want the gate to require a clean structural conclusion,
not just a missing check. The pre-W8 "neutral is non-blocking" framing is
removed: a crashed / injected / fork-suppressed review must not pass the gate
silently. An explicit `~mergecraft` payload event still takes precedence when
provided.

### Comment-trigger authorization

A comment never carries its own authority. Before an `issue_comment` or
`pull_request_review_comment` event can start a run, mergeCraft reads
`comment.author_association` from `GITHUB_EVENT_PATH` and requires one of
`OWNER`, `MEMBER`, or `COLLABORATOR`. Everything else — `CONTRIBUTOR`,
`FIRST_TIME_CONTRIBUTOR`, `NONE`, or a payload with the field missing entirely —
is refused: the run resolves to the `unknown` trigger, no agent is dispatched,
and a single `logger.warning` records the event name and association. The comment
body is never logged and never consulted, so writing `author_association: OWNER`
into a comment changes nothing.

Two knobs widen this, each on exactly one axis:

| Knob | Where | Default | What it widens |
|------|-------|---------|----------------|
| `allow_pr_target_comments` | action input (`with:`) | `false` | Permits comment-driven invocation when `GITHUB_EVENT_NAME` is `pull_request_target`. The association gate still applies. |
| `commentInvocationAllowlist` | `.mergecraft/config.yaml` | empty | Comma-separated extra logins (matched case-insensitively against `comment.user.login`) that may invoke despite their association. Does not affect the `pull_request_target` refusal, and does not override the missing-field fail-closed default. |

`pull_request_target` runs hold repository secrets, which is why comment
invocation there is off by default. Enable it only on a workflow whose `if:`
condition already restricts comment triggers to trusted authors.

Both shipped examples — [`examples/workflows/mergecraft.yml`](examples/workflows/mergecraft.yml)
and [`examples/workflows/mergecraft-hardened.yml`](examples/workflows/mergecraft-hardened.yml)
— deliberately declare no `issue_comment` / `pull_request_review_comment`
triggers and drive on-demand runs from `workflow_dispatch` instead.
[`examples/config.yaml`](examples/config.yaml) shows the
`commentInvocationAllowlist` shape.

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
