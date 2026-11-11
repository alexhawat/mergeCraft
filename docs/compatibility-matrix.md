# Compatibility matrix

Configured Action runtime combinations and their actual test lanes. See the
[generated support matrix](support-matrix.md) for separate support, automated
evidence, and artifact contracts. The PR E2E gate exercises the **security-relevant slice**; a
scheduled nightly job covers the **broad slice** plus live providers
(secrets-gated).

## Axes

| Axis | Supported values | Notes |
|------|------------------|-------|
| **Events** | `pull_request`, `pull_request_target`, `issue_comment` (trusted authors), `workflow_dispatch` | `pull_request_target` is always **untrusted** tier; comment triggers under target require `allow_pr_target_comments` |
| **Agents** | `claude`, `codex`, `gemini`, `opencode`, `cursor` (API harness) | Local CLIs are lockfile-pinned in the Action image (`docker/agent-clis/`); Cursor is Cloud-only |
| **Providers** | <!-- BEGIN:providers-inline -->`anthropic`, `bedrock`, `deepseek`, `google`, `minimax`, `moonshotai`, `openai`, `opencode`, `opencode-go`, `openrouter`, `paperinstruments`, `tokenhub`, `vertex`, `xai`<!-- END:providers-inline -->, custom OpenAI-compatible (every catalog label; see the [auth reference](authentication.md#provider-reference)) | BYOK — credentials via Action secrets / env allowlist (W2) |
| **Shell** | `disabled`, `restricted`, `enabled` | MCP `shell` tool only under `restricted`; hooks off unless `enabled` |
| **Push** | `disabled`, `restricted`, `enabled` | Production modes are **review-only**: mergeCraft refuses commit and push whatever the value, so no value grants write access. Default runtime resolve is `restricted`; default branch protected under `restricted` |
| **Arch** | `linux/amd64`, `linux/arm64` | Runtime/provisioning choices; inspect the selected OCI manifest before use. PR E2E runs on `ubuntu-latest` (amd64); ARM64 execution/publication is not established by that job. |

## Harness × model

OpenCode = generic multi-provider harness · Codex = OpenAI-native harness ·
TokenHub = provider · DeepSeek = model family. When `harness:` is unset in
`.mergecraft/config.yaml`, mergeCraft infers the harness from the model slug.
Explicit `harness:` wins over inference; unsupported combinations are
configuration errors naming both halves.

<!-- BEGIN:harness-table -->
| Provider label | Recommended model (seeded) | `harness` unset (inferred) |
|----------------|----------------------------|----------------------------|
| `anthropic` | `anthropic/claude-opus` | `claude` |
| `bedrock` | none — name a model explicitly | `opencode` |
| `deepseek` | `deepseek/deepseek-pro` | `opencode` |
| `google` | `google/gemini-pro` | `gemini` |
| `minimax` | `minimax/MiniMax-M3` | `opencode` |
| `moonshotai` | `moonshotai/kimi-k2` | `opencode` |
| `openai` | `openai/gpt` | `codex` |
| `opencode` | `opencode/big-pickle` | `opencode` |
| `opencode-go` | `opencode-go/glm-5.1` | `opencode` |
| `openrouter` | `openrouter/claude-opus` | `opencode` |
| `paperinstruments` | `paperinstruments/ultramarine-1-flash` | `opencode` |
| `tokenhub` | `tokenhub/hy3` | `opencode` |
| `vertex` | none — name a model explicitly | `opencode` |
| `xai` | `xai/grok` | `opencode` |

<!-- END:harness-table -->

Explicit `harness:` examples: `harness: claude` on a `tokenhub/…` slug is a configuration
error; `harness: opencode` on an `openai/…` or `anthropic/…` slug is accepted and runs
through `opencode`. The `cursor/cloud-agent` slug infers `cursor` (Cursor Cloud is not a
catalog provider).

## Security-relevant slice (PR gate — `.github/workflows/e2e.yml`)

Runs on every pull request. **No live LLMs**: fixture event payloads +
fake provider CLI shims under `docker/e2e/fake-provider-cli/`.

| Cell | Coverage |
|------|----------|
| Build production image from the PR | `docker/build-push-action` → local tag `mergecraft:e2e` |
| `pull_request` × `claude` shim × `shell=restricted` × `push=restricted` | `docker/e2e/run_action_e2e.sh` — assert `result` + check-run shape |
| `pull_request_target` × `claude` shim × `shell=restricted` × `push=restricted` | same harness, untrusted-tier path |
| Full `shell × push` adversarial suite **in-image** | `docker/e2e/run_in_image_adversarial.sh` (W4 suite inside the built Action image) |

## Broad slice (scheduled nightly — same workflow)

Triggered by `schedule` / `workflow_dispatch`. Live-provider cells are
**secrets-gated**: with no live model configured the slice emits a warning and
records the result as **unavailable** in the run summary; a configured model
with a missing credential, a rejected subscription credential, or a failing
provider fails the job.

| Cell | Coverage |
|------|----------|
| Security slice (above) | Always |
| Live provider coverage | `github` in the nightly Integration matrix. E2E requires `MERGECRAFT_E2E_LIVE_MODEL` and its selected API credential (OpenCode Go/OpenAI/Anthropic/Google); no model means explicitly unavailable. It does not consume the rotating Codex subscription. A green skipped/unavailable slice proves no live-provider acceptance. |
| Arch | `ubuntu-latest` (amd64). This lane provides no ARM64 execution or publication evidence; inspect the selected image manifest before choosing ARM64. |

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
