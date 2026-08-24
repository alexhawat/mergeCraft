# Open issues sweep 2026-08-24 lane B — BA #477 test plan

Maps **BA RED** contracts for #477 (`provider add/list/edit/delete`) to the test suite.
Source plan: `.ignorelocal/waves/open-issues-sweep-2026-08-24-b-provider-registry-wave-plan.md`.

## D2 — config/secret split → BA

| Contract | Tests | Layer |
| --- | --- | --- |
| Structure in `.mergecraft/config.yaml` (`providers:` list) | `tests/cli/test_provider_cmd.py::test_provider_add_writes_config_and_env_indexed_secret` | E2E |
| Secrets in `.env` via `envIndex` (`LLM_PROVIDER_<N>`) | `…::test_provider_add_writes_config_and_env_indexed_secret` | E2E |
| `provider list` surfaces registered labels | `…::test_provider_list_shows_registered_labels` | E2E |

## D3 — permanent indices → BA

| Contract | Tests | Layer |
| --- | --- | --- |
| `delete` leaves an index gap | `tests/cli/test_provider_cmd.py::test_provider_delete_leaves_index_gap_and_never_reuses` | E2E |
| New `add` allocates `max(existing) + 1` | `…::test_provider_add_allocates_max_plus_one_even_with_gaps`, `tests/cli/test_provider_registry.py::test_allocate_env_index_returns_max_plus_one` | E2E / unit |
| Freed indices are never reused | `…::test_provider_delete_leaves_index_gap_and_never_reuses`, `tests/cli/test_provider_registry.py::test_allocate_env_index_never_reuses_gaps` | E2E / unit |

## D4 — harness required, built-in defaults → BA

| Contract | Tests | Layer |
| --- | --- | --- |
| Custom provider without `--harness` fails and names supported values | `tests/cli/test_provider_cmd.py::test_provider_add_without_harness_fails_for_custom_provider[*]` | E2E / error |
| Unknown `--harness` fails | `…::test_provider_add_rejects_unknown_harness` | E2E / error |
| Built-in defaults: `openai→codex`, `anthropic→claude`, `google→gemini`, `cursor→cursor` | `…::test_builtin_provider_add_resolves_harness_without_flag[*]`, `tests/cli/test_provider_registry.py::test_builtin_harness_defaults_match_agent_resolve_table[*]` | E2E / unit |
| Incompatible (harness, provider) pair rejected via `_harness_supports_provider` | `tests/cli/test_provider_cmd.py::test_provider_add_rejects_incompatible_harness_provider_pair`, `tests/cli/test_provider_registry.py::test_harness_support_predicate_is_reused_not_duplicated` | E2E / unit |
| `provider harnesses` lists harnesses from code | `tests/cli/test_provider_cmd.py::test_provider_harnesses_lists_supported_values_from_code`, `tests/cli/test_provider_registry.py::test_list_supported_harnesses_is_generated_from_code` | E2E / unit |
| Unknown provider must not silently default to `opencode` | `tests/cli/test_provider_cmd.py::test_unknown_registry_provider_does_not_default_to_opencode` | unit / error |

## CLI verbs → BA

| Contract | Tests | Layer |
| --- | --- | --- |
| `provider add/list/edit/delete/harnesses` registered | `tests/cli/test_provider_cmd.py::test_provider_help_lists_registry_verbs` | functional |
| `provider edit` updates config | `…::test_provider_edit_updates_url_in_config` | E2E |
| `provider delete` removes label | `…::test_provider_delete_removes_label_from_config` | E2E |
| Duplicate label rejected | `…::test_provider_add_rejects_duplicate_label` | error |
| Unknown label on edit/delete exits non-zero | `…::test_provider_edit_unknown_label_exits_nonzero`, `…::test_provider_delete_unknown_label_exits_nonzero` | error |
| Absolute http(s) URL required | `…::test_provider_add_rejects_non_http_url[*]` | error |

