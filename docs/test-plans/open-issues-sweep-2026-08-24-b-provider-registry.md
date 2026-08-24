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
