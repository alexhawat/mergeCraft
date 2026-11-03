# Test plan — one reader for env and `.env` settings

**Red wave:** the `test-creator` wave of the pydantic-settings plan. It ran
twice: once for the release-carrying pull request (`3a0482c5`) and once for the
parity pull request that follows it.
**Green waves:** the foundation + one `.env` reader, then the tracing family,
its environment layer and its Action inputs; then the parity migration of the
remaining read sites, the control-switch model and the environment-read
inventory.

The document has two halves. *The release half* (sections 1–6) is the typed
environment foundation, the single `.env` reader, the provider-side `.env`
read, and the tracing environment plus its Action inputs. *The parity half*
(sections 7–13) is the migration of every remaining read site, the frozen
run-budget and locator tables, the control switches, the full Action-input
model and the inventory that makes "all" durable. Each half had its own RED
wave and its own green waves.

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
| Functional / E2E (real prompt reader) | `…::test_malformed_tracing_input_fails_closed_with_the_real_prompt_reader` | driving `main()` with the **production** `resolve_prompt_input` (the harness does not script it): an invalid `INPUT_TRACING` still lands in `configuration_error`, no agent is spawned, the input is named and the value is absent — even though prompt resolution constructs `ActionInputEnv` first |
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

## Test-isolation fix (verifier pass)

The wave verifier found that the `.env` corpus tests leaked keys into the
process environment. `_load_local_env` populates `os.environ` with
`os.environ.setdefault`, which bypasses `monkeypatch`; a key that was *absent*
when `monkeypatch.delenv(key, raising=False)` ran was therefore never recorded
for teardown, and the written value outlived the test. `pytest-randomly` varies
the order, so
`tests/cli/test_provider_env_map.py::test_read_env_map_matches_the_startup_load_on_the_corpus`
could interpolate `F=${A}z` from whatever a previous loader test had left in
`os.environ` and fail intermittently (`F: 'from-explicitz'`).

- `tests/cli/test_local_env_loader.py` — a new autouse
  `_restore_keys_written_by_the_loader` fixture snapshots the keys the loader can
  write (`A`–`H` and the credential) per test and restores them afterwards:
  absent-before keys are deleted, present-before keys are put back.
- `tests/cli/test_local_env_path.py` — the same fixture, for the same class of
  straight-`os.environ` write at the three loader sites in that module.
- `tests/cli/test_provider_env_map.py::test_read_env_map_matches_the_startup_load_on_the_corpus`
  — clears `A`–`H` for the duration of the read so the frozen literal holds
  whatever ran before. `_CORPUS_EXPECTED` is unchanged: the literal is the
  oracle, the isolation is what moved.

Both serial orders of the loader and provider modules pass, and the three-module
selection passes under `pytest-randomly`.

## Regression pins for the fail-closed startup paths

Two guards were added after the release-half implementation landed, because the
contract named the tracing **Action inputs** explicitly and one classification
and one exit path had no committed test that failed without the fix.

- `tests/action/test_env_fail_closed_startup.py` — the malformed-tracing
  parametrisation now also carries the two control-carrying Action inputs,
  `INPUT_TRACING` and `INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT`, alongside the
  four `MERGECRAFT_*` keys. The four assertions are unchanged — outcome
  `configuration_error`, no agent spawned, the MCP server never started, the key
  named and the canary absent from every output field. Before the orchestrator
  moved the Action-input export inside its configuration `try`, an unparseable
  `INPUT_TRACING` escaped the setup phase and landed the run in `infra_error`.
  Non-vacuity: raising the same configuration error from the setup phase (the
  pre-fix ordering) drives the real orchestrator to `infra_error`, so the
  `configuration_error` assertion is the discriminator.
