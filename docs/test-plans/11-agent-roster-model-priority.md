# Agent roster, model priority & multi-reviewer — test plan

Maps **W1 RED** contracts for wave plan 11 to the test suite.
Source plan: `.ignorelocal/waves/11-agent-roster-model-priority-wave-plan.md`.

## W1.1 — slot primitives → W2

| Contract | Tests | Layer |
| --- | --- | --- |
| `assign_slot` on empty chain at `p0` | `tests/config/test_agent_roster.py::test_assign_slot_on_empty_chain_at_p0_creates_one_long_chain` | unit |
| `assign_slot` replaces at index, preserves length | `…::test_assign_slot_at_existing_index_replaces_preserves_other_slots` | unit |
| `assign_slot` beyond end names next slot (D5) | `…::test_assign_slot_beyond_end_names_next_assignable_slot` | unit / error |
| `add_model` appends | `…::test_add_model_appends_to_tail` | unit |
| duplicate `add_model` no-op (D4) | `…::test_add_model_duplicate_is_noop_with_message` | unit |
| `pN` parsing rejects malformed tokens | `…::test_parse_slot_rejects_malformed_tokens[*]` | unit / error |
| `parse_slot("p0")` → 0 | `…::test_parse_slot_accepts_p0` | unit |
| `remove_slot` compacts chain | `…::test_remove_slot_compacts_chain` | unit |
| `remove_slot` refuses empty chain | `…::test_remove_slot_refuses_empty_chain` | unit / error |
| `write_roster` omits unset `after:` | `…::test_write_roster_omits_after_when_unset` | unit |

Pinned module: `mergecraft.config.agent_roster` (`parse_slot`, `assign_slot`, `add_model`, `remove_slot`, `write_roster`).

## W1.2 — named agents → W3

| Contract | Tests | Layer |
| --- | --- | --- |
| `agent create reviewer2 --role reviewer` | `tests/cli/test_agent_cmd.py::test_agent_create_reviewer2_writes_role` | E2E |
| `--after` writes `after:`; omit leaves key absent | `…::test_agent_create_with_after_writes_after_key` | E2E |
| unknown `after:` load error (D15) | `…::test_after_unknown_agent_is_load_time_error` | unit / error |
| `after:` cycle load error (D15) | `…::test_after_cycle_is_load_time_error` | unit / error |
| D11 pattern violations rejected | `…::test_agent_create_rejects_d11_pattern_violations[*]` | E2E / error |
| second orchestrator rejected | `…::test_agent_create_rejects_second_orchestrator` | E2E / error |
| `assign-model` on non-`AgentRole` name | `…::test_agent_assign_model_works_on_non_agent_role_name` | E2E |
| delete refuses last reviewer (D12) | `…::test_agent_delete_refuses_last_reviewer` | E2E / error |
| delete refuses last verifier (D12) | `…::test_agent_delete_refuses_last_verifier` | E2E / error |

Pinned module: `mergecraft.cli.agent_cmd`.

## W1.3 — local scope → W4

| Contract | Tests | Layer |
| --- | --- | --- |
| `agent-local` writes local file only (D2) | `tests/cli/test_agent_local_cmd.py::test_agent_local_writes_local_file_not_committed_config` | E2E |
| local file gitignored | `…::test_agent_local_config_is_gitignored` | functional |
| local overrides win for CLI | `…::test_agent_local_overrides_win_for_cli_runs` | E2E |
| `GITHUB_ACTIONS=true` ignores local (D2) | `…::test_github_actions_ignores_local_file` | integration |

Pinned module: `mergecraft.cli.agent_local_cmd`.

## W1.4 — registry multiplicity → W5

| Contract | Tests | Layer |
| --- | --- | --- |
| two lens-less reviewers survive `load_registry` | `tests/agents/test_agent_roster_registry.py::test_two_lensless_reviewer_bindings_survive_load_registry` | unit |
| `resolve_role(reviewer)` returns keyed `reviewer` | `…::test_resolve_role_returns_binding_keyed_reviewer_not_last_wins` | unit |
| `resolve_roles(reviewer)` returns both, stable order | `…::test_resolve_roles_returns_both_reviewers_in_stable_order` | unit |
| `validate()` rejects empty chain | `…::test_registry_validate_rejects_empty_model_chain` | unit / error |
| `validate()` rejects unreachable lens | `…::test_registry_validate_rejects_unreachable_lens` | unit / error |

Pinned API: `Registry.resolve_roles`, `Registry.resolve_role_levels` (W5).

## W1.5 — multi-reviewer execution → W6

