# Test plan — Settings that silently mean something else (config & CLI surfaces)

**Plan:** `.ignorelocal/waves/45-config-cli-surfaces-wave-plan.md`
**Red wave:** CF1 (`test-creator`)
**Trace:** service `mergecraft-dev` · wave.plan=`config-cli-surfaces` · run.id=`de7f4c71-c0f2-43b5-87c6-dd6a4e7d7240` · wave.id=`CF1`
**Green waves:** CF2 (C1, C6, C12, C18, N16) · CF3 (D9, N15) · CF4 (C9, C10, D15, N4, N6) · CF5 (D8)

This is the RED suite for CF2–CF5, authored before any implementation. The suite
**collects** with no import/collection errors and `make lint` + `make typecheck`
are clean; the assertions below fail on the current trunk and pass once the
named green wave lands.

**Marker policy.** No `xfail` markers are used. Every not-yet-implemented
assertion is a plain failure, so the session does not risk an `XPASS` under the
repo's xpass ratchet. Targets whose symbol does not exist yet are imported
**inside the test body** (or asserted absent), never at module import time, so
collection stays clean.

**Scenario matrix.** Every contract below has a happy-path test, edge cases
(empty / boundary / unicode-or-case / repeated / ordering), and an error case
that asserts the failure type and the message contract (naming the offending
key/tier), not merely "it raises".

---

## C1 — an invalid `trust.agentSandbox` fails validation

| Layer | Test | Asserts |
| --- | --- | --- |
| Unit | `tests/config/test_trust_agent_sandbox_settings.py::test_invalid_agent_sandbox_fails_validation` | `off`, `false` (YAML bool), `True`, `nevr`, `""`, `1` (str/int), `None`, `same_repo` each raise `ValidationError`, and the error names all four tiers |
| Unit (happy) | `…::test_trust_settings_accepts_agent_sandbox`, `…::test_valid_agent_sandbox_still_normalizes` | the four tiers still accept, with strip/lower (`" Never "` → `never`) |
| Integration | `…::test_load_repo_settings_rejects_invalid_agent_sandbox` | a committed `agentSandbox: off` aborts loading with the tier-naming error |
| Unit | `tests/security/test_trust_fallthrough.py::test_read_agent_sandbox_level_refuses_unknown_value` | the duck-typed snapshot read raises `ValueError` naming the field + tiers, never returns `dispatch` |
| Unit (happy) | `…::test_read_agent_sandbox_level_returns_valid_tier`, `…::test_read_agent_sandbox_level_defaults_when_trust_absent` | valid tiers pass through; a missing `trust` block keeps `dispatch` |

## C6 — `model_pin` is tri-state

| Layer | Test | Asserts |
| --- | --- | --- |
| Unit | `tests/utils/test_payload.py::test_model_pin_is_tri_state` | `disabled` beats repo `true`; `enabled` beats repo `false`; unset defers to repo — for **both** `modelPin` and `modelExplicit` |
| Unit | `…::test_json_payload_model_pin_beats_repo_when_input_unset`, `…::test_explicit_input_disabled_beats_json_payload_pin` | payload sits between input and repo; the OR is gone |
| Contract | `tests/action/test_action_yml_contract.py::TestActionYmlHygiene::test_model_pin_declares_no_default` | `action.yml` `model_pin` has no `default:` key |

## C12 — reserved settings warn when set

| Layer | Test | Asserts |
| --- | --- | --- |
| Integration | `tests/config/test_reserved_settings.py::test_reserved_key_warns_exactly_once_naming_the_key` | `gates.thermostat`, `tracing.redaction`, `stopScript`, `blastRadiusOverride`, `operatorPipeline` each log exactly one warning naming the key |
| Integration (happy) | `…::test_reserved_defaults_log_nothing` | a config leaving every reserved key at its default is silent |
| Integration | `…::test_auto_merge_enabled_warns_only_when_true` | `false` silent, `true` warns once |
| Integration (guard) | `…::test_model_index_and_providers_seeded_never_warn` | `modelIndex` / `providersSeeded` keep their readers and never warn |

## C18 — `_warn_unknown_config_keys` is deleted, not rewired

| Layer | Test | Asserts |
| --- | --- | --- |
| Unit | `tests/config/test_extra_forbid.py::test_warn_unknown_config_keys_is_deleted` | the symbol is gone from `mergecraft.config.settings` |

The helper-only test (`test_warn_unknown_config_keys_logs_for_optional_models`)
was removed with the function; the forbidden-key behaviour tests are unchanged.

## N16 — comment-preserving writes replace in place

