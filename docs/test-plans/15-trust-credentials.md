# Trust boundary & credential truth — test plan

Wave plan: `.ignorelocal/waves/15-trust-credentials-wave-plan.md`
Worktree: `mergecraft-trust` @ `wave/trust-credentials`
Authoring wave: **W1** (`test-creator`). Implementation: **W2–W6**.

All cross-wave reds use `@pytest.mark.xfail(..., strict=True)` per the lane plan —
`scripts/check_xpass.py` fails non-strict xfails that pass.

## W1.1 — Codex sandbox policy gate → W2

| Contract | Tests | Layer |
| --- | --- | --- |
| Tier × head matrix (20 cells) | `tests/agents/test_codex_sandbox_policy.py::test_agent_sandbox_tier_head_matrix` | unit |
| Fork floor all tiers (D1b) | `…::test_fork_head_is_hard_floor_in_every_tier` | unit |
| Lane-D coupling (D1a) | `…::test_lane_d_coupling_self_review_does_not_open_sandbox_on_prt` | unit |
| selfReview symmetric guard | `…::test_self_review_level_does_not_change_matrix_cells` | unit |
| merged-only ancestor honour | `…::test_merged_only_honours_when_head_is_ancestor_of_default` | unit |
| Unfetched default → refuse | `…::test_merged_only_refuses_when_default_branch_unfetched` | unit |
| Refusal warning fields (D2) | `…::test_refused_override_logs_warning_with_contract_fields` | unit |
| Grant recorded (D2a) | `…::test_granted_override_is_recorded_in_run_manifest` | unit |
| Unrecognised env regression | `…::test_unrecognised_codex_sandbox_env_warns_and_returns_none` | regression |
| Malformed tier → dispatch default | `…::test_absent_or_malformed_agent_sandbox_defaults_to_dispatch` | unit |
| Snapshot not PR head (D1d/D16) | `…::test_agent_sandbox_policy_reads_base_snapshot_not_pr_head` | unit |
| No override request → refuse | `…::test_operator_override_requested_false_never_honours` | unit |
| Action fork invariant (D2b) | `tests/action/test_fork_credential_invariant.py` | unit |

Shared helpers: `tests/trust_credentials/support.py`.

Pinned API (W2): `mergecraft.config.trust_policy.resolve_agent_sandbox_decision`, `agent_sandbox_manifest_fields`; `mergecraft.action.inputs.validate_fork_credential_invariant`.

## W1.1b — CLI & config → W2

| Contract | Tests | Layer |
| --- | --- | --- |
| TrustSettings accepts `agentSandbox` | `tests/config/test_trust_agent_sandbox_settings.py::test_trust_settings_accepts_agent_sandbox` | unit |
| Rejects unknown trust keys | `…::test_trust_settings_rejects_unknown_trust_key` | unit |
| `trust show` resolved answer | `tests/cli/test_trust_agent_sandbox_cmd.py::test_trust_show_prints_configured_and_resolved_agent_sandbox` | E2E |
| `set-agent-sandbox` writes key | `…::test_set_agent_sandbox_writes_key` | E2E |
| same-repo confirmation | `…::test_set_agent_sandbox_same_repo_requires_confirmation` | E2E |
| Offline / no workflow edit | `…::test_set_agent_sandbox_is_offline_no_workflow_edit` | E2E |
| `init` scaffolds default + comment | `…::test_init_scaffolds_agent_sandbox_default_with_tier_comment` | E2E |
| Commented config refusal (`config_has_yaml_comments`) | `tests/config/test_config_io_comments.py` | unit |
| `set-agent-sandbox` refuses commented fixture | `tests/cli/test_trust_agent_sandbox_cmd.py::test_set_agent_sandbox_refuses_commented_config_and_leaves_file_intact` | E2E |
| `set-self-review` refuses commented fixture | `…::test_set_self_review_refuses_commented_config_and_leaves_file_intact` | E2E |

