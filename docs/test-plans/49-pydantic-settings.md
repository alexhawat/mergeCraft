# Test plan — one reader for env and `.env` settings (release half)

**Red wave:** the `test-creator` wave of the pydantic-settings plan (the first,
release-carrying pull request).
**Green waves:** the foundation + one `.env` reader; then the tracing family,
its environment layer and its Action inputs.

This is the RED suite for the release half of the plan — the typed environment
foundation, the single `.env` reader, the provider-side `.env` read, and the
tracing environment plus its Action inputs. The parity migration of the
remaining read sites is a separate pull request and is **not** covered here.

The suite **collects** with no import/collection errors and `make lint` +
`make typecheck` are clean. Every not-yet-implemented assertion is a plain
failure: no `xfail` marker is used, so the repository's xpass ratchet never
fires and no marker reconciliation is needed when an implementation lands. Any
symbol that does not exist yet is imported **inside the test body**, never at
module import time.

## Marker policy

No `xfail` markers. Each contract below names the wave that turns its plain
failures green; a green wave simply makes them pass.

## Scenario matrix

Every contract has a happy path, edge cases (empty / boundary / quoting /
case / ordering) and an error case that asserts the failure type and the
message contract (the variable named, the value never echoed).

---

## 1 — the typed environment foundation

| Layer | Test file | Asserts |
| --- | --- | --- |
| Unit (happy) | `tests/config/test_env_settings_base.py::test_env_bool_accepts_the_true_spellings`, `…::test_env_bool_accepts_the_false_spellings` | the eight spellings, case-insensitive and stripped, parse `True` / `False` |
| Unit (error) | `…::test_env_bool_rejects_widened_spellings_as_none` | `t`, `y`, `ture`, `2`, `-1`, `""` return `None` — the vocabulary never widens to Pydantic's `bool` |
| Unit (edge) | `…::test_env_bool_none_stays_none` | an absent value is `None`, not `False` |
| Unit (happy/edge) | `…::test_exact_flag_is_enabled_only_by_exactly_one` | `"1"` enables; `" 1"`, `"1 "`, `"01"`, `"true"` and `None` do not |
| Unit | `…::test_from_env_reads_nothing_from_the_process_environment` | a mapping-only read never falls back to the process environment |
| Unit | `…::test_from_env_reflects_the_mapping_it_is_given` | the mapping is the only input |
| Unit (edge) | `…::test_a_later_setenv_is_seen_by_the_next_read` | no cached instance: a second read sees a later change |
| Unit | `…::test_registered_models_are_constructed_per_read` | no registered model is a singleton |
| Unit (happy) | `…::test_registered_models_are_settings_models`, `…::test_validate_env_settings_is_callable` | the registry holds settings models and has one startup entry point |
| Unit (error) | `…::test_no_registered_model_dump_leaks_a_secret` | `repr`, `model_dump` and `model_dump_json` mask every secret field; secret fields are `SecretStr` |
| Unit | `…::test_env_settings_error_is_a_value_error`, `…::test_env_settings_error_names_the_variable_never_the_value` | the configuration error is a `ValueError`; its message names the variable and never the value |

**Pinned API.** `mergecraft.config.env` exposes `EnvBool` (a Pydantic field
type), `ExactFlag` (callable; `.enabled == (raw == "1")`), `from_env(model,
mapping)`, `registered_env_models()`, `validate_env_settings()` and
`EnvSettingsError` (a `ValueError` subclass constructed as
`EnvSettingsError(variable, value)`).

## 2 — one `.env` reader, one meaning

| Layer | Test file | Asserts |
| --- | --- | --- |
| Integration (happy) | `tests/cli/test_provider_env_map.py::test_read_env_map_matches_the_startup_load_on_the_corpus` | `provider`'s reader returns exactly what the startup load exports for a corpus with `export `, an empty value, a bare key, single/double quotes, a comment, an inline comment, interpolation and a quoted `#` |
| Integration (happy) | `…::test_read_env_map_round_trips_write_env_value_quoting`, `…::test_read_env_map_round_trips_a_single_quoted_multiline_json_blob` | a value written by the auth writer reads back verbatim, whatever quote mode it chose |
| Integration (edge) | `…::test_read_env_map_ignores_a_missing_file`, `…::test_read_env_map_keeps_a_key_whose_value_is_empty` | a missing file is an empty map; `B=` is present with an empty value |
| Functional (happy) | `tests/cli/test_local_env_loader.py::test_corpus_loads_exactly_like_load_dotenv` | the startup load produces the same `os.environ` as `load_dotenv(override=False)` |
| Functional (edge) | `…::test_corpus_pre_set_environment_wins` | a pre-set key wins; interpolation reads the process value |
| Functional (guard) | `…::test_actions_reads_only_the_explicit_env_over_the_workspace_corpus`, `tests/cli/test_local_env_loader.py` (Actions cases), `tests/cli/test_local_env_path.py` (path cases) | inside GitHub Actions the workspace `.env` is not read; an explicit environment file is, and the path anchor and the parser agree |

`tests/cli/test_provider_status_cmd.py` and `tests/cli/test_jev_cmd.py` are
unchanged and must stay green once the reader moves.