- `tests/cli/test_cli_configuration_error_exit.py` — drives the real entrypoint
  `mergecraft.cli.app.main()` (not `CliRunner`, which enters Click's
  `Command.main()` and never calls `main()`) with a malformed
  `MERGECRAFT_TRACING` / `MERGECRAFT_TRACING_REGION`. It asserts `SystemExit`
  with `CLI_CONFIGURATION_EXIT_CODE`, the variable named and the canary absent
  from stdout and stderr; a guard case asserts a well-formed value keeps the
  ordinary success exit. Before the fix, `main()` called `app()` directly, so
  the error escaped as a Rich traceback and process exit code 1. The module also
  documents why the `INPUT_*` keys are not reachable through this subcommand —
  `mergecraft config tracing` resolves the `MERGECRAFT_*` env layer through
  `TracingEnv`, which has no `INPUT_*` alias; those keys are pinned on the
  Action startup path instead.

Both modules are hermetic (no workspace `.env`, no ambient `MERGECRAFT_*` /
`GITHUB_*` / `INPUT_*`, no network) and rebind the process-global loguru sink
after each test so a captured stream is never written to once it closes.

## 7 — run budgets: a frozen table and one typed read

The resolver keeps its merge arithmetic: the model parses, the resolver decides
what "unset" means. The table is the oracle once the two hand parsers are gone.

| Layer | Test file | Asserts |
| --- | --- | --- |
| Unit (parity) | `tests/utils/test_run_bounds_env_parity.py::test_resolve_run_bounds_keeps_the_frozen_table` | the eight knobs × {unset, empty, whitespace-only, `0`, valid} resolve to the frozen `RunBounds` field values |
| Unit (parity, quirk) | `…::test_integer_zero_and_float_zero_keep_their_own_rules` | `MERGECRAFT_TOKEN_BUDGET=0` falls through to the configured budget; `MERGECRAFT_COST_BUDGET_USD=0` is honoured |
| Unit (error) | `…::test_malformed_run_budget_still_raises_value_error` | every knob, malformed: `ValueError` (a `ValidationError` is one), with the variable named |
| Unit (happy) | `…::test_a_configured_value_still_wins_when_the_knob_is_absent` | an absent knob still takes the configured value |
| Unit (model) | `…::test_run_bounds_env_model_parses_every_knob`, `…::test_run_bounds_env_model_raises_on_a_malformed_value`, `…::test_run_bounds_env_declares_no_other_environment_name` | the model owns the eight exact names, numeric fields, `None` for absent/empty/whitespace, `ValidationError` for malformed |
| Unit (seam) | `…::test_run_bounds_env_model_reads_nothing_from_the_process_environment` | a mapping-only read never falls back to `os.environ` |
| Unit (registry) | `…::test_run_bounds_env_is_registered` | the startup pass validates the model |

## 8 — the config-file locator

| Layer | Test file | Asserts |
| --- | --- | --- |
| Integration (parity) | `tests/config/test_layered_config.py::test_resolve_config_sources_empty_env_config_is_absent`, `…::test_resolve_config_sources_blank_env_config_is_flagged_missing`, `…::test_load_layered_config_dict_empty_env_config_falls_through` | an empty `MERGECRAFT_CONFIG` is unset; a whitespace-only value stays "present but missing"; the layered loader follows the same rule |
| Unit (model) | `…::test_config_locator_env_declares_the_exact_name`, `…::test_config_locator_env_keeps_the_empty_value_rule`, `…::test_config_locator_env_reads_nothing_from_the_process_environment` | one exact alias, the same empty/whitespace rule as the resolver, and a mapping-only read |

The present, missing and short-circuit rows already existed and stay green
(`test_resolve_config_sources_env_file_is_the_only_contributor`,
`…flags_missing_env_file`, `…lists_committed_and_local`, `…omits_local_on_ci`,
`…empty_repo`).

## 9 — the repo YAML is not an env model