**W2 reconcile notes (2026-08-31):** `resolve_agent_sandbox_decision` stubs git fetch/merge-base for
`merged-only` by default (`simulate_merged_only_git=True`); the unfetched-default refuse test passes
`simulate_merged_only_git=False` and supplies its own failing probe. `test_init_scaffolds_*` mocks
`seed_builtin_providers` so scaffold comment preservation is asserted without provider-seed rewrite.

## W1.2 — Analyzer egress → W3

| Contract | Tests | Layer |
| --- | --- | --- |
| Untrusted + allowlist → isolate (D5) | `tests/analyzers/test_analyzer_egress_policy.py::test_untrusted_non_empty_allowlist_does_not_get_host_networking` | unit |
| Trusted unchanged (D7) | `…::test_trusted_tier_keeps_egress_for_allowlist_declaring_analyzer` | regression |
| Empty allowlist isolation | `…::test_empty_allowlist_still_isolates_network` | regression |
| Lane-D egress guard (D5a) | `…::test_lane_d_self_review_analyzers_prt_still_isolates_network` | unit |
| Skip ≠ unavailable (D6) | `…::test_untrusted_allowlist_skip_is_distinct_from_unavailable` | unit |
| Skip reason names hosts | `…::test_egress_skip_reason_names_analyzer_and_hosts` | unit |
| No silent allowlist discard | `…::test_build_analyzer_env_no_longer_discards_network_allowlist` | structural |
| Untrusted + filter → filtered (W3 Step 3) | `…::test_untrusted_with_filter_is_filtered_not_skipped` | unit |
| Filter keeps `--net` / named netns | `…::test_untrusted_with_filter_still_isolates_network`, `…::test_filtered_netns_wrap_drops_net_and_never_uses_host_net` | unit |
| Fork heads never get host net | `…::test_fork_head_never_drops_net_even_when_filter_available` | unit |
| Sandbox `none` still named-skips | `…::test_sandbox_none_named_skips_even_when_filter_available` | unit |
| CONNECT deny/allow | `tests/analyzers/test_filtered_egress.py` | unit |

Pinned API (W3): `build_analyzer_sandbox_argv_for_run`, `evaluate_analyzer_egress_policy`.

## W1.3 — Credential probe → W4

| Contract | Tests | Layer |
| --- | --- | --- |
| #552 singleton key | `tests/utils/test_credential_status_for_slug.py::test_nous_slug_true_with_only_singleton_custom_provider_key` | unit |
| Indexed gateway key | `…::test_nous_slug_true_with_indexed_custom_provider_key` | unit |
| Legacy NOUS_API_KEY + warning | `…::test_nous_slug_true_via_legacy_nous_api_key_with_once_warning` | unit |
| looked_for env vars (D10) | `…::test_no_credential_reports_looked_for_env_vars` | unit |
| source routes (D8) | `…::test_credential_status_reports_source_route` | unit |
| Other providers unchanged | `…::test_other_provider_branches_unchanged` | regression |
| Unwired ≠ missing (D9) | `…::test_unwired_provider_message_differs_from_missing_credential` | unit |
| p0 skip names fields (D10) | `tests/agents/test_credential_p0_skip.py::test_skipped_p0_names_agent_slot_provider_and_env_var` | unit |

Pinned API (W4): `mergecraft.utils.agent_resolve.credential_status_for_slug`, `format_credential_gap_message`, `build_missing_credential_degradation`.

## W1.4 — Logfire token → W5

| Contract | Tests | Layer |
| --- | --- | --- |
| INPUT → `_build_logfire_sink` (D11) | `tests/tracing/exporters/test_logfire_action_token_seam.py::test_input_logfire_token_reaches_build_logfire_sink` | integration |
| No input regression | `…::test_absent_input_keeps_logfire_no_op_warning_path` | regression |
| No clobber existing env | `…::test_empty_input_does_not_clobber_existing_mergecraft_logfire_token` | unit |
| Not in model context | `…::test_logfire_token_never_in_model_context_or_prompt_dump` | unit |
| Redacted in logs | `…::test_logfire_token_redacted_in_logs` | unit |
| Run summary warning (D12) | `tests/tracing/test_tracing_inactive_summary_warning.py::test_tracing_enabled_without_token_surfaces_run_summary_warning` | unit |