## Seeding — `PROVIDERS` is seed data only → BA

| Contract | Tests | Layer |
| --- | --- | --- |
| Built-in catalog has 14 entries (seed source) | `tests/cli/test_provider_registry.py::test_providers_catalog_has_fourteen_builtin_entries` | unit (passes pre-impl) |
| Seeding imports all 14 built-ins with metadata | `tests/cli/test_provider_cmd.py::test_provider_seed_imports_all_builtin_catalog_entries` | integration |
| `PROVIDERS` not consulted at runtime after seeding | `…::test_provider_registry_does_not_read_providers_dict_at_runtime` | integration |
| Deleted built-in stays deleted (no reconcile) | `…::test_deleted_builtin_provider_is_not_reseeded_on_next_load` | functional |

## Pinned public API (implementation wave BA)

New module `src/mergecraft/cli/provider_cmd.py`:

- Typer subcommands: `add`, `list`, `edit`, `delete`, `harnesses`
- `list_supported_harnesses() -> Sequence[tuple[str, str] | HarnessInfo]`
- `seed_builtin_providers(config_path: Path) -> None`
- `load_provider_registry(config_path: Path) -> ProviderRegistry`
- `resolve_provider_harness(label: str, *, harness: str | None) -> str`

New module `src/mergecraft/config/provider_registry.py`:

- `BUILTIN_HARNESS_DEFAULTS: dict[str, str]`
- `allocate_env_index(entries: Sequence[Mapping[str, Any]]) -> int`
- `harness_supports_provider` — alias of `mergecraft.utils.agent_resolve._harness_supports_provider`
- `list_supported_harnesses() -> Sequence[HarnessRow]`

Config schema (`src/mergecraft/config/settings.py` additive):

```yaml
providers:
  - label: nous
    url: https://…
    harness: opencode
    envIndex: 1
    authKind: api_key   # optional; cloud_chain for Bedrock/Vertex
```

`.env` indexed keys:

```dotenv
LLM_PROVIDER_1=nous
LLM_PROVIDER_1_API_KEY=…
```

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| BA | all `@_XFAIL` / module-xfail tests in `tests/cli/test_provider_cmd.py` and `tests/cli/test_provider_registry.py` except `test_providers_catalog_has_fourteen_builtin_entries` |

## Verification commands

```bash
make lint
make typecheck
uv run pytest --collect-only -q tests/cli/test_provider_cmd.py tests/cli/test_provider_registry.py
uv run pytest -q tests/cli/test_provider_cmd.py tests/cli/test_provider_registry.py  # RED: xfails expected
```

## BA RED evidence

- W1 test-author wave: `97b21581` — 35 collected, 34 xfails, 1 pass (`test_providers_catalog_has_fourteen_builtin_entries`)

## BB #478 — unified ``provider auth`` → BB

| Contract | Tests | Layer |
| --- | --- | --- |
| `provider auth` registered on Typer app | `tests/cli/test_provider_auth_registry.py::test_provider_auth_cmd_registered_on_provider_app`, `tests/cli/test_provider_auth_cmd.py::test_provider_help_lists_auth_verb` | functional |
| Non-interactive `provider auth <label>` writes `LLM_PROVIDER_<N>_API_KEY` | `tests/cli/test_provider_auth_cmd.py::test_provider_auth_nous_writes_indexed_api_key` | E2E |
| Unknown label exits non-zero | `…::test_provider_auth_unknown_label_exits_nonzero` | error |
| Re-auth overwrites indexed key in place | `…::test_provider_auth_reauth_overwrites_indexed_key_in_place` | E2E |
| Interactive picker when label omitted | `…::test_provider_auth_interactive_picker_selects_provider`, `…::test_provider_auth_picker_lists_registered_labels_and_urls` | E2E |
| `--scope` flag documented | `…::test_provider_auth_help_documents_scope_flag` | functional |

