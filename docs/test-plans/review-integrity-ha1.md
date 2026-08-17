# Review integrity HA1 — typed `ProviderConfig` — test plan

Wave plan: `.ignorelocal/01-review-integrity-wave-plan.md` (PR HA1)
Worktree: `../mergecraft-ha1-provider-config` @ `wave/ha1-provider-config`
Authoring wave: **HA1.1** (tests-first — this file). Implementation: **HA1.2**.
xfail-reconciliation: **post-HA1.2** (this file).

HA1 types the existing OpenAI-compatible provider surface. It does **not**
change the wire contract (**D16**): `MERGECRAFT_CUSTOM_PROVIDER_*` keeps
working exactly as documented in `README.md`, and `build_custom_provider`'s
emitted JSON stays byte-identical to `origin/pre-0.0.1`. Capabilities are
declarative and fail loud (**D12**): requesting an unsupported provider
capability is a configuration error *before* agent execution.

Target API (HA1.2): frozen Pydantic `ProviderConfig` on
`src/mergecraft/agents/openai_compatible_gateways.py` — **not** the catalog
namesake in `src/mergecraft/models.py` — with fields `provider_id`,
`model_id`, `base_url`, `api_key_env`, `adapter`, `capabilities`,
`extra_options`, plus `context_limit: int | None`. The resolved key is read
through `api_key_env` at use time and is **never stored on the model**.
`build_custom_provider` and `_custom_provider_ids` consume `ProviderConfig`
internally.

## xfail schedule

All HA1.2 markers used `strict=False` (`pyproject.toml` sets `xfail_strict =
true`; an early-passing xfail must be XPASS, not a hard failure). **Cleared
after HA1.2** — the eight typed-model / D12 / credential-hygiene cases are
real passes; the four regression pins were never marked.

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **HA1.2** | `test_gateway_env_pairs_produce_typed_configs` | `green after HA1.2: ProviderConfig` | cleared post-HA1.2 |
| **HA1.2** | `test_api_key_never_appears_in_repr` | same | cleared post-HA1.2 |
| **HA1.2** | `test_api_key_never_appears_in_json_dump` | same | cleared post-HA1.2 |
| **HA1.2** | `test_api_key_never_reaches_trace_attrs` | same | cleared post-HA1.2 |
| **HA1.2** | `test_api_key_never_reaches_run_packet` | same | cleared post-HA1.2 |
| **HA1.2** | `test_unsupported_capability_is_a_configuration_error` | same | cleared post-HA1.2 |
| **HA1.2** | `test_capability_declaration_round_trips` | same | cleared post-HA1.2 |
| **HA1.2** | `test_custom_base_url_validates` | same | cleared post-HA1.2 |

Regression pins below have **no** xfail — they must pass against current
`resolve_gateway_endpoints` / `build_custom_provider` / `_custom_provider_ids`
behaviour on `pre-0.0.1`.

## HA1.2 xfail reconciliation (2026-08-16)

Removed `_HA1_2_XFAIL` and all eight `green after HA1.2: ProviderConfig`
markers from `tests/agents/test_provider_config.py`. Suite is 12 real
passes (0 xfail / 0 xpass). Added a closed-vocabulary pin:
`CAPABILITY_VALUES == _CLOSED_CAPABILITIES` in
`test_capability_declaration_round_trips` (deleting or widening the public
constant fails). Private `_provider_config_from_env_pair` /
`_api_key_from_env` remain untested by design. HA1 Final is unchanged.

## Contract matrix

| # | Decision / convention | Layer | Scenario | Primary test |
|---|----------------------|-------|----------|--------------|
| HA1.1a | D16 — `_N` env pairs type as `ProviderConfig` with today's ids | unit | happy: `_1` + `_2` → `provider_1`, `provider_2` | `test_gateway_env_pairs_produce_typed_configs` |
| HA1.1b | D16 — partial pair dropped | unit | edge: only `API_KEY_1` set | `test_partial_pair_is_dropped` |
| HA1.1c | D16 — index gaps preserved (no renumbering) | unit | edge: `_1` + `_3`, `_2` absent | `test_gaps_in_indices_are_preserved` |
| HA1.1d | D16 — named presets | unit | happy: `nous/*` via `NOUS_API_KEY`, `tokenhub/*` via `TOKENHUB_API_KEY` | `test_named_presets_still_resolve` |
| HA1.1e | convention 5 — key never in `repr`/`str` | unit | error: canary planted in env, absent from serialisation | `test_api_key_never_appears_in_repr` |
| HA1.1f | convention 5 — key never in JSON dump | unit | error: `model_dump` / `model_dump_json` | `test_api_key_never_appears_in_json_dump` |
| HA1.1g | convention 5 — key never in trace attrs | integration | construct → emit span → canary absent from event | `test_api_key_never_reaches_trace_attrs` |
| HA1.1h | convention 5 — key never in run packet | integration | construct → `build_run_packet` → canary absent | `test_api_key_never_reaches_run_packet` |
| HA1.1i | D12 — unsupported capability is a configuration error | unit | error: request `structured_output` when undeclared; raises `_ConfigurationError` before any agent run | `test_unsupported_capability_is_a_configuration_error` |
| HA1.1j | D12 — declared capabilities round-trip | unit | happy: dump/validate preserves `capabilities`, `extra_options`, `context_limit` | `test_capability_declaration_round_trips` |
| HA1.1k | malformed `base_url` rejected before execution | unit | error: `base_url="not a url"` → `ValidationError` | `test_custom_base_url_validates` |
| HA1.1l | D16 — emitted OpenCode JSON byte-identical | functional | happy/edge: 8 env combinations vs `pre-0.0.1` snapshots | `test_emitted_opencode_config_is_byte_identical_for_existing_inputs` |

