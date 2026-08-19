# Open issues sweep 2026-08-19b — test plan

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-19b-wave-plan.md`
Worktree: `../mergecraft-issues-sweep-2026-08-19b` @ `wave/issues-sweep-2026-08-19b`
Authoring waves: **W1** (Batch G RED) · **W5** (Batch H RED — xpass inventory)

W1 pins #277 (xdist flake on grandchild reap) and #278 (`MERGECRAFT_LIVE=1` opt-in)
without changing production code. W5 inventories stale `xfail(strict=False)` xpasses
(#276) and adds the RED `scripts/check_xpass.py` ratchet. D6-forbidden paths are
not edited; D6 xpasses are counted then excluded from the W6 cleanup list.

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W3** | `test_setup_script_grandchildren_are_reaped` | `green after W3: #277 wait for pid_file before kill clock` | greened in W3 |
| **W4** | `test_live_module_skips_when_mergecraft_live_unset` (6 cases) | `green after W4: MERGECRAFT_LIVE skip gate` | greened in W4 |
| **W7** | `tests/ci/test_xpass_check.py::test_make_xpass_check_is_wired` | `green after W7: make xpass-check ratchet` | pending — Makefile target not wired (W5 RED) |

**W6 must not promote** the W7 wiring xfail. That test is still failing (no
`make xpass-check`); it is an xfail, not an xpass.

## Contract matrix

### #277 / D12 — grandchild reap without a 0.5s spawn window

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| G277a | Readiness poll is independent of the 0.5s kill clock | unit | happy — file appears at 0.8s | `tests/config/test_setup_script_timeout.py::test_wait_until_exists_does_not_assume_half_second_grace` |
| G277b | Missing readiness file is not ready | unit | edge — never written | `test_wait_until_exists_returns_false_when_file_never_appears` |
| G277c | Reap recording takes an explicit deadline | unit | happy / edge — `sleep 10` still alive after 0.25s | `test_record_pid_reaped_deadline_is_independent_of_wait_or_kill_timeout` |
| G277d | Non-positive reap deadline is rejected | unit | error — `0` / `-1` | `test_record_pid_reaped_rejects_non_positive_deadline` |
| G277e | Kill-before-readiness fails deterministically | functional | error — old timing | `test_setup_script_grandchildren_are_reaped` (greened W3) |

W3 greens G277e by calling `_wait_until_exists(pid_file)` **before** `wait_or_kill_process_group`. Do not mock `kill_process_group`.

### #278 / D8 — live opt-in

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| G278a | Unset / empty / `"0"` → skip, not fail | functional | happy + edge | `tests/ci/test_live_opt_in.py::test_live_module_skips_when_mergecraft_live_unset` |
| G278b | `MERGECRAFT_LIVE=1` + no creds → fail | functional | error (D9 preserved) | `test_live_module_fails_when_flag_set_without_credentials` |

Both live modules are parametrized:

- `tests/integration/test_live_providers.py`
- `tests/integration/test_github_integration.py`

Child pytest runs with credentials stripped so a developer laptop with keys cannot accidentally hit a provider.

## W1.1 note

Deterministic RED, not inspection-only. The grandchild script delays the pid-file write by 1s so `wait_or_kill(..., timeout=0.5)` expires before readiness. Helpers `_wait_until_exists` and `_record_pid_reaped` have no 0.5s default.

## Acceptance (W1)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- G277 helper units pass; G277e xfail; G278a xfail; G278b pass
- No `src/` edits; no D6 paths

---

## Batch H — xfail hygiene (#276 / D9)

Authoring wave: **W5**. Implementation: **W6** (promote allowed-tree xpasses),
**W7** (`make xpass-check` wiring). Do not edit D6 test files.

### W5.1 inventory (2026-08-19 @ `7e3f5a5`)

Command: `uv run pytest tests -m "not integration" --strict-markers -q --tb=no -rX --randomly-seed=424242 -n auto`

| Bucket | Count |
|--------|-------|
| Total xpassed | **121** |
| Allowed-tree (W6 cleanup) | **113** |
| D6-excluded (count only; do not promote) | **8** |
| xfailed (still failing; not this wave) | 13 |
| passed / skipped | 2989 / 30 |

GF reported 119 xpassed; this W5 run is 121. The extra two are still on the
allowed tree and belong in the cleanup list below. `tests/ci/test_xpass_check.py::test_make_xpass_check_is_wired`
is **xfailed**, not xpassed — leave it for W7.

