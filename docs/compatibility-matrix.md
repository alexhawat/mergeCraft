# Compatibility matrix

Supported Action runtime combinations for mergeCraft (production-readiness
`#36` / W11.3). The PR E2E gate exercises the **security-relevant slice**; a
scheduled nightly job covers the **broad slice** plus live providers
(secrets-gated, D6).

## Axes

| Axis | Supported values | Notes |
|------|------------------|-------|
| **Events** | `pull_request`, `pull_request_target`, `issue_comment` (trusted authors), `workflow_dispatch` | `pull_request_target` is always **untrusted** tier; comment triggers under target require `allow_pr_target_comments` |
| **Agents** | `claude`, `codex`, `gemini`, `opencode`, `cursor` (API harness) | Local CLIs are lockfile-pinned in the Action image (`docker/agent-clis/`); Cursor is Cloud-only |
| **Providers** | `anthropic`, `openai`, `google`, `nous`, `tokenhub`, custom OpenAI-compatible | BYOK — credentials via Action secrets / env allowlist (W2) |
| **Shell** | `disabled`, `restricted`, `enabled` | MCP `shell` tool only under `restricted`; hooks off unless `enabled` |
| **Push** | `disabled`, `restricted`, `enabled` | Default runtime resolve is `restricted`; default branch protected under `restricted` |
| **Arch** | `linux/amd64`, `linux/arm64` | Images built multi-arch where the release pipeline publishes them; PR E2E runs on `ubuntu-latest` (amd64) |

## Harness × model (HA3 / D11)

OpenCode = generic multi-provider harness · Codex = OpenAI-native harness ·
Nous = provider · DeepSeek = model family. When `harness:` is unset in
`.mergecraft/config.yaml`, mergeCraft infers the harness from the model slug.
Explicit `harness:` wins over inference; unsupported combinations are
configuration errors naming both halves.

| Model slug | `harness` unset (inferred) | Explicit override / error |
|------------|----------------------------|---------------------------|
| `nous/deepseek-v4-flash` | `opencode` | — |
| `nous/deepseek/deepseek-v4-flash` | `opencode` | `harness: claude` → configuration error |
| `openai/gpt-5.3-codex` | `codex` | `harness: opencode` → `opencode` |
| `anthropic/claude-sonnet` | `claude` | `harness: opencode` → `opencode` |
| `google/gemini-3.1-pro-preview` | `gemini` | — |
| `cursor/cloud-agent` | `cursor` | — |

## Security-relevant slice (PR gate — `.github/workflows/e2e.yml`)

Runs on every pull request. **No live LLMs** (D6): fixture event payloads +
fake provider CLI shims under `docker/e2e/fake-provider-cli/`.

| Cell | Coverage |
|------|----------|
| Build production image from the PR | `docker/build-push-action` → local tag `mergecraft:e2e` |
| `pull_request` × `claude` shim × `shell=restricted` × `push=restricted` | `docker/e2e/run_action_e2e.sh` — assert `result` + check-run shape |
| `pull_request_target` × `claude` shim × `shell=restricted` × `push=restricted` | same harness, untrusted-tier path |
| Full `shell × push` adversarial suite **in-image** | `docker/e2e/run_in_image_adversarial.sh` (W4 suite inside the built Action image) |

## Broad slice (scheduled nightly — same workflow)

Triggered by `schedule` / `workflow_dispatch`. Live-provider cells are
**secrets-gated** — the job no-ops with an explicit skip when provider
secrets are absent (`skipped: no live credential`).

| Cell | Coverage |
|------|----------|
| Security slice (above) | Always |
| Agents × providers matrix (live) | `claude`/`codex`/`gemini`/`opencode` against real CLIs when `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` (etc.) are present |
| Arch | `ubuntu-latest` today; arm64 expansion tracked with multi-arch publish |

## Out of scope / dogfood

- `docker.yml` remains the advisory/manual image smoke (`--help`) on
  `workflow_dispatch` / path-filtered push — unchanged by W11.
- `mergecraft.yml` continues to dogfood a **SHA-pinned published** Action; it
  does **not** consume the PR-built image (explicitly out of scope).

## Invocation surfaces

| Surface | What it proves |
|---------|----------------|
| `.github/workflows/e2e.yml` `e2e-pr` | PR-built artifact + fixture Action run + in-image adversarial |
| `.github/workflows/e2e.yml` `e2e-nightly` | Broad/live matrix (secrets-gated) |
| `.github/workflows/docker.yml` | Dispatch `--help` smoke (unchanged) |
| Host `make test` | Python unit/adversarial suite (not the shipped image) |
