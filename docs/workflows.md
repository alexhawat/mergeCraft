# Workflow examples and placement

Advanced workflow patterns, local review, and `pull_request_target` gotchas moved off the landing README.

<details>
<summary><b>Trust tiers & comment authorization</b> (click to expand)</summary>

```mermaid
flowchart TD
    E[GitHub event] --> Q{Event type}
    Q -->|pull_request, same repo| T1[trusted]
    Q -->|pull_request from fork| T3[untrusted]
    Q -->|pull_request_target| T3
    Q -->|issue_comment / review_comment| Q2{author_association}
    Q2 -->|OWNER / MEMBER / COLLABORATOR| T1
    Q2 -->|CONTRIBUTOR / FIRST_TIME / NONE / missing| X[refused — no run]
```

The authorization decision reads `comment.author_association` from the event
payload — **never** the comment body — so writing `author_association: OWNER`
into a comment changes nothing. Details:
[Comment-trigger authorization](#comment-trigger-authorization).

</details>

## Comment-trigger authorization

Only `OWNER`, `MEMBER`, and `COLLABORATOR` may start a run from an
`issue_comment` or `pull_request_review_comment`. The gate reads
`comment.author_association` from the GitHub event payload — never the
comment body. Under `pull_request_target`, comment triggers also require
`allow_pr_target_comments: true` on the Action input (default off). See
[`allow_pr_target_comments`](action-reference.md) in the action reference.



### Example 2 — hardened, review as a required check

When the review gates merges, use `pull_request_target` with trust-aware
restrictions — [`examples/workflows/mergecraft-hardened.yml`](../examples/workflows/mergecraft-hardened.yml)
ships wait-for-CI, same-repo guards, and an enforce step that flips a `neutral`
approval check to blocking.

### Example 3 — local review before you push

```bash
mergecraft review                                        # uncommitted + branch changes vs origin/main
mergecraft review --base origin/main                     # this worktree vs that GitHub branch
mergecraft review --cwd ../feature-wt --base origin/main # linked worktree vs origin/main
mergecraft review --repo .                               # explicit local checkout
mergecraft review --repo owner/repo --head feature --base main   # public GitHub repo at a branch
mergecraft review --repo owner/repo --head pull/42/head --base main  # open or past GitHub PR
mergecraft review --repo https://github.com/o/r --token "$GH_TOKEN"  # private repo
mergecraft review --staged                               # staged changes only
mergecraft review --diff changes.patch --dry-run         # inspect the prompt, no LLM call
gh pr diff 42 > /tmp/pr-42.diff && mergecraft review --diff /tmp/pr-42.diff
mergecraft review --json findings.json                 # machine-readable Finding[] for scoring
mergecraft review --output-format sarif --output report.sarif.json
mergecraft review --output-format jsonl --output stream.jsonl
mergecraft review --agent                              # JSONL agent protocol on stdout
mergecraft review 2> review.md                         # human text is on stderr (D14)
```

Human-readable review text (default mode) is written to **stderr** so stdout stays free
for `--agent` JSONL and other machine payloads. Redirecting stdout (`mergecraft review > review.md`)
captures nothing useful — use `2>` instead (`mergecraft review 2> review.md`). Structured
findings still go to `--json` / `--output` paths as documented above. Root `--format json`
selects JSON output when `--output-format` is omitted (same pattern as `findings export`).

Process exit codes: `0` clean pass; `10` non-blocking findings; `11` blocking severities;
`12` review failed (no findings); `20` inconclusive; `30` configuration error; `40` infra error;
`50` timed out; `2` usage / invalid CLI input. Full table: [`docs/EXIT-CODES.md`](EXIT-CODES.md).

`diff-review` remains a hidden deprecated alias of `review` (one stderr warning per invocation).

**Auth precedence for private clones:** `--token` → `GH_TOKEN` / `GITHUB_TOKEN` →
`gh auth token` → anonymous (public repos only). Cloned third-party repositories
review at **untrusted** tier unless you pass an explicit `--trust trusted` override.

### Example 4 — multi-model with fallback

```yaml
# .mergecraft/config.yaml
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
modelFallbacks:
  anthropic/claude-sonnet:
    - anthropic/claude-opus
push: restricted
shell: restricted
staticChecks:
  - name: lint
    command: make lint
```

Add `model: <slug>` to the workflow `with:` block to pick the **head** of
the chain (default chain head is the first `models:` entry); the configured
fallbacks are walked on credential miss or retryable failure. See
[Chain semantics](#chain-semantics--model-37--w4) for the contract.

### Example 5 — SARIF upload to code scanning (opt-in)

Publish analyzer findings as GitHub code-scanning alerts — off by default,
requires `security-events: write`:

```yaml
permissions:
  contents: read
  pull-requests: write
  security-events: write   # required — without it GitHub answers 403

jobs:
  review:
    steps:
      - uses: alexhawat/mergeCraft@9cdd46d2f5521e663ad8f895ccd87b8fe8c15301
        with:
          sarif_upload: enabled
```

Only findings admitted by the run's trust tier, `shell:` policy and
`analyzers:` mode are uploaded, after secret redaction — agent narrative is
never uploaded. Details: [docs/ANALYZERS.md](ANALYZERS.md).

Full config reference: [`examples/config.yaml`](../examples/config.yaml).

### Example 6 — Tracing with Logfire (opt-in)

Every run can emit a per-request span tree — to local JSONL, to
[Logfire](https://logfire.pydantic.dev/), or to any OTLP collector — off by
default:

```yaml
- uses: alexhawat/mergeCraft@9cdd46d2f5521e663ad8f895ccd87b8fe8c15301
  with:
    tracing: enabled
    tracing-to: logfire
  env:
    LOGFIRE_TOKEN: ${{ secrets.LOGFIRE_TOKEN }}
```

One `trace_id` groups every span from a run into a single tree, so a
Logfire trace view of a real review reads top to bottom as:

```
mergecraft.run
└── agent.attempt          (per fallback entry: model.id, status, ...)
    ├── provider.call      (once per upstream API request)
    │   ├── http.client.request
    │   └── llm.call       (model.id, cost.*, gen_ai.usage.*)
    └── tool.call           (tool.name, tool.server)
```

`gen_ai.*` attrs on `llm.call` / `provider.call` follow the GenAI
semantic-convention keys, so Logfire's built-in AI panels group and render
them without extra config. Full config schema, the redaction guarantee, and
the payload/span-count caps: [docs/TRACING.md](TRACING.md).

<!-- Asset pending: a screenshot of this trace tree for a real review,
committed under assets/ and linked here — operator-captured, see the
issues-showcase-readiness wave plan (PR G5 / D7). -->

## 🔑 Authentication

| Provider | Subscription (recommended) | API key |
|----------|-----------------------------|---------|
| Anthropic Claude | `mergecraft auth claude` → `CLAUDE_CODE_OAUTH_TOKEN` (Claude Pro/Max) | `ANTHROPIC_API_KEY` |
| OpenAI Codex | `mergecraft auth codex` → `CODEX_AUTH_JSON` (ChatGPT Plus/Pro/Team/Enterprise) | `OPENAI_API_KEY` |
| Google Gemini | `mergecraft auth gemini` → `GEMINI_API_KEY` (AI Studio) | `GEMINI_API_KEY` / `GOOGLE_GENERATIVE_AI_API_KEY` |
| Nous Portal | — (API key) | `mergecraft auth nous` → `NOUS_API_KEY` (`nous/deepseek/deepseek-v4-flash`) |
| Tencent TokenHub | — (API key) | `mergecraft auth tokenhub` → `TOKENHUB_API_KEY` (`tokenhub/hy3` + any TokenHub model) |
| MiniMax | — (API key) | `mergecraft auth minimax` → `MERGECRAFT_CUSTOM_PROVIDER_API_KEY` (`minimax/MiniMax-M3`; OpenAI-compatible, default `https://api.minimax.io/v1`) |
| Cursor Cloud | `mergecraft auth cursor` → `CURSOR_API_KEY` | `CURSOR_API_KEY` |
| Logfire tracing | `mergecraft auth logfire` → `MERGECRAFT_LOGFIRE_TOKEN` + `MERGECRAFT_TRACING_PROJECT` (local) and `LOGFIRE_TOKEN` (Actions) | see [`docs/TRACING.md`](TRACING.md) |

Subscription auth runs the official `claude` / `codex` / `gemini` CLIs as *you*
— the same credential your local coding agent uses. Only set env vars for
providers you actually use.

> **Codex on container runners:** Codex CLI's nested bubblewrap sandbox fails
> inside namespaced containers. On an already-isolated ephemeral runner, pass
> `codex_sandbox: danger-full-access`. mergeCraft never sets this itself —
> its own `shell`/`push` controls remain the security boundary
> ([issue #70](https://github.com/alexhawat/mergeCraft/issues/70)).

### Custom OpenAI-compatible provider

For any OpenAI-compatible endpoint (Nous Portal, Tencent TokenHub,
MiniMax, OpenRouter, a self-hosted vLLM, etc.), mergeCraft exposes one
mechanism that both harnesses consume. Issue
[#71](https://github.com/alexhawat/mergeCraft/issues/71) closes on this
surface — the **Codex half** is new in `v0.0.x`; the OpenCode half
shipped earlier in PR
[#79](https://github.com/alexhawat/mergeCraft/pull/79) and is
regression-tested.

#### Env-var convention

| Form | Example | Provider id |
|------|---------|-------------|
| Singleton back-compat alias (PR #79 / D7) | `MERGECRAFT_CUSTOM_PROVIDER_BASE_URL` + `MERGECRAFT_CUSTOM_PROVIDER_API_KEY` | `default` (or the active model's prefix when the model is `nous/...` or `tokenhub/...`) |
| Indexed multi-provider | `MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1` + `MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1`, `_2`, `_3`, … | `provider_1`, `provider_2`, `provider_3`, … |

Indexed env vars are operator-locked — both halves of each numeric pair
must be set with non-empty values; partial pairs are silently dropped.
Discovery enumerates every matching suffix, sorts by numeric `N`
ascending, and preserves gaps (no renumbering). When any indexed pair is
set, the singleton is ignored.

#### Action inputs (`with:`)

For the common single-provider case, two top-level `with:` inputs map
onto the singleton env vars — no need to name them in `env:`:

```yaml
- uses: alexhawat/mergeCraft@9cdd46d2f5521e663ad8f895ccd87b8fe8c15301
  with:
    model: default/your-model-id
    provider_base_url: https://api.example.com/v1
    provider_api_key_env: MY_PROVIDER_API_KEY   # the NAME of an env var, not the key value
  env:
    MY_PROVIDER_API_KEY: ${{ secrets.MY_PROVIDER_API_KEY }}  # wire the secret here
```

`provider_api_key_env` is the **env-var name** that holds the key;
mergeCraft reads that env var's value and re-exports it as
`MERGECRAFT_CUSTOM_PROVIDER_API_KEY`. The resolved key value is never
inlined into the workflow file and never logged (convention 7). For
multi-provider setups, fall back to the indexed env-var form below —
`with:` cannot enumerate multiple providers.

See [docs/action-reference.md](action-reference.md) for the full input list
(every `with:` key, literal defaults, and descriptions).

Behavioural note: `setup_failure_policy`'s and `setup_timeout`'s literal
`action.yml` default is an empty string (unset defers to the S1/D10 policy
described below); the *effective* runtime default when left unset is
`inconclusive` and `10m` respectively.

- S1 / D10 — what a trusted-tier `setupScript` failure (non-zero exit **or**
  timeout) maps to: `inconclusive` (effective default — neutral check
  conclusion, the run is no-verdict), `fail` (`configuration_error`), or
  `warn` (run continues; prompt still carries the failure text). Closed
  vocabulary — unknown values fail closed as `configuration_error` before the
  run starts.
- S1 / F6 — `setup_timeout`'s effective default (`10m`) is the wall-clock
  budget for `setupScript` (e.g. `5m`, `30s`, `1h`). A hanging install stalls
  the run otherwise. Reuses the same duration grammar as `timeout`. The setup
  runs as a session leader so a TERM → grace → KILL on the deadline reaches
  the whole process tree.

#### Action outputs

See [docs/action-reference.md](action-reference.md#action-outputs) for the
full output list.

#### Worked example — Nous-hosted DeepSeek V4 Flash

A raw pass-through slug reaches Nous's OpenAI-compatible endpoint via
either harness:

```yaml
- uses: alexhawat/mergeCraft@9cdd46d2f5521e663ad8f895ccd87b8fe8c15301
  with:
    model: nous/deepseek/deepseek-v4-flash  # raw pass-through slug
  env:
    NOUS_API_KEY: ${{ secrets.NOUS_API_KEY }}      # preset path — no MERGECRAFT_* needed
```

The model prefix `nous` resolves against `NOUS_API_KEY` (set above) and
`https://inference-api.nousresearch.com/v1`. The harness then registers
the provider, sets `enabled_providers = ["nous"]`, and serves the model.

#### Multi-provider — Codex-side indexed pairs

Two distinct OpenAI-compatible providers in one workflow (e.g. MiniMax
and Nous alongside OpenAI):

```yaml
- uses: alexhawat/mergeCraft@9cdd46d2f5521e663ad8f895ccd87b8fe8c15301
  with:
    model: provider_1/deepseek-v4-flash           # active provider_1
  env:
    MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1: https://inference-api.nousresearch.com/v1
    MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1:  ${{ secrets.NOUS_API_KEY }}
    MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_2: https://api.MiniMax.io/v1
    MERGECRAFT_CUSTOM_PROVIDER_API_KEY_2:  ${{ secrets.MINIMAX_API_KEY }}
```

Codex writes the corresponding `config.toml`:

```toml
[model_providers.provider_1]
name = "provider_1"
base_url = "https://inference-api.nousresearch.com/v1"
env_key = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1"
wire_api = "responses"

[model_providers.provider_2]
name = "provider_2"
base_url = "https://api.MiniMax.io/v1"
env_key = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY_2"
wire_api = "responses"
```

The `env_key` field references the **env-var name**, not the resolved
key value — convention 7. The harness reads the env var at exec time.

#### Which harness handles which

**Harness vs provider vs model.** OpenCode is the generic multi-provider
harness (OpenAI-compatible gateways, Nous, TokenHub, custom providers).
Codex is the OpenAI-native harness. **Nous** is a *provider* (inference
gateway); **DeepSeek** is a *model family* under that provider — not a
harness name. Set `harness:` in `.mergecraft/config.yaml` to pick the
runtime independently of `model:`; when unset, mergeCraft infers the
harness from the model slug (see matrix below).

| Model slug (unset `harness`) | Inferred harness | Explicit override exercised by tests |
|------------------------------|------------------|--------------------------------------|
| `nous/deepseek-v4-flash` | `opencode` | — |
| `nous/deepseek/deepseek-v4-flash` | `opencode` | — |
| `openai/gpt-5.3-codex` | `codex` | `harness: opencode` → `opencode` |
| `anthropic/claude-sonnet` | `claude` | `harness: opencode` → `opencode` |
| `google/gemini-3.1-pro-preview` | `gemini` | — |
| `cursor/cloud-agent` | `cursor` | — |
| `nous/deepseek/deepseek-v4-flash` + `harness: claude` | — | **configuration error** (names both halves) |

| Harness | Format written | Where it lives |
|---------|----------------|----------------|
| OpenCode | `provider.<id>.options.baseURL` / `.apiKey` (JSON) | `OPENCODE_CONFIG_CONTENT` (inline) and `OPENCODE_CONFIG` (file) |
| Codex CLI 0.146 | `[model_providers.<id>]` with `base_url` / `env_key` / `wire_api = "responses"` (TOML) | `$CODEX_HOME/config.toml` |

Both harnesses consume the same shared resolver
(`src/mergecraft/agents/openai_compatible_gateways.py`), so the env-var
contract is one — pass-through slugs (`<provider>/<model>`) route to
the right harness via the existing chain logic. OpenAI-compatible
models route to the OpenCode harness (no first-party Codex provider);
"true" OpenAI models route to Codex.

> PR [#79](https://github.com/alexhawat/mergeCraft/pull/79) shipped the
> OpenCode side of this feature; the Codex side, the `with:` input
> surface, and the env-var multi-provider extension all land together in
> this release — see issue
> [#71](https://github.com/alexhawat/mergeCraft/issues/71).

### Chain semantics — `model:` (#37 / W4)

The `with: model:` input is the **chain head**, not a chain kill-switch.
The configured `models:` / `modelFallbacks:` tail is preserved and walked
on credential miss or retryable failure. Issue
[#37](https://github.com/alexhawat/mergeCraft/issues/37) closes on this.

```yaml
# .mergecraft/config.yaml — the configured chain
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
modelFallbacks:
  anthropic/claude-sonnet:
    - anthropic/claude-opus
```

```yaml
# .github/workflows/mergecraft.yml — a single ``uses:`` step walks the
# chain. ``model:`` is the head; the configured tail follows.
- uses: alexhawat/mergeCraft@9cdd46d2f5521e663ad8f895ccd87b8fe8c15301
  with:
    model: anthropic/claude-sonnet        # ← chain head (your pick)
    # model_pin: enabled                 # ← uncomment to collapse to one model
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

Effective chain in the example above (with the operator-named head
preserved as the first entry):

```text
[anthropic/claude-sonnet, anthropic/claude-opus,
 openai/gpt-5.3-codex, google/gemini-3.1-pro-preview]
```

`MERGECRAFT_MODEL` (env var) follows the same rule: it joins as the head.

#### Escape hatch — `model_pin: enabled`

To restore the legacy "use exactly this model, suppress fallbacks"
semantics, set `model_pin: enabled` on the `with:` block, or
`modelPin: true` in `.mergecraft/config.yaml` (the action input wins):

```yaml
- uses: alexhawat/mergeCraft@9cdd46d2f5521e663ad8f895ccd87b8fe8c15301
  with:
    model: anthropic/claude-sonnet
    model_pin: enabled                 # ← chain collapses to [claude-sonnet]
```

#### Action parity with `models:`

`models:` is the chain, `model:` is the head. `models:` alone (without
`with: model:`) is supported and unchanged — the chain runs as configured.
A workflow that used to dual-step (`if: HAS_CLAUDE` → one review, else
`if: HAS_OPENAI` → another) collapses to a single step.

## 🧰 CLI

See [docs/cli.md](cli.md) for the full command list (one row per real leaf
command — pass `--help` to any invocation for its full flag set). Action
inputs and outputs live in [docs/action-reference.md](action-reference.md).

The bare `gha` group invocation (no subcommand) is the Docker action's
runtime entry point — it is a Typer group callback, not a
`registered_commands` leaf itself, so it is described here in prose rather
than as its own table row; `gha token` above is the one real leaf command
under that group.

## 🔒 Security model

- **BYOK by design** — credentials and repo content never leave GitHub
  Actions / your machine and this repo's code.
- **Comment triggers are authorized, not authenticated-by-content** — only
  `OWNER`/`MEMBER`/`COLLABORATOR` associations can invoke; the body is never
  consulted. Two opt-in knobs (`allow_pr_target_comments`,
  `commentInvocationAllowlist`) each widen exactly one axis.
- **Learnings are fail-closed** — entries land in `## Staging`; only
  maintainer-associated authors promote to `## Active`, and active entries are
  nonce-fenced before the model reads them.
- **The approval check is structural** — `success` requires a completed trusted
  run with no Critical/Major findings; `failure` on any blocker; `neutral` for
  crashes, timeouts, and untrusted tiers. The agent's narrative approval is
  advisory only.
- **Analyzers under low trust run untrusted-only** — no secrets, no network, no
  PR-authored command construction; exclusions are reported as named skips.
- **Agent subprocess env is an explicit allowlist** — agent CLIs never
  inherit the full process environment. Stripped by default: ``GIT_ASKPASS``,
  ``GITHUB_TOKEN``/``GH_TOKEN``, ``ACTIONS_ID_TOKEN_*``, and every non-active
  provider API key. Git authentication for agent operations is brokered
  per-invocation via MCP git's ``http.extraHeader`` injection, not ambient
  askpass. Retained askpass files (entrypoint bookkeeping only) live at
  ``0o600`` inside a ``0o700`` credentials directory the agent cannot read.
  Run temp dirs and registered leak-surface paths are removed on success and
  failure; ``wipe_runner_leak_surface`` only unlinks mergeCraft-owned paths.
- **`push` / `shell` value semantics are defined in the action-inputs
  table** — see [Action inputs (`with:`)](#action-inputs-with) above for the
  `disabled` / `restricted` / `enabled` vocabulary both inputs share.
- **Containment hardening** — ``safe.directory`` is scoped to
  ``$GITHUB_WORKSPACE`` and registered cross-repo checkout roots (no wildcard).
  Git hooks run only when ``shell: enabled``; ``restricted`` and ``disabled``
  neutralize hooks via ``core.hooksPath``. ``cwd`` and MCP shell
  ``working_directory`` must resolve inside allowed workspace roots. Agent CLI
  subprocesses drop to the unprivileged ``mergecraft`` user via ``setpriv``
  while the action entrypoint stays root for GitHub file commands.
- **Network is outside the hard sandbox guarantee when ``unshare --net`` is
  unavailable (W12.7)** — on CI hosts that support it, untrusted MCP shell
  spawns with ``unshare --pid --net`` so the child has an empty network
  namespace. Where that probe fails (macOS runners, restricted containers,
  missing CAP_SYS_ADMIN), shell egress is not kernel-isolated; the W2
  credential allowlist (no ambient ``GITHUB_TOKEN`` / provider keys / askpass)
  remains the binding control. Trusted-tier shell does not force ``--net`` so
  provider CLIs can still reach their APIs.

Report vulnerabilities via [SECURITY.md](../SECURITY.md). What a review does and
never does: [REVIEW-CHECKS.md](../REVIEW-CHECKS.md).

## ⚙️ Workflow-placement gotchas (`pull_request_target`)

GitHub resolves `pull_request_target` workflows from the **default branch** —
the workflow file *and* the checked-out commit, whatever base the PR targets
([Nov 2025 policy](https://github.blog/changelog/2025-11-07-actions-pull_request_target-and-environment-branch-protections-changes/),
effective 2025-12-08). Three consequences:

- **A copy on a non-default trunk is inert.** If `main` is a stub and real work
  lands on a staging branch, this workflow still has to live on `main`.
- **`GITHUB_REF` / `GITHUB_SHA` point at the default branch**, not the PR base —
  so a bare `actions/checkout` lands on default-branch tip and
  `.mergecraft/config.yaml` is read from there. Environment branch-protection
  rules also now evaluate against the default branch; update environment
  filters if you gate secrets that way.
- **A PR that edits this workflow is still reviewed — by the default-branch
  copy.** Its own edits apply to the *next* PR, after merge. (That much was
  always true of `pull_request_target`; what Nov 2025 changed is base branch →
  default branch.)

If the review is **not** a required check, prefer plain `pull_request` — simpler,
and no secrets in scope. The case for accepting `pull_request_target` is narrower
than it looks: GitHub cannot build `refs/pull/N/merge` for a conflicted PR, so
`pull_request` runs are skipped and a *required* review check sits unreported
for as long as the conflict lasts. `pull_request_target` still fires on
`synchronize` in that state, so the review lands — and its verdict is visible —
while the PR is still conflicted.

That is the whole of the benefit, and it is worth stating plainly: pushing the
conflict fix to the PR branch fires `synchronize` and clears a `pull_request`
check too, so the gap is the conflicted window, not a permanent block. It
outlasts the conflict only when the conflict disappears *without* a push to the
head branch — the base moved, say — because nothing then re-triggers the run.
A conflicted PR is unmergeable on its own account anyway, so weigh this against
running with secrets in scope rather than treating it as decisive.

If you pin the action SHA in more than one place, gate the copies against each
other in CI — and read the workflow side from the **default branch**
(`git show origin/main:.github/workflows/mergecraft.yml`), not the working tree.
Bump order is default branch first, local pin second.

Since [June 2026](https://github.blog/changelog/2026-06-18-safer-pull_request_target-defaults-for-github-actions-checkout/)
`actions/checkout` refuses to check out fork PR code under `pull_request_target`
unless you pass `allow-unsafe-pr-checkout` (v7 GA 2026-06-18, backported to all
supported majors 2026-07-20). mergeCraft's shipped workflows are unaffected —
they check out the default branch with no `ref:` and reach PR content through
`checkout_pr` and the API, never by executing PR-authored code with secrets in
scope.

Full rationale in the collapsible sections of
[documentation index](README.md).