D6 xpasses (excluded from cleanup; all in `tests/agents/test_codex_custom_provider.py`):

- `test_codex_config_toml_writes_both_indexed_providers`
- `test_codex_config_toml_writes_three_indexed_providers`
- `test_codex_indexed_wins_singleton_ignored`
- `test_codex_partial_indexed_coverage_writes_only_present_providers` (4 params)
- `test_codex_singleton_alone_emits_default_provider_block`

### W5.2 RED ratchet

`scripts/check_xpass.py` parses pytest `-rX` / `-ra` `XPASS nodeid - reason`
lines. `--from-log PATH` is the cheap W7 path; omitting the log runs the unit
suite. Exit 1 when allowed-tree xpass > 0; D6 xpasses are printed in the
counts and ignored. Verified RED on the W5.1 log: exit 1,
`113 allowed-tree xpassed (121 total, 8 D6-excluded)`.

`make xpass-check` is **not** wired (W7). No `Makefile` edit in W5.

### Contract matrix (#276)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| H276a | Script exists | unit | happy | `tests/ci/test_xpass_check.py::test_script_exists` |
| H276b | D6 path set covers the plan's test files | unit | happy | `test_d6_paths_cover_plan_test_files` |
| H276c | Nodeid D6 classification (incl. params) | unit | happy / edge | `test_is_d6_nodeid` |
| H276d | Log parse splits D6 vs allowed | unit | happy | `test_parse_xpass_log_splits_d6_and_allowed` |
| H276e | Empty log is zero xpass | unit | edge | `test_parse_xpass_log_empty_is_zero` |
| H276f | Allowed-tree xpass → exit 1 | unit | error | `test_check_xpass_fails_on_allowed_tree` / `test_main_from_log_exits_one_on_allowed_xpass` |
| H276g | D6-only xpass → exit 0 | unit | edge | `test_check_xpass_ok_when_only_d6_xpasses` |
| H276h | Zero xpass → exit 0 | unit | happy | `test_check_xpass_ok_when_zero_xpasses` |
| H276i | Missing log file → exit 2 | unit | error | `test_main_from_log_missing_file_exits_two` |
| H276j | `make xpass-check` is in the Make graph | integration | happy after W7 | `test_make_xpass_check_is_wired` (xfail until W7) |

### W6 cleanup list (allowed-tree xpasses only)

Remove `xfail(strict=False)` from these 113 nodeids. Keep the test body. Do
not delete tests. Do not touch D6 files.

`tests/agents/test_minimax_routing.py` (74):

- `test_existing_curated_slug_resolution_is_unchanged` — 68 parametrized cases
  (`anthropic/claude-haiku`, `anthropic/claude-opus`, `anthropic/claude-sonnet`,
  `bedrock/byok`, `deepseek/deepseek-chat`, `deepseek/deepseek-flash`,
  `deepseek/deepseek-pro`, `deepseek/deepseek-reasoner`, `google/gemini-flash`,
  `google/gemini-pro`, `moonshotai/kimi-k2`, `nous/deepseek/deepseek-v4-flash`,
  `openai/gpt-5.4`, `openai/gpt-codex-mini`, `openai/gpt-codex`, `openai/gpt-mini`,
  `openai/gpt-pro`, `openai/gpt-terra`, `openai/gpt`, `openai/o3`,
  `opencode-go/glm-5.1`, `opencode-go/kimi-k2`, `opencode/big-pickle`,
  `opencode/claude-haiku`, `opencode/claude-opus`, `opencode/claude-sonnet`,
  `opencode/gemini-flash`, `opencode/gemini-pro`, `opencode/gpt-5-nano`,
  `opencode/gpt-5.4`, `opencode/gpt-codex-mini`, `opencode/gpt-codex`,
  `opencode/gpt-mini`, `opencode/gpt-pro`, `opencode/gpt-terra`, `opencode/gpt`,
  `opencode/kimi-k2`, `opencode/mimo-v2-pro-free`, `opencode/minimax-m2.5-free`,
  `opencode/minimax-m2.5`, `openrouter/claude-haiku`, `openrouter/claude-opus`,
  `openrouter/claude-sonnet`, `openrouter/deepseek-chat`,
  `openrouter/deepseek-flash`, `openrouter/deepseek-pro`,
  `openrouter/gemini-flash`, `openrouter/gemini-pro`, `openrouter/gpt-5.4`,
  `openrouter/gpt-codex-mini`, `openrouter/gpt-codex`, `openrouter/gpt-mini`,
  `openrouter/gpt-pro`, `openrouter/gpt-terra`, `openrouter/gpt`,
  `openrouter/grok`, `openrouter/kimi-k2`, `openrouter/minimax-m2.5`,
  `openrouter/o4-mini`, `tokenhub/deepseek-v4-flash`, `tokenhub/deepseek-v4-pro`,
  `tokenhub/glm-5.2`, `tokenhub/hy3`, `tokenhub/kimi-k3`, `vertex/byok`,
  `xai/grok-code-fast`, `xai/grok-fast`, `xai/grok`)