| Layer | Test | Asserts |
| --- | --- | --- |
| Unit | `tests/config/test_config_io_comments.py::test_patch_config_dict_replaces_commented_block_in_place` | one write leaves exactly one top-level `agents:`; other blocks intact |
| Unit (edge) | `…::test_patch_config_dict_twice_leaves_one_agents_key` | repeated writes never accumulate a second copy |
| Unit (edge) | `…::test_patch_config_dict_appends_only_when_key_absent` | an absent key appends once; a repeat replaces |
| Unit | `…::test_patch_config_dict_preserves_comments_outside_replaced_block` | comments outside the replaced block survive |
| Functional | `tests/cli/test_config_surface.py::test_config_set_on_commented_config_does_not_duplicate_key` | `config set model` on a commented file leaves one `models:` key and the comment |
| Functional (guard) | `tests/cli/test_jev_cmd.py` (whole file, unchanged) | the Jev write paths stay green through the shared helper |

## D9 — one resolved config view

| Layer | Test | Asserts |
| --- | --- | --- |
| Unit | `tests/config/test_layered_config.py::test_resolve_config_sources_lists_committed_and_local` | committed + local overlay, lowest precedence first, absolute paths |
| Unit (edge) | `…::test_resolve_config_sources_omits_local_on_ci` | `GITHUB_ACTIONS=true` drops the overlay |
| Unit (edge) | `…::test_resolve_config_sources_env_file_is_the_only_contributor` | a present `MERGECRAFT_CONFIG` short-circuits the rest |
| Unit (error) | `…::test_resolve_config_sources_flags_missing_env_file` | a missing env file sets the flag and keeps the committed contributors |
| Unit (edge) | `…::test_resolve_config_sources_empty_repo` | nothing contributes → empty tuple, flag false |
| Integration | `tests/cli/test_config_view_parity.py::test_doctor_config_row_lists_local_overlay` + `…_agrees_with_resolve_config_sources` | doctor's config row names the same contributing files |
| Integration | `…::test_config_explain_yaml_layer_includes_local_overlay` | `config explain`'s YAML layer reflects the local overlay |
| Integration (error) | `…::test_doctor_names_missing_mergecraft_config` | names `MERGECRAFT_CONFIG` + the missing path, never "defaults apply" |
| Integration (guard) | `…::test_load_repo_settings_includes_local_overlay` | the loader already merges the overlay (behavioral anchor) |

**Pinned API.** `mergecraft.config.layered.resolve_config_sources(root)` returns
an object with `.files: tuple[Path, ...]` in precedence order (lowest first) and
`.env_config_missing: bool`.

## N15 — the doctor secret tripwire is a hard failure

| Layer | Test | Asserts |
| --- | --- | --- |
| Functional | `tests/cli/test_doctor.py::test_doctor_fails_closed_when_rendered_output_would_leak_a_secret` | exit `CLI_CONFIGURATION_EXIT_CODE`, no table rendered, names `OPENAI_API_KEY`, never the value |
| Functional (guard) | `tests/cli/test_doctor.py::test_never_prints_a_credential_value` (unchanged) | the normal path still exits 0 without echoing secrets |

## C9 — version stamps and a health payload that says what it checks

| Layer | Test | Asserts |
| --- | --- | --- |
| Functional | `tests/cli/test_provider_status_cmd.py::test_provider_status_json_carries_both_schema_stamps` | `schema_version == "1.0.0"` **and** `schemaVersion == 1` |
| Unit (guard) | `tests/enterprise/test_health.py::test_health_payload_is_machine_readable`, `…::test_health_payload_names_each_check` | status `ok`, `python`/`telemetry` checks, resolved telemetry mode |
| Functional | `…::test_health_cli_output_carries_schema_version` | the CLI emits the shared schema-versioned envelope |
| Functional | `…::test_health_help_states_its_scope` | help says liveness + telemetry and "not a readiness probe" |

## C10 — Logfire wiring accepts the docs' lowercase reference

| Layer | Test | Asserts |
| --- | --- | --- |
| Unit (happy) | `tests/cli/test_tracing_logfire_wf_yaml.py::test_apply_logfire_wiring_accepts_lowercase_action_reference` | `alexhawat/mergecraft@<sha>` is wired with the four keys |
| Unit (error) | `…::test_apply_logfire_wiring_rejects_similar_fork_action_uses` | `alexhawat/mergeCraft-fork@…`, `alexhawat/mergecraftx@…` and `alexhawat/mergeCraft@` (empty ref) are all refused |

The mixed fixture was split so a regression in either the case-insensitivity or
the fork/empty-ref refusal fails on its own.

## D15 — GitHub Enterprise hosts

