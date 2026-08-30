# Publication & attribution integrity — test plan

Wave plan: `.ignorelocal/waves/14-publication-attribution-wave-plan.md`
Worktree: `mergecraft-publication` @ `wave/publication-attribution`
Authoring wave: **W1** (`test-creator`). Implementation: **W2–W5**.

## Contract matrix

| Contract | Greening wave | Primary test(s) |
| --- | --- | --- |
| **W1.1** out-of-range 422 terminates (call count) | W2 | `test_publication_anchor_recovery.py::test_out_of_range_422_index_terminates_with_bounded_call_count` |
| **W1.1** out-of-range demotes all, no `comments` key (D3) | W2 | `…::test_out_of_range_422_demotes_all_inline_comments` |
| **W1.1** unparseable index demotes all (regression) | W2 | `…::test_unparseable_422_index_still_demotes_all_inline_comments` |
| **W1.1** unchanged payload hard-stops (D1) | W2 | `…::test_unchanged_payload_between_attempts_raises_instead_of_looping` |
| **W1.1** retry ceiling raises last 422 (D2) | W2 | `…::test_retry_ceiling_raises_last_http_status_error` |
| **W1.1** APPROVE→COMMENT fallback (regression) | W2 | `…::test_approve_comment_422_fallback_reports_approve_fallback` |
| **W1.1** non-422 propagates (regression) | W2 | `…::test_non_422_http_status_error_propagates_immediately` |
| **W1.2** body equals terminal submission kwargs (D4) | W3 | `test_publication_body_integrity.py::test_create_review_body_equals_terminal_submission_summary` |
| **W1.2** probe body guard raises (D4) | W3 | `…::test_probe_body_with_bound_terminal_submission_is_hard_failure` |
| **W1.2** #572 race → one review with findings (D5) | W3 | `…::test_572_race_replay_produces_one_review_with_real_findings` |
| **W1.2** second publish same commit skips (D5) | W3 | `…::test_second_publish_same_commit_posts_nothing_and_reports_existing_review` |
| **W1.2** demoted inline survives in body | W3 | `…::test_demoted_inline_comments_survive_in_final_review_body` |
| **W1.2** one terminal submission (D13) | W3 | `…::test_multi_reviewer_run_still_has_one_terminal_submission` |
| **W1.3** reviewer2 `raised_by` at terminal | W4 | `test_publication_raised_by.py::test_reviewer2_finding_arrives_with_raised_by_at_terminal_submission` |
| **W1.3** dual-reviewer list `raised_by` | W4 | `…::test_identical_finding_from_two_reviewers_lists_both_agents` |
| **W1.3** `unknown` never primary (D7) | W4 | `…::test_unknown_provenance_never_defaults_to_primary_reviewer` |
| **W1.3** agent `raised_by` rejected (D6) | W4 | `…::test_submit_review_verdict_schema_rejects_agent_supplied_raised_by` |
| **W1.3** `finding_key` ignores `raised_by` (D8) | W4 | `…::test_finding_key_ignores_raised_by_for_dedup` |
| **W1.3** verdict/severity unchanged (D8) | W4 | `…::test_verdict_and_severity_unaffected_by_raised_by` |
| **W1.3** inline placement unchanged (D8) | W4 | `…::test_inline_placement_unaffected_by_raised_by` |
| **W1.4** over target warns once (D9) | W5 | `test_publication_budget_band.py::test_crossing_target_under_ceiling_warns_once_without_raise` |
| **W1.4** warning once only (D9) | W5 | `…::test_over_target_warning_emitted_only_once` |
| **W1.4** ceiling message names band (D9) | W5 | `…::test_crossing_ceiling_raises_with_target_ceiling_and_tolerance` |
| **W1.4** tolerance 0 strict `>` (regression) | W5 | `…::test_zero_tolerance_restores_strict_greater_than_target` |
| **W1.4** increment vs drift messages (D10) | W5 | `…::test_single_increment_over_ceiling_has_distinct_message_from_steady_drift` |
| **W1.4** `unattributed` default phase (D11) | W5 | `…::test_record_tokens_without_phase_attributes_to_unattributed` |
| **W1.4** phase totals reconcile (D11) | W5 | `…::test_per_phase_totals_sum_to_tokens_used` |
| **W1.4** `record_cost` untouched (D11) | W5 | `…::test_record_cost_path_is_untouched_by_token_band_changes` |

## Deliverable symbols

| Symbol | Module | Test anchor |
| --- | --- | --- |
| `_create_github_review_with_anchor_recovery` | `mcp/review.py` | `test_publication_anchor_recovery.py` |
| `_payload_signature` / retry ceiling | `mcp/review.py` | `test_publication_anchor_recovery.py` |
| `_publish_github_review` body guard | `mcp/review.py` | `test_publication_body_integrity.py` |
| publication idempotency key | `mcp/review.py` / `tool_state` | `test_publication_body_integrity.py` |
| `_group_findings_by_reviewer` unknown bucket | `review/terminal_submission.py` | `test_publication_raised_by.py` |
| server-side `raised_by` stamp | dispatch/merge path (W4) | `test_publication_raised_by.py` |
| `token_budget_tolerance` / `token_ceiling` | `utils/run_bounds.py` | `test_publication_budget_band.py` |
| `record_tokens(..., phase=)` | `utils/run_bounds.py` | `test_publication_budget_band.py` |

## Shared helpers

`tests/publication_attribution/support.py` — contexts, GitHub stubs, xfail markers, #572 probe strings.

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| W2 | `tests/mcp/test_publication_anchor_recovery.py` (4 tests) |
| W3 | `tests/mcp/test_publication_body_integrity.py` (4 tests) |
| W4 | `tests/review/test_publication_raised_by.py` (3 tests) |
| W5 | `tests/utils/test_publication_budget_band.py` (7 tests) |

## Verification

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev"
env -u VIRTUAL_ENV make lint
env -u VIRTUAL_ENV make typecheck
env -u VIRTUAL_ENV uv run pytest --collect-only -q \
  tests/mcp/test_publication_anchor_recovery.py \
  tests/mcp/test_publication_body_integrity.py \
  tests/review/test_publication_raised_by.py \
  tests/utils/test_publication_budget_band.py
```

## W1 RED evidence

- 29 collected; 18 xfailed; 11 passed (regression guards including demoted-inline survival).