### D6 — ``auth logfire`` stays separate → BB

| Contract | Tests | Layer |
| --- | --- | --- |
| `auth logfire` remains under `mergecraft auth` | `tests/cli/test_provider_auth_cmd.py::test_auth_logfire_remains_under_auth_namespace` | functional (green) |
| `provider auth logfire` rejected | `…::test_provider_auth_logfire_is_rejected` | error |
| Picker excludes logfire | `…::test_provider_auth_picker_excludes_logfire` | E2E |

### D10 — auth kinds / cloud_chain → BB

| Contract | Tests | Layer |
| --- | --- | --- |
| `api_key` / `oauth` / `device_code` indexed suffixes | `tests/cli/test_provider_auth_registry.py::test_indexed_credential_keys_for_auth_kind[*]` | unit |
| `resolve_auth_strategy` dispatches per kind | `…::test_resolve_auth_strategy_returns_handler_per_kind[*]` | unit |
| Bedrock `cloud_chain` writes AWS keys, not `_API_KEY` | `tests/cli/test_provider_auth_cmd.py::test_provider_auth_bedrock_cloud_chain_writes_indexed_aws_keys[*]`, `tests/cli/test_provider_auth_registry.py::test_cloud_chain_bedrock_keys_exclude_api_key_suffix` | E2E / unit |
| Vertex path-based credentials | `tests/cli/test_provider_auth_cmd.py::test_provider_auth_vertex_writes_credentials_path_not_api_key` | E2E |
| Multi-line JSON guard preserved | `…::test_provider_auth_vertex_refuses_multiline_json_for_local_scope` | error |
| Seeded built-in `authKind` defaults | `tests/cli/test_provider_auth_registry.py::test_seeded_builtin_auth_kind_defaults[*]` | unit |

### D7 — legacy shim → BB

| Contract | Tests | Layer |
| --- | --- | --- |
| Legacy `auth <provider>` warns and delegates to indexed write | `tests/cli/test_provider_auth_cmd.py::test_legacy_auth_commands_warn_and_write_indexed_secret[*]` | E2E |
| Warning emitted once per process | `…::test_legacy_auth_warning_emitted_once_per_process` | unit / E2E |

### Pinned public API (implementation wave BB)

Extend `src/mergecraft/cli/provider_cmd.py`:

- Typer subcommand: `auth` (`provider_auth_cmd`)
- `indexed_credential_keys(entry: Mapping[str, Any]) -> Sequence[str]`
- `resolve_auth_strategy(auth_kind: str) -> AuthStrategy`
- `_warn_legacy_auth_once(message: str) -> None` in `auth_cmd.py` (once-per-process guard)

Extend `src/mergecraft/config/provider_registry.py`:

- `default_auth_kind_for_label` — add `device_code` (`openai`), `oauth` (`anthropic`)

### BB xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| BB | all `@BB_XFAIL` tests in `tests/cli/test_provider_auth_cmd.py` and `tests/cli/test_provider_auth_registry.py` except `test_auth_logfire_remains_under_auth_namespace` |

### BB verification commands

```bash
uv run pytest --collect-only -q tests/cli/test_provider_auth_cmd.py tests/cli/test_provider_auth_registry.py
uv run pytest -q tests/cli/test_provider_auth_cmd.py tests/cli/test_provider_auth_registry.py  # RED: xfails expected
```

## BC #479 — model add/list/delete per provider

Maps **BC RED** contracts for #479 (`model add/list/delete`) to the test suite.

### D2 — config source of truth + optional env override → BC

| Contract | Tests | Layer |
| --- | --- | --- |
| Models stored in `.mergecraft/config.yaml` under provider `models:` | `tests/cli/test_model_cmd.py::test_model_add_writes_model_to_config_without_provider_prefix` | E2E |
| Config is source of truth; env not written by default | `…::test_model_add_does_not_write_env_by_default` | E2E |
| `LLM_PROVIDER_<N>_MODEL_<M>` env override optional | `…::test_model_env_override_optional` | E2E / integration |