Pinned API (W5): `mergecraft.action.inputs.export_tracing_env_from_action_inputs`, `collect_tracing_warnings_for_summary`.

## W2b — Publication guard re-baseline → W2b Step 3

| Contract | Tests | Layer |
| --- | --- | --- |
| checkout_pr tree swap publishes (#582) | `tests/config/test_publication_guard_w2b.py::test_checkout_pr_tree_swap_publishes_normally` | unit |
| Post-rebaseline edit refuses | `…::test_config_edit_after_rebaseline_refuses` | unit |
| Absent config snapshot no fail-closed | `…::test_snapshot_without_config_file_does_not_fail_closed` | unit |
| Legitimate PR config edit publishes (#562) | `…::test_pr_config_edit_in_diff_publishes_with_pinned_settings` | unit |

Pinned API (W2b): `rebaseline_repo_settings_snapshot`, `assert_config_unchanged`, `repo_settings_from_context`.

## W1.5 — Entropy redaction → W6

| Contract | Tests | Layer |
| --- | --- | --- |
| Fixture sweep harness (D13) | `tests/analyzers/test_entropy_redaction_sweep.py::test_entropy_sweep_harness_records_redacted_tokens_with_context` | harness |
| Named benign shapes (D14) | `…::test_proven_benign_entropy_shapes_stay_unredacted_after_relaxation` | unit |
| Secrets stay redacted | `…::test_real_secret_shapes_remain_redacted_fail_closed` | regression |

## xfail reconciliation

| Wave | Marker reason prefix | Primary files | Status |
| --- | --- | --- | --- |
| W2 | `green after W2:` | `test_codex_sandbox_policy.py`, `test_fork_credential_invariant.py`, `test_trust_agent_sandbox_settings.py`, `test_trust_agent_sandbox_cmd.py` | **reconciled** — markers removed 2026-08-31 |
| W3 | `green after W3:` | `test_analyzer_egress_policy.py` | **reconciled** — fail-closed skip greened in W3; Step 3 filter path in `test_filtered_egress.py` |
| W4 | `green after W4:` | `test_credential_status_for_slug.py`, `test_credential_p0_skip.py` | **reconciled** — markers removed 2026-08-31 |
| W5 | `green after W5:` | `test_logfire_action_token_seam.py`, `test_tracing_inactive_summary_warning.py` | **reconciled** — markers removed 2026-08-31 |
| W6 | `green after W6:` | `test_entropy_redaction_sweep.py` (`classify_entropy_redaction_hits`) | **reconciled** — marker removed 2026-08-31 |

## W1 RED evidence

- 86 collected; 68 xfailed (`strict=True`); 18 passed (regression guards).

## Verification

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev"
env -u VIRTUAL_ENV make lint
env -u VIRTUAL_ENV make typecheck
env -u VIRTUAL_ENV uv run pytest --collect-only -q \
  tests/trust_credentials \
  tests/agents/test_codex_sandbox_policy.py \
  tests/agents/test_credential_p0_skip.py \
  tests/action/test_fork_credential_invariant.py \
  tests/config/test_trust_agent_sandbox_settings.py \
  tests/cli/test_trust_agent_sandbox_cmd.py \
  tests/analyzers/test_analyzer_egress_policy.py \
  tests/analyzers/test_entropy_redaction_sweep.py \
  tests/utils/test_credential_status_for_slug.py \
  tests/tracing/exporters/test_logfire_action_token_seam.py \
  tests/tracing/test_tracing_inactive_summary_warning.py \
  tests/config/test_publication_guard_w2b.py
```