| Layer | Test file | Asserts |
| --- | --- | --- |
| Unit (guard) | `tests/config/test_repo_settings_not_env.py::test_repo_settings_is_not_a_base_settings`, `…::test_no_repo_config_model_reads_the_environment` | no repo-config model is a `BaseSettings` |
| Unit (parity) | `…::test_a_repo_field_name_in_the_environment_changes_nothing` | `SHELL`, `PUSH`, `MODEL`, `STATUS_CHECKS`, `TOKENBUDGET`, `MAXDIFFLINES` and `RUNBOUNDS` in the environment leave `load_repo_settings` equal to the defaults |
| Unit (edge) | `…::test_the_login_shell_does_not_fail_shell_permission` | `SHELL=/bin/zsh` does not become the repo's shell policy |
| Integration (happy) | `…::test_a_repo_file_still_decides_the_repo_fields` | the committed YAML still wins over the same poison |
| Unit (guard) | `…::test_repo_settings_forbid_unknown_keys` | the repo YAML keeps `extra="forbid"` |
| Integration | `…::test_the_config_locator_still_reads_mergecraft_config_explicitly` | the locator is an explicit read, not a field-name override |

## 10 — control switches: exact `"1"`, never a knob

| Layer | Test file | Asserts |
| --- | --- | --- |
| Unit (parity) | `tests/security/test_control_switch_exact.py::test_control_switch_is_enabled_only_by_exactly_one` | for each switch (`unsandboxed-shell`, `allow-root`, `filtered-egress-opt-in`): `"1"` enables; `true`/`TRUE`/`yes`/`on`/`t`/`01`/`""`/absent do not |
| Unit (model) | `tests/config/test_env_reads_inventory.py::test_control_switch_fields_are_exact_flags_and_never_listed` | the three fields are not `bool`, carry the `control_switch` marker, and enable exactly `raw == "1"` including the whitespace variants the readers leave to the model; no switch is a repo-settings field and no settings dump carries one |
| Unit (guard) | `tests/security/test_control_switch_exact.py::test_no_switch_is_a_repo_setting` | `config show` cannot render a switch: it prints repo settings |
| Unit (guard) | `…::test_the_removed_security_instructions_switch_has_no_reader` | the deleted security-instructions switch keeps no reader |

The `"1 "` / `" 1"` edge is not asserted on the readers: the locked type
decision owns that comparison (`ExactFlag.enabled == (raw == "1")`), so it is
pinned once, on the model, rather than re-stated per reader.

## 11 — the agent runtime

| Layer | Test file | Asserts |
| --- | --- | --- |
| Unit (happy) | `tests/agents/test_agent_timeout_env.py::test_agent_timeout_defaults_to_3600_and_honours_a_valid_value` | unset reads `3600`; `3600`, `120`, `1` are honoured |
| Unit (shape) | `…::test_agent_timeout_field_is_a_float` | the field accepts fractional seconds (`float`) and keeps the `3600` default |
| Unit (parity) | `…::test_agent_timeout_accepts_fractional_seconds` | `1.5`, `3600.0` and `0.5` resolve to floats: `agents/cursor.py` and `security/broker.py` parsed with `float(...)` before the migration, and one model must not narrow what those paths accepted |
| Unit (error) | `…::test_agent_timeout_rejects_a_malformed_value`, `…::test_agent_timeout_rejects_an_empty_value_like_today` | `soon`, `10m`, `true` raise `ValueError` naming the variable; `""` and `"   "` raise too, as the old bare `int("")` / `float("")` did |
| Unit (parity audit) | `…::test_numeric_knobs_do_not_turn_an_empty_value_into_a_default` | every numeric run-budget/timeout knob keeps today's empty rule: only the agent timeout raised; the eight `RunBoundsEnv` fields and the MCP port read as absent and `MERGECRAFT_*=` resolves exactly like unset |
| Unit (edge) | `…::test_agent_timeout_reads_nothing_from_the_process_environment`, `…::test_agent_runtime_env_is_constructed_per_read` | the mapping is the only input; no cached instance |
| Unit (shape) | `…::test_agent_runtime_env_declares_the_runtime_knobs` | the timeout, the Codex home parent, the model and the agent are exact aliases |

