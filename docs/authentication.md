# Authentication


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


**See also:** [`docs/action-reference.md`](action-reference.md) · [`README.md`](../README.md)