- `test_minimax_missing_credential_fails_loud[minimax-minimax-m3]`
- `test_minimax_missing_credential_fails_loud[minimax-unknown-model]`
- `test_minimax_raw_passthrough_slug_resolves`
- `test_minimax_routes_via_codex_with_singleton_env`
- `test_minimax_routes_via_indexed_provider_pair`
- `test_minimax_routes_via_opencode_with_singleton_env`

`tests/agents/test_openai_compatible_gateways.py` (6):

- `test_shared_helper_exposes_multi_provider_resolver`
- `test_shared_multi_provider_resolver_drops_partial_pairs`
- `test_shared_multi_provider_resolver_handles_indexed_pairs`
- `test_shared_multi_provider_resolver_indexed_overrides_singleton`
- `test_shared_multi_provider_resolver_preserves_index_gaps`
- `test_shared_multi_provider_resolver_singleton_maps_to_default`

`tests/agents/test_opencode_custom_provider.py` (5):

- `test_opencode_emits_blocks_for_non_contiguous_indices`
- `test_opencode_emits_provider_blocks_for_each_indexed_pair`
- `test_opencode_indexed_wins_singleton_ignored`
- `test_opencode_partial_indexed_pair_is_dropped`
- `test_opencode_singleton_alone_emits_default_provider_block`

`tests/cli/test_models_list_minimax.py` (3):

- `test_mergecraft_models_list_minimax_row_does_not_leak_api_key`
- `test_mergecraft_models_list_renders_minimax_row_with_credentials`
- `test_mergecraft_models_list_renders_minimax_row_without_credentials`

`tests/evidence/test_gate_actions.py` (15):

- `test_disagreement_report_groups_by_lane_and_rule`
- `test_disagreement_report_on_match_records_no_disagreement`
- `test_enforce_mode_decision_differs_from_shadow_for_low_risk`
- `test_every_outcome_maps_to_a_named_action`
- `test_new_gates_default_to_shadow`
- `test_numeric_score_never_appears_without_findings_and_decision`
- `test_policy_changed_unread_file_maps_to_request_changes`
- `test_policy_high_risk_migration_maps_to_require_human_review`
- `test_policy_low_risk_passing_maps_to_auto_merge`
- `test_policy_schema_failure_maps_to_block`
- `test_policy_tool_loop_maps_to_require_more_tests`
- `test_record_shadow_prediction_writes_to_disk`
- `test_shadow_mode_records_prediction_without_blocking`
- `test_unknown_action_in_policy_is_rejected`
- `test_unrecognised_gate_mode_falls_back_to_shadow`

`tests/tracing/instrumentation/test_emit_failure.py` (2):

- `test_emit_failure_logs_a_warning`
- `test_emit_failure_never_fails_the_run`

`tests/utils/test_learnings_provenance.py` (8):

- `test_approved_learnings_are_fenced_at_seed_time`
- `test_entry_without_maintainer_provenance_is_quarantined`
- `test_every_learning_entry_carries_provenance`
- `test_fork_pr_injected_learning_text_promotes_nothing`
- `test_influence_listing_names_seeded_entries`
- `test_legacy_autopromote_available_as_optin`
- `test_promotion_requires_explicit_approval_by_default`
- `test_quarantined_entry_never_reaches_reviewer_prompt`

### Acceptance (W5)

- Inventory recorded (121 total / 113 allowed / 8 D6)
- `scripts/check_xpass.py` exits 1 on the current allowed tree
- Ratchet unit tests pass; Makefile wiring test xfail until W7
- `make lint` + `make typecheck` clean; collection clean
- No Makefile `xpass-check` target; not wired into `ci-static` / `make test`
- No D6 path edits; no xfail promotions (W6)