## Byte-identity fixture set (HA1.1l)

Snapshots captured from `build_custom_provider` at `origin/pre-0.0.1` (HEAD of
this worktree at authoring). Canonical JSON (`sort_keys=True`, compact
separators) is the equality form.

| Label | Model | Env combination |
|-------|-------|-----------------|
| `indexed_pairs` | `provider_1/some-model` | `_1` + `_2` gateway pairs |
| `named_nous` | `nous/deepseek/deepseek-v4-flash` | `NOUS_API_KEY` |
| `named_tokenhub` | `tokenhub/hy3` | `TOKENHUB_API_KEY` |
| `custom_singleton` | `default/some-model` | singleton `MERGECRAFT_CUSTOM_PROVIDER_{BASE_URL,API_KEY}` |
| `custom_base_url_overrides_nous` | `nous/deepseek/deepseek-v4-flash` | singleton custom base URL overrides named preset |
| `partial_pair` | `provider_1/some-model` | only `API_KEY_1` (emits `null`) |
| `index_gaps` | `provider_1/some-model` | `_1` + `_3`, `_2` absent |
| `indexed_overrides_singleton` | `provider_1/some-model` | indexed `_1` plus singleton (indexed wins) |

## Guard-deletion proof (convention 5)

`_assert_key_absent_from_model` fails if HA1.2's "never store the key"
guard is deleted:

- `api_key` must not be a Pydantic field or computed field
- the planted canary (`ha1-canary-NEVER-LEAK-9f3c2a1b`, not `sk-`/`ghp_`
  shaped so sink deny-value redaction cannot hide it) must not appear in
  `repr`, `str`, `model_dump`, span attrs, or the run packet

A test that only asserted "redaction replaced `api_key`" would pass with
the key stored on the model — that is the defect these four tests refuse
to protect.

## Named deliverable symbols

| Symbol | Direct test |
|--------|-------------|
| `ProviderConfig` | `test_gateway_env_pairs_produce_typed_configs` (+ credential / capability tests) |
| `require_capabilities` | `test_unsupported_capability_is_a_configuration_error` |
| `CAPABILITY_VALUES` | `test_capability_declaration_round_trips` (`== _CLOSED_CAPABILITIES`) |
| `build_custom_provider` | `test_emitted_opencode_config_is_byte_identical_for_existing_inputs` |
| `_custom_provider_ids` | `test_partial_pair_is_dropped`, `test_gaps_in_indices_are_preserved`, `test_named_presets_still_resolve` |

## RED acceptance (HA1.1, historical)

- `uv run pytest --collect-only -q tests/agents/test_provider_config.py` → **12**
  collected, zero collection errors (`ProviderConfig` imports live inside
  test bodies / helpers called only from xfailed tests).
- File run at HA1.1: **4 pass** (regression pins) + **8 xfail** (typed model /
  D12 / credential hygiene). Do not edit `src/` to make RED tests green.
- `make lint` and `make typecheck` clean.

Post-HA1.2 reconciliation: **12 passed**, 0 xfail, 0 xpass, 0 fail.

## Implementation notes for HA1.2

- Import `ProviderConfig` from `mergecraft.agents.openai_compatible_gateways`.
  Keep `mergecraft.models.ProviderConfig` (catalog) unchanged.
- `resolve_gateway_endpoints()` returns `dict[str, ProviderConfig]` keyed by
  today's ids (`provider_<N>` / `default`). `api_key_env` is the env-var
  *name*; the resolved value is read at emit time so OpenCode JSON still
  carries `options.apiKey` (D16 / the byte-identity pin).
- Closed capability set: `tool_calling`, `streaming`, `reasoning_controls`,
  `structured_output`, `custom_base_url`, `openai_compatible`,
  `native_opencode`. `context_limit: int | None` is a sibling field.
- `require_capabilities(config, requested)` raises
  `mergecraft.main._ConfigurationError` naming the missing capability
  (match `structured_output`) without invoking an agent.
- `base_url="not a url"` is a Pydantic `ValidationError` at construction.
- Tests are owned by test-creator. HA1.2 xfails were cleared in the
  post-impl reconciliation pass; HA1 Final is unchanged.