### D3 — permanent model indices → BC

| Contract | Tests | Layer |
| --- | --- | --- |
| `delete` leaves a model index gap | `tests/cli/test_model_cmd.py::test_model_delete_leaves_model_index_gap_and_never_reuses` | E2E |
| New `add` allocates `max(existing modelIndex) + 1` | `…::test_model_add_allocates_max_plus_one_model_index_with_gaps`, `…::test_allocate_model_index_returns_max_plus_one` | E2E / unit |
| Freed model indices are never reused | `…::test_model_delete_leaves_model_index_gap_and_never_reuses`, `…::test_allocate_model_index_never_reuses_gaps` | E2E / unit |

### Model id shape → BC

| Contract | Tests | Layer |
| --- | --- | --- |
| Model id stored without provider prefix | `tests/cli/test_model_cmd.py::test_model_add_writes_model_to_config_without_provider_prefix`, `…::test_stored_model_rows_use_id_without_provider_prefix_field` | E2E |
| Prefixed CLI input normalizes to unprefixed storage | `…::test_stored_model_rows_use_id_without_provider_prefix_field` | E2E |

### CLI verbs → BC

| Contract | Tests | Layer |
| --- | --- | --- |
| `model add/list/delete` registered | `tests/cli/test_model_cmd.py::test_model_help_lists_registry_verbs` | functional |
| `model list` surfaces registered models | `…::test_model_list_shows_registered_models` | E2E |
| `model delete` removes model row | `…::test_model_delete_removes_model_from_config` | E2E |
| Unknown `--provider` fails and names registered providers | `…::test_model_add_unknown_provider_fails_and_names_registered_providers`, `…::test_model_delete_unknown_provider_fails` | error |
| Omitting `--provider` prompts registered providers | `…::test_model_add_without_provider_prompts_registered_providers` | functional |
| Duplicate model on same provider rejected | `…::test_model_add_rejects_duplicate_model_on_same_provider` | error |

### Pinned public API (implementation wave BC)

New module `src/mergecraft/cli/model_cmd.py`:

- Typer subcommands: `add`, `list`, `delete`
- Interactive provider picker when `--provider` omitted

New module `src/mergecraft/config/model_registry.py` (or extend `provider_registry`):

- `allocate_model_index(entries: Sequence[Mapping[str, Any]]) -> int`

Config schema (`ProviderRegistryEntry` additive):

```yaml
providers:
  - label: nous
  url: https://…
  harness: opencode
  envIndex: 1
  models:
    - id: deepseek/deepseek-v4-flash
      modelIndex: 1
```

Optional `.env` override keys:

```dotenv
LLM_PROVIDER_1_MODEL_1=deepseek/deepseek-v4-flash
```

### xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| BC | all `@pytest.mark.xfail(reason="green after BC impl")` in `tests/cli/test_model_cmd.py` |

## BC RED evidence

- BC test-author wave: `a97b2664` — 15 collected, 15 xfails; BC test files lint clean; `make typecheck` clean

### BC RED verification

```bash
uv run ruff check tests/cli/test_model_cmd.py tests/cli/support_provider_registry.py
make typecheck
uv run pytest --collect-only -q tests/cli/test_model_cmd.py
uv run pytest -q tests/cli/test_model_cmd.py  # RED: xfails expected
```

## BD #480 — ``agents setmodel`` / ``addbackupmodel``

Maps **BD RED** contracts for #480 (`agents setmodel` / `addbackupmodel`) to the test suite.

### D8 — primary-only replacement + backup append → BD