| Layer | Test | Asserts |
| --- | --- | --- |
| Unit | `tests/utils/test_github.py::test_default_server_url_falls_back_to_public_github`, `…_honours_github_server_url_env` | `GITHUB_SERVER_URL` drives the web host; default github.com (trailing slash stripped) |
| Integration | `tests/cli/test_watch_cmd.py::test_poll_timeline_uses_github_api_url` | the timeline request targets `GITHUB_API_URL` |
| Integration | `…::test_parse_git_remote_honours_github_server_url` (+ default guard) | the remote parser accepts a GHES host |
| Unit | `tests/mcp/test_comment_footer_host.py::test_footer_run_link_honours_github_server_url` (+ default guard) | the run link is built on the configured web host |

**Pinned API.** `mergecraft.utils.github._default_server_url()` beside
`_default_api_base_url()`.

## N4 — id-less timeline events emit once

| Layer | Test | Asserts |
| --- | --- | --- |
| Functional | `tests/cli/test_watch_cmd.py::test_run_emits_idless_event_once_across_polls` | two polls returning the same `committed` event emit exactly one JSONL line |
| Functional (guard) | `…::test_run_still_dedups_events_by_id` | an event carrying an `id` still dedups by id |

The loop is driven through two real polls (mocked transport, two poll cycles)
so the process-scoped fingerprint state is exercised end to end.

## N6 — one workflow-command escaper

| Layer | Test | Asserts |
| --- | --- | --- |
| Unit | `tests/utils/test_gha_log_escape.py::test_escape_workflow_command_escapes_percent_cr_and_lf` | `%`→`%25`, CR→`%0D`, LF→`%0A` |
| Unit | `…::test_escape_workflow_command_preserves_brackets_and_colons`, `…::test_escape_workflow_command_collapses_crlf_into_one_line` | brackets intact, CRLF collapses to one line |
| Unit (guard) | `…::test_error_annotation_routes_through_the_escaper` | the public `error()` emitter escapes |
| Unit | `tests/cli/test_gha_cmd.py::test_set_failed_writes_one_escaped_error_line_to_stdout` | exactly one escaped `::error::` line on **stdout**, brackets intact |

**Pinned API.** `mergecraft.utils.gha_log.escape_workflow_command(value)` is
public; `_set_failed` writes the escaped command line to stdout directly.

## D8 — SaaS residue removed

| Layer | Test | Asserts |
| --- | --- | --- |
| Unit | `tests/mcp/test_context_saas_residue.py::test_tool_context_has_no_plan_field`, `…::test_run_context_data_has_no_hosted_plan_or_proxy_model_fields` | no `plan` / `proxy_model` fields |
| Unit | `…::test_account_plan_literal_is_removed_everywhere` | no `AccountPlan` in `mcp/context.py`, `config`, `config/settings.py` |
| Unit | `…::test_payload_has_no_proxy_model_key` | the payload has no `proxyModel` producer |
| Unit (guard) | `…::test_run_context_data_still_carries_api_token`, `…::test_repo_info_is_unchanged` | `api_token` survives |
| Unit | `tests/test_models.py::test_card_and_openrouter_helpers_are_removed` | the card/OpenRouter helpers and import-time guard are gone |
| Functional (guard) | `tests/mcp/test_empty_upload_bearer_469.py`, `tests/mcp/test_upload.py` (unchanged) | the upload remote arm and local fallback stay green |

The card/OpenRouter helper imports and their tests were dropped from
`tests/test_models.py` (sanctioned by the plan); the `auto-tier` guard tests
that keep real callers (`is_auto_tier`, `resolve_cli_model`) remain.

---

## Sanctioned edits to existing green tests

| File | Change | Reason |
| --- | --- | --- |
| `tests/config/test_extra_forbid.py` | removed `test_warn_unknown_config_keys_logs_for_optional_models` and its imports | the helper is deleted with its test (C18); a new presence assertion replaces it |
| `tests/action/test_action_yml_contract.py` | dropped `model_pin` from the declared-defaults parametrization | its `default:` is removed (C6); a new no-default assertion replaces it |
| `tests/test_models.py` | dropped card/OpenRouter helper imports and tests | the helpers are removed (D8); a removal assertion replaces them |
| `tests/cli/test_tracing_logfire_wf_yaml.py` | split the fork-similar fixture; added the lowercase-wired case | the lowercase reference now wires (C10) |

No other existing test was weakened or deleted.

## Reconciliation after each green wave

CF2–CF5 land their behaviour; the orchestrator re-dispatches `test-creator`
after each wave only where a test needs amending (per the escalation path).
No xfail markers exist, so no marker removal is required — a green wave simply
turns the plain failures into passes.