| Contract | Tests | Layer |
| --- | --- | --- |
| `default_subagent_selection` returns all reviewers + verifier | `tests/agents/test_multi_reviewer_execution.py::test_default_subagent_selection_returns_every_reviewer_plus_verifier` | unit |
| merge dedupes `(path, body, line)` (D6) | `…::test_merge_dedupes_identical_path_body_line` | unit |
| distinct Critical lines both survive | `…::test_merge_preserves_critical_findings_at_different_lines` | unit |
| one verdict + one terminal submission (D7) | `…::test_merged_findings_yield_one_verdict_and_one_terminal_submission` | unit |
| Critical from reviewer2 blocks (strictest wins) | `…::test_critical_from_reviewer2_blocks_when_reviewer_approves` | unit |
| one reviewer failing does not void other findings | `…::test_one_reviewer_failing_does_not_void_other_findings` | unit |

Pinned module: `mergecraft.agents.reviewer_merge` (`merge_reviewer_findings`, `verdict_from_merged_findings`, `ReviewerRun`, `terminal_submission_count_from_review_runs`, `format_reviewer_degradation_summary`).

## W1.6 — trust (D9)

| Contract | Tests | Layer |
| --- | --- | --- |
| PR-head `agents:` edit cannot change reviewing model | `tests/config/test_agent_roster_trust.py::test_pr_head_agents_edit_cannot_change_reviewing_model` | integration |
| config hash mismatch fails closed | `…::test_config_hash_mismatch_during_read_only_run_fails_closed` | unit (AG2 green) |

Reuses `mergecraft.config.settings_snapshot` (AG2 landed).

## W1.7 — auth manifest & fail-closed → W7

| Contract | Tests | Layer |
| --- | --- | --- |
| `parse_auth_manifest` reads indexed `LLM_PROVIDER_<N>_*` | `tests/cli/test_agent_roster_auth_manifest.py::test_parse_auth_manifest_reads_indexed_llm_provider_env` | unit |
| `if:`-gated secret step counts as wired | `…::test_parse_auth_manifest_counts_secret_gated_step` | unit |
| `agent assign-model` bails unwired (D1a) | `…::test_agent_assign_model_bails_on_unwired_provider` | E2E / error |
| `--allow-unwired` warns and permits | `…::test_agent_assign_model_allow_unwired_permits_with_warning` | E2E |
| `agent-local` accepts unwired | `…::test_agent_local_accepts_unwired_provider` | E2E |
| run-start fails closed, no p1 fallback | `…::test_run_start_validation_fails_closed_on_unwired_provider` | integration |
| unwired vs empty secret messages differ | `…::test_unwired_provider_and_empty_secret_messages_differ` | error |
| `workflow sync --check` non-zero, no write | `…::test_workflow_sync_check_exits_nonzero_and_writes_nothing` | E2E |
| `workflow sync --apply` owned keys only | `…::test_workflow_sync_apply_adds_missing_step_with_owned_keys_only` | E2E |

Pinned API: `mergecraft.cli.workflow_cmd.parse_auth_manifest`, roster run-start validator, `workflow sync`.

## W1.8 — init → W8

| Contract | Tests | Layer |
| --- | --- | --- |
| `init` + first auth → one `modelChain` entry (D10) | `tests/cli/test_agent_roster_init.py::test_init_plus_auth_seeds_single_model_chain_entry` | E2E |
| entry is provider preferred model | `…::test_seeded_entry_uses_authenticated_provider_preferred_model` | E2E |
| init does not overwrite existing roster | `…::test_init_on_existing_roster_does_not_overwrite` | E2E |
| review runs after `init` + auth only (D10) | `…::test_review_runs_after_init_and_auth_without_third_command` | E2E |

## Shared helpers

`tests/cli/support_agent_roster.py` — fixtures, xfail markers, import guards.

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| W2 | reconciled — `tests/config/test_agent_roster.py`, `tests/config/test_agent_roster_trust.py::test_pr_head_*` |
| W3 | `tests/cli/test_agent_cmd.py` |
| W4 | reconciled — `tests/cli/test_agent_local_cmd.py` |
| W5 | `tests/agents/test_agent_roster_registry.py` |
| W6 | `tests/agents/test_multi_reviewer_execution.py` |
| W7 | `tests/cli/test_agent_roster_auth_manifest.py` |
| W8 | `tests/cli/test_agent_roster_init.py` |

## Verification commands

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev"
make lint
make typecheck
uv run pytest --collect-only -q \
  tests/config/test_agent_roster.py \
  tests/config/test_agent_roster_trust.py \
  tests/cli/test_agent_cmd.py \
  tests/cli/test_agent_local_cmd.py \
  tests/cli/test_agent_roster_auth_manifest.py \
  tests/cli/test_agent_roster_init.py \
  tests/agents/test_agent_roster_registry.py \
  tests/agents/test_multi_reviewer_execution.py
```

## W1 RED evidence

- 53 collected, 51 xfailed, 2 passed (AG2 hash guard + existing empty-chain `validate()` regression)