The per-driver "no direct read remains" half of this contract is enforced by
the inventory (section 13): the five drivers and the credential broker must stop
reading the name themselves.

## 12 — the Action inputs

| Layer | Test file | Asserts |
| --- | --- | --- |
| Unit (shape) | `tests/utils/test_payload.py::test_action_input_model_declares_every_action_input` | every `INPUT_*` `action.yml` maps (24, tracing included) is a field with its exact name |
| Unit (guard) | `…::test_action_input_model_does_not_carry_the_github_token` | `INPUT_TOKEN` is not a model field |
| Unit (edge) | `…::test_an_empty_action_input_reads_as_unset` | the runtime's empty string reads as `None`, for every input |
| Unit (seam) | `…::test_action_input_model_reads_nothing_from_the_process_environment` | a mapping-only read |
| Functional (parity) | `…::test_get_action_input_keeps_its_frozen_behaviour`, `…::test_get_action_input_maps_hyphens_to_underscores` | unset → `""`, values are stripped, `tracing-to` → `INPUT_TRACING_TO` |
| Functional (parity) | `…::test_resolve_payload_lowercases_the_permission_inputs` | push/shell/status-checks/model-pin keep today's lower-casing on the public payload |
| Functional (parity) | `…::test_custom_provider_inputs_still_export_the_singleton_pair` | `provider_base_url` + `provider_api_key_env` still export the two env vars |

## 13 — the inventory: "all" is a test, not a promise

`tests/config/test_env_reads_inventory.py` is the durable evidence. It
AST-scans `src/mergecraft/` for environment reads and classifies them.

| Layer | Test | Asserts |
| --- | --- | --- |
| Static (per name) | `test_in_scope_name_is_declared_by_its_model` | each in-scope name is an exact alias of exactly one process-env model (`LocalDotEnv` is the `.env` file view and is exempt from the count) |
| Static (per name) | `test_in_scope_name_is_read_only_through_a_model` | no in-scope read survives outside `config/env/` unless it is allowlisted with a class and a reason |
| Static (registry) | `test_plan_named_models_are_registered` | the models the plan registers reach the startup pass |
| Static (secrets) | `test_secret_names_are_secretstr_and_never_leak` | each secret name is a `SecretStr` and no `repr`/`model_dump`/`model_dump_json` renders it |
| Static (switches) | `test_control_switch_fields_are_exact_flags_and_never_listed` | section 10's model pins |
| Static (coverage) | `test_every_out_of_scope_read_is_allowlisted` | every read of a name outside the in-scope set matches a `(path, name, class, reason)` row |
| Static (allowlist) | `test_allowlist_rows_carry_a_known_class_and_a_reason` | the allowlist is self-describing |

The scan recognises the read shapes the codebase uses: a literal (or a
module-level constant, including one imported from another module) passed to
`os.environ.get` / `os.getenv` / `environ.get`, an `os.environ[...]` load, a
`key in os.environ` membership test, a literal passed to one of the module-local
env helpers, and a candidate-name tuple — inline, a module-level constant, or a
function-local constant — that a `for` loop or a comprehension/generator reads
through the environment. The filters count as part of a comprehension body, so
`[v for v in VARS if v in os.environ]` and `any(os.environ.get(n) for n in (...))`
are both candidate reads. The non-obvious shapes have scratch-tree self-tests:
`test_scan_reports_getenv_in_a_scratch_tree` for `os.getenv` / bare `getenv`
(the real tree reads through `os.environ.get` only) and
`test_scan_reports_candidate_reads_in_a_scratch_tree` for the five loop and
comprehension spellings. Writes
are not reads: a subscript store, `pop`, `setdefault` and an exporter's dict key
are the writer's own business. A constant that is no longer referenced anywhere
in its module is dead, not a read, so it is not flagged.

