# Review record integrity — test plan (W1 RED suite)

Wave plan: `.ignorelocal/waves/12-review-record-integrity-wave-plan.md`
Worktree: `mergecraft-review-record` @ `wave/review-record`
Authoring wave: **W1** (`test-creator`). Implementation: **W2–W8**.

## Contract matrix

| Contract | Greening wave | Primary test(s) |
|----------|---------------|-------------------|
| **W1.1** `Finding.scope` default `change` | W2 | `test_w11_scope_blocking.py::test_finding_defaults_scope_change` |
| **W1.1** `source="trajectory"` validates | W2 | `test_w11_scope_blocking.py::test_trajectory_source_validates` |
| **W1.1** `blocking_findings` drops `scope="run"` | W2 | `test_w11_scope_blocking.py::test_blocking_findings_drops_run_scoped_critical` |
| **W1.1** causality before block test | W2 | `test_w11_scope_blocking.py::test_blocking_findings_applies_causality_policy` |
| **W1.1** one blocking predicate (#447) | W2 | `test_w11_scope_blocking.py::test_has_blocker_and_blocks_approve_agree_on_mixed_scope_set` |
| **W1.1** run-only → `success` | W2 | `test_w11_scope_blocking.py::test_decide_approval_success_on_run_only_findings` |
| **W1.2** trajectory stamp table | W2 | `test_w12_trajectory_attribution.py::test_every_trajectory_check_stamps_scope_source_and_introduced_by_pr` |
| **W1.2** trajectory-only approval success | W2 | `test_w12_trajectory_attribution.py::test_trajectory_only_run_produces_approval_success` |
| **W1.2** `unresolved-failure` advisory | W2 | `test_w12_trajectory_attribution.py::test_unresolved_failure_critical_does_not_block` |
| **W1.3** schema self-correct | W3 | `test_w13_trajectory_classify.py::test_schema_rejection_self_corrected_within_three_calls_produces_no_finding` |
| **W1.3** guard refusal trivial | W3 | `test_w13_trajectory_classify.py::test_guard_refusal_produces_at_most_trivial_run_scoped_observation` |
| **W1.3** bubblewrap rollup | W3 | `test_w13_trajectory_classify.py::test_bubblewrap_namespace_failure_produces_one_rolled_up_environment_finding` |
| **W1.3** git_fetch retry intent | W3 | `test_w13_trajectory_classify.py::test_git_fetch_after_checkout_pr_counts_as_retry_not_ignored_error` |
| **W1.3** transient ignored-tool-error | W3 | `test_w13_trajectory_classify.py::test_transient_failure_without_retry_fires_ignored_tool_error` |
| **W1.3** immutable git show not a loop | W3 | `test_w13_trajectory_classify.py::test_repeated_tool_loop_does_not_fire_on_immutable_git_show_with_intervening_work` |
| **W1.3** adjacent `run_static_checks` loop | W3 | `test_w13_trajectory_classify.py::test_repeated_tool_loop_fires_on_three_adjacent_identical_run_static_checks` |
| **W1.3** run 33126460925 fixture | W3 | `test_w13_trajectory_classify.py::test_run_33126460925_fixture_zero_blocking_at_most_three_run_scoped` |
| **W1.4** no false “outstanding feedback” | W4 | `test_w14_status_check_summaries.py::test_zero_change_findings_never_claim_outstanding_feedback` |
| **W1.4** three summary variants | W4 | `test_w14_status_check_summaries.py::test_three_distinct_summaries_for_outcomes` |
| **W1.4** run URL + reviewed SHA | W4 | `test_w14_status_check_summaries.py::test_every_summary_carries_run_url_and_reviewed_sha` |
| **W1.4** failure → warning + `::warning::` | W4 | `test_w14_status_check_summaries.py::test_failed_check_run_post_emits_warning_and_annotation` |
| **W1.4** success → one INFO line / check | W4 | `test_w14_status_check_summaries.py::test_successful_post_emits_one_info_line_per_check` |
| **W1.4** post failure non-fatal | W4 | `test_w14_status_check_summaries.py::test_post_failure_does_not_raise_into_run_outcome` |
| **W1.5** sticky on every verdict path | W5 | `test_w15_deterministic_record.py::test_deterministic_record_posts_on_every_resolved_pr` |
| **W1.5** zero-finding approve still posts | W5 | `test_w15_deterministic_record.py::test_agent_approved_zero_findings_still_posts_deterministic_record` |
| **W1.5** idempotent sticky | W5 | `test_w15_deterministic_record.py::test_two_runs_edit_one_sticky_comment_in_place` |
| **W1.5** mandatory preamble | W5 | `test_w15_deterministic_record.py::test_review_body_contains_preamble_when_agent_body_empty` |
| **W1.5** agent cannot suppress preamble | W5 | `test_w15_deterministic_record.py::test_agent_cannot_suppress_preamble_by_duplicating_markers` |
| **W1.5** packet-row findings in preamble | W5 | `test_w15_deterministic_record.py::test_preamble_renders_packet_critical_not_agent_narrative` |
| **W1.5** run-scoped collapsed heading | W5 | `test_w15_deterministic_record.py::test_run_scoped_findings_render_under_collapsed_heading` |
| **W1.6** anchor pre-validation | W6 | `test_w16_anchor_422_recovery.py::test_out_of_diff_inline_comment_is_dropped_before_post` |
| **W1.6** REQUEST_CHANGES 422 swallowed | W6 | `test_w16_anchor_422_recovery.py::test_request_changes_422_does_not_propagate_to_agent` |
| **W1.6** verdict survives all anchor failures | W6 | `test_w16_anchor_422_recovery.py::test_all_anchors_rejected_still_posts_body_and_verdict` |
| **W1.6** APPROVE→COMMENT 422 preserved | W6 | `test_w16_anchor_422_recovery.py::test_approve_comment_422_fallback_still_works` |
| **W1.7** `run_health` + schema bump | W7 | `test_w17_packet_artifact_summary.py::test_packet_run_health_round_trips_and_schema_version_bumps` |
| **W1.7** step summary all outcomes | W7 | `test_w17_packet_artifact_summary.py::test_step_summary_written_on_success_failure_and_no_verdict` |
| **W1.7** 1 MiB cap | W7 | `test_w17_packet_artifact_summary.py::test_step_summary_truncates_findings_not_header` |
| **W1.7** `evidence_packet` output | W7 | `test_w17_packet_artifact_summary.py::test_evidence_packet_output_nonempty_for_pr_run` |
| **W1.7** workflow artifact via `env:` | W7 | `test_w17_packet_artifact_summary.py::test_mergecraft_workflow_persists_packet_via_env_not_inline_interpolation` |
| **W1.8** `action-pin-check` in `ci-static` | W8 | `test_w18_action_pin_gate.py::test_make_ci_static_invokes_action_pin_check` |
| **W1.8** `ci.yml` non-zero on stale pin | W8 | `test_w18_action_pin_gate.py::test_ci_yml_fails_on_stale_pin_instead_of_warning_only` |
| **W1.8** single pin, three rungs | W8 | `test_w18_action_pin_gate.py::test_mergecraft_workflow_three_rungs_share_one_pin_value` |
| **W1.8** partial bump fails | W8 | `test_w18_action_pin_gate.py::test_partial_pin_bump_fails_action_pin_check` |
| **W8 / #535** digest guard script | W8 | `test_action_image_digest_check.py` (pre-tracing case stubs workflow SHA when current pin lacks GHCR tag) |
| **W8 / #535** digest pin in `action.yml` | W8 | `test_action_image_digest_sync.py`, `test_action_yml_contract.py::test_docker_action_pulls_digest_pinned_slim_image` |
| **W8 / #535** `action-image-digest-check` in `make lint` | W8 | `test_action_image_digest_sync.py::test_action_image_digest_check_runs_via_make_lint` |
| **W2** `Finding.scope` on CI evidence path | W2 | `test_evidence.py::test_no_new_finding_fields_introduced` |

## Deliverable symbols

| Symbol | Module (planned) | Test anchor |
|--------|----------------|-------------|
| `FindingScope` | `review_taxonomy.py` | `test_w11_scope_blocking.py` |
| `Finding.scope` | `analyzers/finding.py` | `test_w11_scope_blocking.py` |
| `blocking_findings` | `agents/gates.py` | `test_w11_scope_blocking.py`, `test_w12_trajectory_attribution.py`, `test_w13_trajectory_classify.py` |
| `TRAJECTORY_CHECKS` stamps | `evidence/trajectory_audit.py` | `test_w12_trajectory_attribution.py` |
| `failure_class` | `evidence/trajectory.py` | `test_w13_trajectory_classify.py` (via auditor behaviour) |
| `render_deterministic_review_block` | `findings/ledger.py` | `test_w15_deterministic_record.py` |
| `merge_deterministic_preamble_into_review_body` | `mcp/review.py` | `test_w15_deterministic_record.py` |
| `publish_deterministic_record` | `main.py` | `test_w15_deterministic_record.py` |
| anchor pre-validation | `mcp/review.py` / `convergence_runtime.py` | `test_w16_anchor_422_recovery.py` |
| `run_health` | `evidence/packet.py` | `test_w17_packet_artifact_summary.py` |
| `render_step_summary` / `append_step_summary` | `utils/step_summary.py` | `test_w17_packet_artifact_summary.py` |
| workflow packet `env:` artifact steps | `.github/workflows/mergecraft.yml` | `test_w17_packet_artifact_summary.py` |
| `action-pin-check` in `ci-static` / `CI_STEPS` | `Makefile` | `test_w18_action_pin_gate.py` |
| `action-image-digest-check` / `check_action_image_digest.py` | `scripts/`, `Makefile` | `test_action_image_digest_check.py`, `test_action_image_digest_sync.py` |

## Fixtures

| Fixture | Path |
|---------|------|
| Run 33126460925 trajectory replay | `tests/review_record/fixtures/run_33126460925_trajectory.json` |

## Verification

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev"
make lint && make typecheck
uv run pytest --collect-only -q tests/review_record
uv run pytest tests/review_record -q
```

Expect RED: failures/errors dominate; W3-marked cases xfail; `test_approve_comment_422_fallback_still_works` passes today (regression pin).
