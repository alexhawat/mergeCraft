# Open issues sweep 2026-08-20d-a-engine — Batch DA test plan (#377–#380)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20d-a-engine-wave-plan.md`
Worktree: `.ignorelocal/worktrees/open-issues-sweep-2026-08-20d-a-engine` @ `wave/20d-a-engine`
Authoring wave: **W2** (DA RED) · Implementation: **W3–W6**

W9 (#383 capability / adversarial tests) is **out of scope** for this suite — do
not name a module `adversarial.py`. D13 write/Fix pins belong to W9. D16: nothing
under `skills/`.

## xfail schedule

All cross-wave markers use `@pytest.mark.xfail(..., strict=False)`.

| Wave | Tests | Marker reason | Status at W2 |
|------|-------|---------------|--------------|
| **W3** | remaining #377 verbs (not `describe` / `capabilities`) | `green after W3: remaining #377 verbs` | XFAIL |
| **W4** | first-finding stream, resume, result cache, cancel cleanup, goldens | `green after W4: first-finding stream / cache / resume / goldens` | XFAIL |
| **W5** | negotiate / retryable mismatch / budgets / D12 adapter | `green after W5: protocol negotiation / D12 reconcile` | XFAIL |
| **W6** | `ReviewSnapshot` type + CLI / Action / SCM conformance | `green after W6: ReviewSnapshot conformance` | XFAIL |

Green guards (no xfail): D8 inherit `describe` / `capabilities`; unknown verb →
usage exit 2; dual `schema_version` vs `protocol_version` stamps; hidden
`diff-review` alias. **W5 recon must delete** `test_agent_protocol_module_has_no_negotiate_export`
once negotiation lands (current-state negative).

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| DA377a | `describe` / `capabilities` stay registered (D8) | functional | happy | `tests/cli/test_da_missing_verbs.py::test_inherited_20c_verbs_remain_registered` |
| DA377b | Unknown root verb is usage-exit 2 | functional | error | `test_unknown_root_verb_is_still_usage_exit` |
| DA377c | `explain` / `ask` / `replay` registered + `--help` | functional | happy | `test_remaining_root_verb_is_registered`, `test_root_help_lists_remaining_verb` |
| DA377d | `run inspect` / `run diff` (root `run` typer, not `analyzers run`) | functional | happy + edge | `test_run_typer_exposes_inspect_and_diff`, `test_remaining_verbs_are_not_the_config_or_analyzers_homonyms` |
| DA377e | JSON payloads carry `schema_version` (D11) | functional | happy | `test_remaining_verb_json_payload_carries_schema_version`, `test_run_subcommand_json_payload_carries_schema_version` |
| DA377f | New modules use consoles + named exits + schema_version (D11) | unit | happy | `test_remaining_verb_module_uses_d11_surface` |
| DA378a | First finding emits while review is still running | functional | happy | `tests/cli/test_da_first_finding_stream.py::test_first_finding_emits_while_review_is_still_running` |
| DA378b | `review --resume` documented | functional | happy | `test_review_help_documents_resume` |
| DA378c | Review result cache beyond `mergecraft cache` | functional | happy | `test_review_help_documents_result_cache_beyond_cache_typer` |
| DA378d | Cancellation cleans up subprocesses | unit | error | `test_diff_review_cmd_exposes_cancellation_subprocess_cleanup` |
| DA378e | Reusable CLI golden at `tests/cli/goldens/review_first_finding.jsonl` (RV5) | functional | happy | `test_reusable_cli_golden_for_first_finding_exists` |
| DA379a | CLI JSON stamps `schema_version` `1.0.0` | unit | happy (current) | `tests/cli/test_da_protocol_negotiation.py::test_cli_json_stamps_schema_version` |
| DA379b | Agent JSONL stamps flat `protocol_version` `1` | unit | happy (current) | `test_agent_jsonl_stamps_flat_protocol_version` |
| DA379c | Dual fields unreconciled (D12 current) | unit | edge (current) | `test_schema_version_and_protocol_version_are_distinct_unreconciled_fields` |
| DA379d | No negotiate export yet | unit | current gap | `test_agent_protocol_module_has_no_negotiate_export` |
| DA379e | `negotiate_protocol` selects a version | unit | happy | `test_negotiate_protocol_selects_a_mutually_supported_version` |
| DA379f | Mismatch is retryable | unit | error | `test_protocol_mismatch_is_retryable` |
| DA379g | Named `PROTOCOL_BUDGET_FIELDS` (not ad-hoc kwargs) | unit | edge | `test_protocol_declares_budget_fields_for_negotiation` |
| DA379h | D12 adapter mentions both field names (no survivor guess) | unit | happy | `test_d12_exposes_a_version_field_adapter_without_picking_the_survivor` |
| DA380a | `review` listed; `diff-review` hidden | functional | happy (current) | `tests/review/test_da_review_snapshot.py::test_review_is_the_documented_command` |
| DA380b | Hidden `diff-review` remains invocable | functional | edge (current) | `test_hidden_diff_review_alias_remains_invocable` |
| DA380c | `ReviewSnapshot` type exists | unit | happy | `test_review_snapshot_type_exists` |
| DA380d | One engine callable accepts `ReviewSnapshot` | unit | happy | `test_shared_engine_accepts_review_snapshot` |
| DA380e | CLI review builds a snapshot | integration | happy | `test_cli_review_path_builds_a_review_snapshot` |
| DA380f | Action/`mergecraft.main` builds a snapshot | integration | happy | `test_action_path_builds_a_review_snapshot` |
| DA380g | SCM `conforming_review_request` feeds a snapshot | integration | happy | `test_scm_conforming_request_builds_or_feeds_a_review_snapshot` |

Existing greens **not duplicated:** `tests/cli/test_agent_protocol.py` (flat
`protocol_version` on `--agent` events).

Golden entry point for file 8 RV5: `tests/cli/goldens/review_first_finding.jsonl`
(not created in W2 — W4 lands it). D11: JSONL CLI/agent output only; no second
stdout/stderr split.