**Allowlist policy.** A stale row (a read that has moved into `config/env/`) is
tolerated; an *unlisted* read is a failure. That is the only rule compatible
with a single-writer test tree: an implementation wave adds the read to a model,
never to this allowlist. The test owner prunes the stale rows.

A `descriptor` row may cover only a module-level constant that *labels* a
variable for a message or a provider descriptor. It is never a home for a live
`os.environ` read: the leaf package owns that read. Because the scan records a
referenced env-name constant as a read surrogate (a dynamic read is represented
by the constant that names it), a module keeping a name only to print must
import it from `config/env/` — the leaf is out of scan scope, as
`OTEL_PLUGIN_ENV` already demonstrates — rather than re-declare it locally.

**What the post-50 tree surfaced.** The definitive inventory at the parity
wave's base (`d103e90c`) is **370 read lines in 115 files** for the plan's
`git grep` command. The AST scan classifies **108 distinct `(path, name)`
reads** — 85 of them in scope, 23 allowlisted out of scope. Beyond the plan's
wave lists it surfaced four reads the release half left behind and one knob no
wave had named:

- `TYPESAFE_API_KEY` read directly in `cli/jev_cmd.py` (two places),
  `cli/opencode_cmd.py` and `jev/client.py`;
- `LOG_LEVEL` read directly in `utils/instructions.py`;
- `MERGECRAFT_STICKY_ONLY_NEUTRAL`, `MERGECRAFT_CAPTURE_VERDICTS`,
  `MERGECRAFT_REVIEWER_BOT_LOGIN` and `MERGECRAFT_OPENCODE_OTEL_PLUGIN`, which
  PS-D2's classification rule makes operator knobs;
- `MERGECRAFT_INSTALL_REF` and the Harbor harness reads, allowlisted as
  generated benchmark inputs;
- `cli/provider_cmd.py`'s legacy migration, allowlisted as a writer: its
  `env_map` is the parsed `.env` file, not the process environment.

## The parity half — scenario matrix

Every contract above has a happy path, an edge case (empty / boundary / `0` /
whitespace / overlap) and an error case that pins the failure type and the
message contract (the variable named, the value never used as an oracle).

## Frozen parity tables (parity half)

Produced by running the pre-migration code before any reader moved, so the table
— not the deleted helper — is the oracle:

- the run-budget grid: `resolve_run_bounds(env=…)` over `default_settings()`,
  every knob × {unset, `""`, `"   "`, `"0"`, a valid value, `"soon"`};
- the control-switch table: `mcp.shell._allow_unsandboxed_shell`,
  `utils.privilege._allow_root_override`, and the kernel-probe opt-in observed
  through `analyzers.egress._can_unshare_net`;
- the locator grid: `resolve_config_sources` and
  `load_layered_config_dict` over an unset / empty / whitespace / present /
  missing `MERGECRAFT_CONFIG`;
- the repo-settings grid: `load_repo_settings` with the repo field names
  present in the environment;
- the Action-input parity: `get_action_input`, `resolve_payload`'s
  lower-casing and `resolve_custom_provider_env_inputs`.

The throwaway scripts that produced them are not committed.

## Verification

```text
uv run --extra dev pytest tests/config/test_env_reads_inventory.py \
    tests/config/test_repo_settings_not_env.py tests/config/test_layered_config.py \
    tests/utils/test_run_bounds_env_parity.py tests/utils/test_payload.py \
    tests/agents/test_agent_timeout_env.py tests/security/test_control_switch_exact.py -q -n8
```

At the RED wave: **449 collected**, 217 failing pending implementation, 232
parity/guard passing; `make lint` and `make typecheck` clean.

## Gate reconciliation (test-owner pass)