| Contract | Tests | Layer |
| --- | --- | --- |
| ``setmodel`` replaces primary only; backups preserved | `tests/cli/test_agents_setmodel_cmd.py::test_agents_setmodel_replaces_primary_preserves_backups` | E2E |
| ``addbackupmodel`` appends one entry | `…::test_agents_addbackupmodel_appends_to_chain` | E2E |
| Two ``addbackupmodel`` calls yield ordered distinct backups | `…::test_agents_addbackupmodel_twice_yields_two_distinct_backups_in_order` | E2E |
| Duplicate backup (same provider+model) rejected | `…::test_agents_addbackupmodel_rejects_duplicate_backup` | error |
| ``agents set --model`` no longer wipes backup chain | `…::test_agents_set_preserves_backup_chain_after_model_override` | E2E / regression |

### Registry validation at write time → BD

| Contract | Tests | Layer |
| --- | --- | --- |
| Unregistered provider exits non-zero; config unchanged | `…::test_agents_setmodel_unregistered_provider_fails_at_write_time` | error |
| Unregistered model exits non-zero; config unchanged | `…::test_agents_setmodel_unregistered_model_fails_at_write_time` | error |
| ``addbackupmodel`` unregistered pair fails at write time | `…::test_agents_addbackupmodel_unregistered_pair_fails_at_write_time` | error |

### CLI verbs + UX → BD

| Contract | Tests | Layer |
| --- | --- | --- |
| ``setmodel`` / ``addbackupmodel`` registered on agents app | `…::test_agents_help_lists_setmodel_and_addbackupmodel_verbs` | functional |
| Help documents ``--provider`` / ``--model`` / ``--all`` | `…::test_agents_setmodel_help_documents_flags` | functional |
| Unknown agent role exits non-zero and lists valid roles | `…::test_agents_setmodel_rejects_unknown_role_lists_valid_roles`, `…::test_agents_addbackupmodel_rejects_unknown_role` | error |
| Interactive pickers when flags omitted | `…::test_agents_setmodel_interactive_picker_when_flags_omitted` | E2E |
| ``--all`` lists overwrite targets before applying | `…::test_agents_setmodel_all_lists_targets_before_overwrite` | E2E |
| ``AgentBindingOverride`` validation before file write | `…::test_agents_setmodel_validates_binding_before_write` | error |

### Pinned public API (implementation wave BD)

Extend `src/mergecraft/cli/agents_cmd.py`:

- Typer subcommands: `setmodel` (`setmodel_cmd`), `addbackupmodel` (`addbackupmodel_cmd`)
- Registry validation helper (e.g. `validate_registered_model_slug(provider, model_id)`) — fails at write time
- Fix `set_cmd` so `--model` replaces primary only (D8 bug fix)

Shared fixtures in `tests/cli/support_provider_registry.py`:

- `format_model_slug`, `write_agents_model_chain`, `agents_model_chain`, `import_agents_cmd`

### xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| BD | all `@BD_XFAIL` / `@pytest.mark.xfail(reason="green after BD impl")` in `tests/cli/test_agents_setmodel_cmd.py` |

### BD verification commands

```bash
uv run pytest --collect-only -q tests/cli/test_agents_setmodel_cmd.py
uv run pytest -q tests/cli/test_agents_setmodel_cmd.py  # RED: xfails expected
```

## BD RED evidence

- BD test-author wave: `6618dba3` — 15 collected, 15 xfails; lint+typecheck clean

## BE #481 — Nous as ordinary registry provider

Maps **BE RED** contracts for #481 (drop presets, registry-only runtime, kill opencode
fallback) to the test suite.

### D4 — unknown provider is configuration_error → BE

| Contract | Tests | Layer |
| --- | --- | --- |
| Unknown slug must not infer ``opencode`` via ``_agent_mode_for_slug`` | `tests/agents/test_registry_provider_runtime.py::test_agent_mode_for_unknown_provider_raises_configuration_error` | unit / error |
| ``resolve_harness`` fails for unregistered provider | `…::test_resolve_harness_unknown_provider_raises_configuration_error` | unit / error |
| ``resolve_runtime_agent`` must not silently return opencode | `…::test_resolve_runtime_agent_unknown_provider_not_opencode` | integration / error |
| Error maps to ``RunOutcome.configuration_error`` | `…::test_classify_unknown_provider_error_maps_to_configuration_error` | integration |
| ``_harness_supports_provider`` rejects unregistered custom label | `…::test_harness_supports_provider_rejects_unregistered_custom_provider` | unit |