## 3 — the tracing environment layer: parity and fail-closed

| Layer | Test file | Asserts |
| --- | --- | --- |
| Unit (parity) | `tests/tracing/test_env_layer_parity.py::test_env_layer_parity` | a frozen grid: every tracing environment key x {unset, empty, valid, malformed-for-non-control-keys} resolves to the exact frozen env-layer and merged dicts |
| Unit (control) | `…::test_malformed_control_value_fails_closed`, `…::test_malformed_control_value_maps_through_the_env_model` | a malformed value on the enable flag, region, content level or untrusted-content export raises a configuration error naming the key and not the value |
| Integration (parity) | `…::test_enabled_matrix` | the frozen config x environment x CLI `enabled` arithmetic, including `true` propagation and the CLI `--no-tracing` override |
| Integration | `tests/tracing/exporters/test_cli_precedence.py::test_env_layer_malformed_control_value_fails_closed`, `…::test_env_layer_unknown_region_is_ignored_today_becomes_an_error` | the resolver raises through the typed model instead of dropping the key |
| Integration (guard) | `…::test_env_layer_region_is_stripped_and_lowercased`, `…::test_env_layer_empty_tracing_to_stays_present` | well-formed values keep the current normalisation and the empty-value presence rule |

The trace-directory, tracing-target, endpoint, token and project keys carry no
control vocabulary; a malformed-looking value on them keeps exactly today's
behaviour (frozen in the grid) and never raises.

## 4 — content capture: parity and fail-closed

| Layer | Test file | Asserts |
| --- | --- | --- |
| Unit (parity) | `tests/tracing/test_content_capture_env.py::test_content_level_parity` | the frozen resolution of environment level x configured level x trust tier, cap included |
| Unit (parity) | `…::test_export_untrusted_parity` | the frozen untrusted-content flag behaviour: the environment flag beats the argument, `"false"` still caps |
| Unit (error) | `…::test_malformed_content_level_fails_closed`, `…::test_malformed_export_flag_fails_closed` | a malformed level or flag raises a configuration error naming the variable and never the value |

## 5 — Action tracing inputs

| Layer | Test file | Asserts |
| --- | --- | --- |
| Functional (error) | `tests/tracing/exporters/test_action_inputs.py::test_malformed_input_tracing_fails_closed`, `…::test_malformed_input_export_untrusted_fails_closed` | a malformed enable flag or untrusted-content export raises a configuration error naming the input and not the value |
| Functional (guard) | `…::test_unknown_input_tracing_to_still_raises` | an unknown tracing target still raises, as today |
| Functional (guard) | `…::test_valid_input_tracing_still_maps_to_enabled` | well-formed inputs keep mapping to the resolved sinks |

## 6 — the Action startup fails closed

| Layer | Test file | Asserts |
| --- | --- | --- |
| Functional / E2E | `tests/action/test_env_fail_closed_startup.py::test_malformed_tracing_env_fails_closed_before_the_agent` | driving the real orchestrator through the instrumented harness: a malformed control value lands the run in `configuration_error`, no agent is spawned, the MCP server never starts, the variable is named and the value is absent from all output |
| Functional (guard) | `…::test_valid_tracing_env_does_not_abort_the_run` | a well-formed value still reaches the agent |

---

## Frozen parity tables (provenance)

Every table above is a literal produced by running the **current** code over
its input grid before any implementation moved, so the table — not the old
function — is the oracle once the old parser is deleted. The grids were
produced with a throwaway script run against the development virtual
environment:

- the `.env` corpus and the writer round-trips: `dotenv.main.DotEnv(...,
  interpolate=True, override=False).dict()`, which is exactly what
  `load_dotenv(override=False)` exports;
- the tracing env layer and merged dicts: `_resolve_env_layer` and
  `resolve_tracing_settings` over an explicit, sentinel-prefixed mapping;
- the `enabled` matrix: `resolve_tracing_settings` over the config x env x CLI
  grid;
- the content-capture grids: `resolve_content_capture` over level x tier and
  flag x argument.

The throwaway script is not committed.

## Reconciliation after the green waves

Two **pre-existing** regression pins still asserted the pre-49 tracing env
behaviour and were amended in the reconciliation pass (the 49a contract wins;
`tests/` is owned solely by `test-creator`):

- `tests/tracing/test_content_policy.py::test_invalid_level_falls_back_to_default_not_full`
  — the YAML half is unchanged (an unknown configured level still falls through
  to the `redacted` default, never `full`); the env half now expects
  `EnvSettingsError` for a non-empty unknown `MERGECRAFT_TRACING_CONTENT`, which
  is section 4's fail-closed contract.
- `tests/config/test_tracing_tri_state.py::test_cli_precedence_layer_is_already_tri_state`
  — re-authored against `TracingEnv.from_env(...)`; the CLI-precedence
  `_parse_bool` helper it pinned was deleted in 49a. The tri-state intent is
  unchanged (unset is distinguishable from `false`) and an unknown non-empty
  value now fails closed.

## Out of scope

The run budgets, the config-file locator, the repository-settings-not-env
check, the control switches, the full `INPUT_*` model, the agents timeout and
the environment-read inventory belong to the second pull request and are not
authored here.