**Closed by the product pass.** The four product findings were migrated at
`60d45a88`; the full gate re-ran green at that head (461 plan-selection tests,
inventory 186 passed with 0 unlisted reads, 10,378 in the wider selection).

The 49b verifier gate returned `changes_required`, with three test-owned findings
and three product findings. The test-owned findings are fixed here; the product
findings were deliberately left red for that pass.

**Test-owned fixes.**

1. *Stale oracle.* `tests/cli/test_profile_env_exports.py` derived `_READ_ENV`
   by regexing `src/mergecraft/utils/run_bounds.py`, which now contains no
   `MERGECRAFT_*` names because the parser moved into `RunBoundsEnv`. The
   accepted set is now the model's declared aliases, with a `_BUDGET_VARS`
   guard so a model that lost a knob cannot make the subset check vacuous.
   `test_profile_env_overrides_emits_no_unread_variable[fast|deep|security]`
   is green again.
2. *Scan gap.* The inventory accepted a getter only when its receiver was a
   mapping (`os.environ.get`, `env_map.get`), so `os.getenv("MERGECRAFT_MCP_PORT")`
   was invisible. `_is_getenv_reference` now recognises `os.getenv` and a bare
   `getenv` imported from `os`; the candidate-name loop uses the same predicate.
   `test_scan_reports_getenv_in_a_scratch_tree` plants `os.getenv` / bare
   `getenv` / `os.environ.get` / membership in a `tmp_path` tree and asserts all
   four are reported. `_scan_file(..., root=...)` and `_scan_source` exist so a
   tree outside the repo can be scanned. The real tree has no `os.getenv`
   calls, so the classification is unchanged.
3. *Empty-value parity.* `MERGECRAFT_AGENT_TIMEOUT=""` raised `ValueError` from
   `int("")` before the migration; `env_ignore_empty=True` turned it into
   `3600`. `test_agent_timeout_rejects_an_empty_value_like_today` pins the raise
   for `""` and `"   "`, and
   `test_numeric_knobs_do_not_turn_an_empty_value_into_a_default` audits the
   whole numeric run-budget/timeout family: the eight `RunBoundsEnv` fields and
   the MCP port read as absent for `""` (and the run-budget knobs resolve
   exactly like unset); only the agent timeout raised.

**Product findings left red** — the exemptions that hid the live reads are
removed, so the inventory fails until the reads move:

| Read | Removed row | Node id |
| --- | --- | --- |
| `src/mergecraft/analyzers/sandbox.py:245` (fail-closed sandbox gate) | `MERGECRAFT_ALLOW_UNSANDBOXED_SHELL`, class `descriptor` | `test_in_scope_name_is_read_only_through_a_model[MERGECRAFT_ALLOW_UNSANDBOXED_SHELL-PS7]` |
| `src/mergecraft/agents/openai_compatible_gateways.py:255-256` (singleton gateway pair) | `MERGECRAFT_CUSTOM_PROVIDER_BASE_URL` and `MERGECRAFT_CUSTOM_PROVIDER_API_KEY`, class `descriptor` | `…[MERGECRAFT_CUSTOM_PROVIDER_BASE_URL-PS6]`, `…[MERGECRAFT_CUSTOM_PROVIDER_API_KEY-PS6]` |
| `src/mergecraft/jev/client.py:228` (Jev credential) | `TYPESAFE_API_KEY`, class `writer` | `…[TYPESAFE_API_KEY-PS2]` |

The `writer` row was mislabelled: `jev/client.py` returns the value, it does not
write it. The gateway rows claimed "the value read moves" while the read was
still there.

**Executor note.** The scan reports a referenced module-level constant whose
value is an environment name (`kind="constant"`). After the value read moves,
`sandbox.py` and the gateway module still reference their constants as labels,
so the constant site keeps failing unless the name is imported from
`mergecraft.config.env` (out of scan scope — the `OTEL_PLUGIN_ENV` precedent) or
the test owner re-adds a descriptor row during reconciliation.
`TYPESAFE_API_KEY_ENV` becomes unreferenced once the read moves, and a dead
constant is not a read site.

