# Open issues sweep — Batch E test plan (W16 RED)

Wave plan: `.ignorelocal/waves/open-issues-sweep-wave-plan.md`
Worktree: `mergecraft-issues-e-model-routing` @ `wave/issues-e-model-routing`

## xfail schedule

| Wave | Test | Marker reason |
|------|------|---------------|
| **W17** | `tests/config/test_model_preference_config.py::test_load_repo_settings_parses_models_ordered_list` | `green after W17: models list parses into RepoSettings (#14)` |
| **W17** | `tests/config/test_model_preference_config.py::test_load_repo_settings_scalar_model_unchanged_without_models_list` | `green after W17: scalar model back-compat unchanged (#14)` |
| **W18** | `tests/cli/test_models_cmd.py::test_models_show_prints_config_order_with_env_override` | `green after W18: mergecraft models show prints effective order (#14)` |
| **W19** | `tests/utils/test_model_chain_resolve.py::test_model_chain_skips_slugs_without_credentials` | `green after W19: chain skips entries without required credentials (#14)` |
| **W19** | `tests/utils/test_model_chain_resolve.py::test_model_chain_advances_on_retryable_provider_failure` | `green after W19: chain advances on retryable provider failure (#14)` |
| **W19** | `tests/utils/test_model_chain_resolve.py::test_model_chain_caps_attempts_at_max_depth` | `green after W19: chain caps total attempts at max depth (#14)` |

All cross-wave markers use `strict=False`.

## Contract matrix

| Issue | Decision | Layer | Scenario | Primary test |
|-------|----------|-------|----------|--------------|
| **#14** | D13 — additive `models:` list; scalar `model:` unchanged | Unit | Happy path — ordered `models:` YAML → `RepoSettings.models` | `test_model_preference_config.py::test_load_repo_settings_parses_models_ordered_list` |
| **#14** | D13 | Unit | Back-compat — scalar `model:` only, no `models` key | `test_model_preference_config.py::test_load_repo_settings_scalar_model_unchanged_without_models_list` |
| **#14** | W18 CLI contract | Functional | Happy path — `models show` lists config order + `MERGECRAFT_MODEL` override | `test_models_cmd.py::test_models_show_prints_config_order_with_env_override` |
| **#14** | W19 runtime chain | Unit | Edge — skip slug when required secret absent | `test_model_chain_resolve.py::test_model_chain_skips_slugs_without_credentials` |
| **#14** | W19 | Integration | Error handling — retryable provider failure advances chain | `test_model_chain_resolve.py::test_model_chain_advances_on_retryable_provider_failure` |
| **#14** | W19 | Unit | Edge — cap total attempts at `_MAX_FALLBACK_DEPTH` | `test_model_chain_resolve.py::test_model_chain_caps_attempts_at_max_depth` |

## Pinned module surface (for impl waves)

| Module | Expected symbols |
|--------|------------------|
| `mergecraft.config.settings.RepoSettings` | `models: list[str] \| None`, optional `model_fallbacks: dict[str, list[str]] \| None` (`modelFallbacks` alias); scalar `model` unchanged |
| `mergecraft.cli.models_cmd` | Typer app with `list`, `set`, `show`; registered on root `app` as `models` |
| `mergecraft.utils.agent_resolve` | `select_runnable_model_slug(settings=…)` — first chain entry with credentials; `run_with_model_chain(settings=…, run_once=…, max_attempts=…)` — walk chain, skip missing creds, advance when `AgentResult.metadata["retryable"]` is true, cap attempts |

## Implementation notes for impl waves

- **W17:** Add `models` / `modelFallbacks` to `RepoSettings`; un-xfail both config parse tests.
- **W18:** Add `cli/models_cmd.py` + register on `app`; `show` prints effective order (config + `MERGECRAFT_MODEL`); un-xfail CLI test.
- **W19:** Implement chain resolution in `agent_resolve.py`; retryable failures use `AgentResult.metadata["retryable"] = True`; un-xfail all three chain tests.
