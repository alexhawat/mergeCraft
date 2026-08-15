# Review integrity HA3 — explicit harness selection — test plan

Wave plan: `.ignorelocal/01-review-integrity-wave-plan.md` (PR HA3)
Worktree: `../mergecraft-ha3-harness-split` @ `wave/ha3-harness-split`
Authoring wave: **HA3.1** (tests-first — this file). Implementation: **HA3.2**.
xfail-reconciliation: **post-HA3.2** (this file).

HA3 separates harness selection from provider/model selection. Locked
**D11**: `harness:` set → use it. Unset → today's provider/model inference.
Unsupported combination → configuration error, never silent routing.
Existing `nous/deepseek-*` configs must keep working untouched.

The HA3 wave-plan bullets say "D2" for the explicit override; the baked
table's **D11** wins.

Target API (HA3.2): `RepoSettings.harness` on
`src/mergecraft/config/settings.py` is
`Literal["opencode", "codex", "claude", "gemini", "cursor"] | None = None`
(optional, default `None` = today's inference). Resolver
`resolve_harness(settings, slug)` on `src/mergecraft/utils/agent_resolve.py`:
explicit harness → validate the `(harness, provider, model)` triple against
HA1 capabilities → else `_agent_mode_for_slug`. Unsupported combos raise an
existing configuration-error shape (`ModelFallbackPolicyError` /
`main._ConfigurationError` / `ValidationError`) so
`main._classify_error_outcome` maps them to `configuration_error` without a
new branch.

Today's inference (`_agent_mode_for_slug`): anthropic→claude, openai→codex,
google→gemini, cursor→cursor, else opencode. `nous/*` therefore already
selects opencode.

## xfail schedule

All HA3.2 markers used `strict=False` (`pyproject.toml` sets `xfail_strict =
true`; an early-passing xfail must be XPASS, not a hard failure). **Cleared
after HA3.2** — the five explicit-harness / validation / telemetry cases are
real passes; the four regression pins were never marked.

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **HA3.2** | `test_explicit_harness_overrides_inference` | `green after HA3.2: harness selection` | cleared post-HA3.2 |
| **HA3.2** | `test_opencode_with_non_nous_provider_resolves` | same | cleared post-HA3.2 |
| **HA3.2** | `test_unsupported_combination_is_a_configuration_error` | same | cleared post-HA3.2 |
| **HA3.2** | `test_unknown_harness_value_fails_closed` | same | cleared post-HA3.2 |
| **HA3.2** | `test_harness_reaches_telemetry` | same | cleared post-HA3.2 |

Regression / compatibility pins below have **no** xfail — they must pass
against current `_agent_mode_for_slug` behaviour on the HA1 stack.

## HA3.2 xfail reconciliation (2026-08-16)

Removed `_HA3_2` and all five `green after HA3.2: harness selection` markers
from `tests/config/test_harness_selection.py`. Suite is 9 real passes
(0 xfail / 0 xpass). Added direct pins for the previously unreferenced
helpers: `_NATIVE_HARNESS_PROVIDERS` (closed native map in the remain-
selectable tests), `_OPENCODE_NATIVE_PROVIDERS` (exact frozenset in the
override test), and `_harness_supports_provider` (True for opencode×openai/
anthropic; False for claude×nous). `resolve_harness` stays imported at
module level. The four inference pins were never xfailed. HA3 Final is
unchanged.

## Contract matrix

| # | Decision / convention | Layer | Scenario | Primary test |
|---|----------------------|-------|----------|--------------|
| HA3.1a | D11 — existing `nous/deepseek-*` YAML with harness unset still selects opencode | functional | happy: load `.mergecraft/config.yaml` | `test_existing_nous_config_still_selects_opencode` |
| HA3.1b | D11 — explicit `harness:` overrides inference | unit | happy: openai infers codex / anthropic infers claude; `harness: opencode` wins both | `test_explicit_harness_overrides_inference` |
| HA3.1c | OpenCode × non-Nous OpenAI-compatible model, same opencode agent (no review-logic duplication) | integration | happy: `openai/gpt-5.3-codex` + `harness: opencode` → `agents["opencode"]` | `test_opencode_with_non_nous_provider_resolves` |
| HA3.1d | Codex remains selectable | unit | happy: openai slug, harness unset → `codex` | `test_codex_remains_selectable` |
| HA3.1e | Claude / Gemini / Cursor remain selectable | unit | happy: anthropic→claude, google→gemini, cursor→cursor | `test_claude_gemini_cursor_remain_selectable` |
| HA3.1f | D11 — unsupported (harness, provider/model) is a configuration error naming both halves | unit | error: `harness: claude` × `nous/deepseek/deepseek-v4-flash`; maps to `configuration_error` | `test_unsupported_combination_is_a_configuration_error` |
| HA3.1g | Unknown harness *value* fails closed (`Literal` + `extra="forbid"`) | unit | error: `harness: "foo"` is `ValidationError` naming `harness`; valid members accepted | `test_unknown_harness_value_fails_closed` |
| HA3.1h | Resolved harness recorded on the attempt | integration | happy: drive `run_with_model_chain`; span attr or result metadata carries `opencode` | `test_harness_reaches_telemetry` |
| HA3.1i | Inference path unchanged when harness unset | unit | regression: fixture matrix of today's slugs vs `_agent_mode_for_slug` | `test_inference_path_unchanged_when_harness_unset` |

## Combinations this suite exercises

HA3.2 docs (`docs/compatibility-matrix.md`) must list **only** combinations a
test exercises. This table is that set:

| Harness | Provider / model | How selected | Test |
|---------|------------------|--------------|------|
| opencode | nous / `nous/deepseek/deepseek-v4-flash` | inference (unset) | `test_existing_nous_config_still_selects_opencode`, `test_inference_path_unchanged_when_harness_unset` |
| opencode | nous / `nous/deepseek-v4-flash` | inference (unset) | `test_inference_path_unchanged_when_harness_unset` |
| opencode | openai / `openai/gpt-5.3-codex` | explicit override | `test_explicit_harness_overrides_inference`, `test_opencode_with_non_nous_provider_resolves`, `test_harness_reaches_telemetry` |
| opencode | anthropic / `anthropic/claude-sonnet` | explicit override | `test_explicit_harness_overrides_inference` |
| codex | openai / `openai/gpt-5.3-codex` | inference (unset) | `test_codex_remains_selectable`, `test_inference_path_unchanged_when_harness_unset` |
| claude | anthropic / `anthropic/claude-sonnet` | inference (unset) | `test_claude_gemini_cursor_remain_selectable`, `test_inference_path_unchanged_when_harness_unset` |
| gemini | google / `google/gemini-3.1-pro-preview` | inference (unset) | `test_claude_gemini_cursor_remain_selectable`, `test_inference_path_unchanged_when_harness_unset` |
| cursor | cursor / `cursor/cloud-agent` | inference (unset) | `test_claude_gemini_cursor_remain_selectable`, `test_inference_path_unchanged_when_harness_unset` |
| *(rejected)* | claude × nous / `nous/deepseek/deepseek-v4-flash` | explicit, unsupported | `test_unsupported_combination_is_a_configuration_error` |
| *(rejected)* | `harness: "foo"` | unknown value | `test_unknown_harness_value_fails_closed` |

Architecture reminder for HA3.2 docs: OpenCode = generic multi-provider
harness · Codex = OpenAI-native harness · Nous = provider · DeepSeek = model
family.

## Guard-deletion proof

- **Override (D11).** `test_explicit_harness_overrides_inference` first pins
  that openai infers `codex` and anthropic infers `claude`, then asserts
  `resolve_harness` returns `opencode` when that field is set. Deleting the
  explicit-wins branch makes the test fail.
- **Unsupported combo (D11).**
  `test_unsupported_combination_is_a_configuration_error` requires a raise
  of an *existing* configuration-error type whose message names **both**
  `claude` and the Nous/DeepSeek half, and whose
  `_classify_error_outcome` mapping is `configuration_error`. Silent routing
  (returning a harness) fails the `pytest.raises`. A new exception type that
  is not already in `_classify_error_outcome` also fails.
- **Literal surface.** `test_unknown_harness_value_fails_closed` accepts every
  closed member *before* rejecting `"foo"`, so today's unknown-*key* forbid
  cannot satisfy the test.

## Named deliverable symbols

| Symbol | Direct test |
|--------|-------------|
| `RepoSettings.harness` | `test_unknown_harness_value_fails_closed` (+ override / telemetry tests) |
| `resolve_harness` | `test_explicit_harness_overrides_inference`, `test_opencode_with_non_nous_provider_resolves`, `test_unsupported_combination_is_a_configuration_error` |
| `_agent_mode_for_slug` | `test_existing_nous_config_still_selects_opencode`, `test_inference_path_unchanged_when_harness_unset`, `test_codex_remains_selectable`, `test_claude_gemini_cursor_remain_selectable` |
| `_NATIVE_HARNESS_PROVIDERS` | `test_codex_remains_selectable`, `test_claude_gemini_cursor_remain_selectable` |
| `_OPENCODE_NATIVE_PROVIDERS` | `test_explicit_harness_overrides_inference` |
| `_harness_supports_provider` | `test_explicit_harness_overrides_inference`, `test_unsupported_combination_is_a_configuration_error` |

## RED acceptance (HA3.1)

- `uv run pytest --collect-only -q tests/config/test_harness_selection.py` →
  **9** collected, zero collection errors (`resolve_harness` /
  `RepoSettings.harness` imports live inside xfailed test bodies).
- File run at HA3.1: **4 pass** (compatibility / inference pins) + **5 xfail**
  (explicit harness, OpenCode×non-Nous, unsupported combo, unknown value,
  telemetry). Do not edit `src/` to make RED tests green.
- `make lint` and `make typecheck` clean.

## Post-HA3.2 acceptance (xfail reconciliation)

- File run: **9 passed, 0 xfail, 0 xpass** on
  `tests/config/test_harness_selection.py`. Existing
  `tests/config/test_settings.py`, `tests/config/test_extra_forbid.py`, and
  `tests/agents/test_resolve.py` must not newly fail.
- `make lint` and `make typecheck` clean. Tests-only commit; HA3 Final
  unchanged.

## Implementation notes for HA3.2

- Add `harness` on `RepoSettings` with the five-value Literal, default
  `None`. `extra="forbid"` stays; `"foo"` is a `ValidationError` naming
  `harness`.
- Implement `resolve_harness(settings, slug) -> str` in
  `src/mergecraft/utils/agent_resolve.py`. When `settings.harness` is set,
  validate `(harness, provider, model)` against HA1 `ProviderConfig`
  capabilities and return it; otherwise call `_agent_mode_for_slug(slug)`.
- Raise `ModelFallbackPolicyError` or `main._ConfigurationError` (already
  mapped by `_classify_error_outcome`) for unsupported combos. The message
  must name the harness **and** the provider/model.
- Stamp the resolved harness onto the `agent.attempt` span (`agent.mode` /
  `model.mode` / `gen_ai.agent.name` or a dedicated `harness` attr) and/or
  `AgentResult.metadata["harness"]` so `test_harness_reaches_telemetry`
  sees `opencode` when the override is in force.
- Existing `nous/deepseek-*` configs without `harness:` must keep selecting
  opencode — that is HA3's compatibility test.
- Tests are owned by test-creator. HA3.2 must not edit `tests/`.