Rows that stay are message-only descriptors whose value read is already on a
model (codex sandbox, the extra-options labels, audit root, evidence dir,
verdict capture, linked repos, allow-root); their reasons now say so.

## Second self-review pass (PR #1127)

**Closed by the product pass.** All three findings were fixed at `4e0183ef`
(timeout is a float again, the tracing diagnostics read `TracingEnv`, and a
malformed `INPUT_TRACING` through the real `main()` path is
`configuration_error`); the gate re-ran green at that head (477 plan-selection
tests, 191 inventory with 0 unlisted reads).

The PR self-review returned three more findings, one of them a suite gap. All
three were pinned here as RED; the product findings were left red for the
executor's pass.

1. **Agent-timeout type.** `AgentRuntimeEnv.agent_timeout` is `int`, but
   `agents/cursor.py` and `security/broker.py` parsed with `float(...)` before
   the migration, so `MERGECRAFT_AGENT_TIMEOUT=1.5` and `3600.0` were valid on
   those paths. `test_agent_timeout_field_is_a_float` and
   `test_agent_timeout_accepts_fractional_seconds` require the field to be a
   `float` with the same `3600` default; `1.5` moved out of the malformed table.
   The empty-value rule is unchanged (raise, naming the variable).
2. **Scan gap.** `_scan_tree` handled only `ast.For` over an inline tuple, so
   named constants, function-local constants and comprehension/generator bodies
   were invisible. The scan now resolves `UPPER = (...)` / `[...]` constants at
   module or function scope (an ambiguous redefinition stays unresolved) and
   covers `ListComp` / `SetComp` / `GeneratorExp` / `DictComp`, with the filters
   treated as part of the body. Five scratch-tree self-tests pin the shapes:
   module tuple, local tuple, membership filter, getter filter, inline-tuple
   generator. Newly surfaced reads:
   - `src/mergecraft/cli/tracing_cmd.py:194,350` — the seven `MERGECRAFT_TRACING*`
     / `MERGECRAFT_TRACE_DIR` names are in scope and now RED (no row).
   - `src/mergecraft/cli/opencode_cmd.py:273` — `MERGECRAFT_LOGFIRE_TOKEN` is in
     scope and now RED.
   - `src/mergecraft/cli/doctor_cmd.py:112,334` — the secret-name iteration is
     the documented dynamic probe, so it carries a `dynamic` row and stays green.
   - `src/mergecraft/cli/tracing_logfire_wf_yaml.py:884` — the Logfire workflow
     writer checks its own YAML `env:` mapping, not the process environment, so
     it carries a `generated` row and stays green.
3. **Prompt resolution before the guard.** `resolve_prompt_input` constructs the
   full `ActionInputEnv`, and `_setup_run` calls it before the guarded tracing
   block, so an invalid `INPUT_TRACING` was classified `infra_error`.
   `test_malformed_tracing_input_fails_closed_with_the_real_prompt_reader` drives
   `main()` with the production resolver (`run_main_for_test(...,
   real_prompt_input=True)`, with `INPUT_PROMPT` in the environment) and requires
   `configuration_error`, no agent, the input named and the value absent.

## Out of scope

The `.env` corpus and the tracing precedence pins are unchanged by the parity
half — it adds no `.env` reader. `tests/cli/test_local_env_loader.py`,
`tests/cli/test_local_env_path.py`, `tests/cli/test_provider_env_map.py`,
`tests/tracing/test_env_layer_parity.py` and
`tests/tracing/exporters/test_cli_precedence.py` stay as the release half left
them and must keep passing.

The GitHub token chain, platform context, the internal message bus, provider-native
credentials, subprocess env forwarding and OS-standard variables stay out of the
models; the inventory's allowlist keeps each of them, with its class.