### Registry-only Nous (harness: opencode) → BE

| Contract | Tests | Layer |
| --- | --- | --- |
| Nous slug resolves via registry ``harness: opencode`` | `…::test_nous_resolves_to_opencode_via_registry_harness` | integration |
| Indexed ``LLM_PROVIDER_<N>_API_KEY`` is the credential source | `…::test_nous_credentials_from_indexed_registry_key_only` | unit |
| Nous without registry row is configuration error | `…::test_nous_without_registry_entry_raises_configuration_error` | error |
| Gateway endpoint uses registry URL, not preset default | `…::test_resolve_gateway_endpoint_uses_registry_url_not_preset` | integration |

### Remove presets / special-casing → BE

| Contract | Tests | Layer |
| --- | --- | --- |
| ``GATEWAY_PRESETS`` excludes nous/tokenhub/minimax | `tests/agents/test_registry_provider_presets_removed.py::test_gateway_presets_exclude_nous_tokenhub_minimax` | unit |
| Preset env/base-url constants removed | `…::test_named_gateway_env_constants_removed[*]` | unit |
| ``_OPENCODE_NATIVE_PROVIDERS`` excludes preset labels | `…::test_opencode_native_providers_exclude_gateway_preset_labels` | unit |
| ``_KNOWN_CATALOG_PROVIDERS`` excludes preset labels | `…::test_known_catalog_providers_exclude_gateway_preset_labels` | unit |
| No hardcoded nous/tokenhub/minimax branches in ``agent_resolve`` | `…::test_agent_resolve_has_no_nous_tokenhub_minimax_branches` | structural |

### Harness per registry row → BE

| Contract | Tests | Layer |
| --- | --- | --- |
| Each harness value honoured from registry data | `tests/agents/test_registry_provider_runtime.py::test_registry_declared_harness_respected_at_runtime[*]` | integration |

### D7 — legacy ``NOUS_API_KEY`` shim → BE

| Contract | Tests | Layer |
| --- | --- | --- |
| Legacy key works with one deprecation warning per process | `…::test_legacy_nous_api_key_emits_deprecation_warning_once` | unit |

### Pinned owner modules (implementation wave BE)

- `src/mergecraft/utils/agent_resolve.py` — kill bare ``return "opencode"``; registry lookup; remove preset branches
- `src/mergecraft/models.py` — ``PROVIDERS`` seed-only (no runtime special-casing)
- `src/mergecraft/agents/openai_compatible_gateways.py` — remove ``GATEWAY_PRESETS`` nous/tokenhub/minimax rows and named env constants

Shared fixtures in `tests/cli/support_provider_registry.py`:

- `bootstrap_nous_registry`, `write_registry_provider_row`, `write_indexed_provider_secret`, `clear_legacy_gateway_env`

### xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| BE | all `@BE_XFAIL` / `@pytest.mark.xfail(reason="green after BE impl")` in `tests/agents/test_registry_provider_runtime.py` and `tests/agents/test_registry_provider_presets_removed.py` |

### BE verification commands

```bash
uv run pytest --collect-only -q tests/agents/test_registry_provider_runtime.py tests/agents/test_registry_provider_presets_removed.py
uv run pytest -q tests/agents/test_registry_provider_runtime.py tests/agents/test_registry_provider_presets_removed.py  # RED: xfails expected
```

## BE RED evidence

- BE test-author wave: `f8ca1c23` — 28 collected, 28 xfails; lint+typecheck clean
