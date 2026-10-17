# Test plan — what the run says it did

**Owner:** `test-creator` · **Branch:** `wave/review-run-correctness` · **Base:** `origin/main` @ `fe0eb61d`

Each item below is a place where a run reached a verdict, posted, swept or skipped work
while the record said something else. This document maps each issue's contract to the
tests that pin it. The suite is written first, against the contracts in the issues, and
is red until the implementation lands: every new test fails for the behaviour it names,
and every regression guard is green from the start.

Rule the suite enforces throughout: **no item may make a run look more complete than it
was.** Where a fix has to choose between succeeding quietly and saying what was missing,
it says what was missing.

Verification commands:

```bash
uv run --extra dev pytest <paths> -q -n8     # every contract passes
make lint && make typecheck
```

## #902 — review-thread retrieval pages through GitHub's connections

Contract: page `reviewThreads` and each thread's `comments` with `pageInfo` up to a named
cap (10 pages of 100); when the cap is hit return an explicit `incomplete`, never truncate
silently; an unfetched or half-fetched thread is never auto-resolved.

| Test | Acceptance bullet |
| --- | --- |
| `tests/findings/test_thread_pagination.py::test_more_than_one_page_of_threads_are_all_returned` | more than 100 threads across two pages are all returned |
| `…::test_a_thread_with_more_than_one_page_of_comments_is_read_in_full` | a thread with more than 100 comments paginates |
| `…::test_hitting_the_thread_page_cap_reports_incomplete_and_warns` | cap hit → `incomplete` and a warning |
| `…::test_a_thread_whose_comments_hit_the_cap_is_marked_truncated_and_page_incomplete` | comment cap hit → thread flagged, page incomplete |
| `…::test_resolved_threads_are_still_filtered_across_pages` | resolved filtering still applies on every page |
| `…::test_the_old_truncated_name_still_reads_the_same_signal` | callers reading `truncated` keep working |
| `…::test_get_review_comments_tool_reports_incomplete_only_when_the_cap_was_hit` | the agent-facing tool carries `incomplete` |
| `…::test_a_thread_whose_comments_were_not_all_read_is_never_resolved` | fail-safe: unread comments → never auto-resolved |

## #903 — a post-run finalize failure is visible

Contract: log at `warning` with the exception type, carry `finalize_failed: <Type>` into
the run record, and still fail closed (`inconclusive` for a Review run).

| Test | Acceptance bullet |
| --- | --- |
| `tests/review/test_finalize_failure_visible.py::test_finalize_failure_logs_a_warning_naming_the_exception_type` | warning names the type |
| `…::test_finalize_failure_still_fails_closed_and_names_itself_as_the_reason` | outcome unchanged; reason is specific |
| `…::test_the_published_run_record_names_the_finalize_failure` | the posted record names the failure |
| `…::test_a_finalize_that_succeeds_logs_no_finalize_warning_and_keeps_its_outcome` | green guard: success path unchanged |

## #904 — IncrementalReview names no tool the session refuses

Contract: drop the reply/resolve instruction and say the run retires addressed threads
itself; define "mergeCraft-originated" by the expected-publisher rule. The refused set is
derived from the live guard, so a later allowlist change keeps the test honest.

| Test | Acceptance bullet |
| --- | --- |
| `tests/modes/test_incremental_review_tool_contract.py::test_incremental_review_names_no_tool_the_review_session_refuses` | prompt-contract test over both agent spellings |
| `…::test_the_refused_set_includes_the_thread_tools_the_prompt_used_to_call` | the derived set is not vacuous |
| `…::test_incremental_review_says_the_run_retires_addressed_threads_itself` | the replacement statement is present |
| `…::test_mergecraft_originated_matches_the_expected_publisher_rule` | no `author=mergecraft[bot]` definition |
| `tests/test_modes.py::test_mode_prompt_text_is_byte_identical_after_split`, `tests/prompts/test_terminal_protocol_prompt.py::test_no_other_prompt_content_changed` | snapshot pins updated to the new step text |

## #905 — carry-over authorship

Contract: a root comment is mergeCraft's only through marker **and** an expected-publisher
author; `github-actions[bot]` never counts; an empty set trusts nothing; replies are
classified by author, not by body.

| Test | Acceptance bullet |
| --- | --- |
| `tests/findings/test_select_authorship.py::test_a_user_who_copies_the_marker_does_not_get_a_thread_swept` | forged marker by a user → not swept |
| `…::test_marker_plus_an_expected_publisher_is_swept` | marker + publisher → swept |
| `…::test_an_empty_publisher_set_sweeps_nothing` | empty set → nothing swept |
| `…::test_the_shared_actions_login_never_counts_even_when_passed` | shared login never a publisher |
| `…::test_a_publisher_comment_without_a_marker_is_not_a_finding` | marker is still required on the root |
| `…::test_author_match_is_case_insensitive` | login comparison |
| `…::test_a_mergecraft_reply_without_a_marker_is_not_a_human_answer` | reply classification, one way |
| `…::test_a_human_reply_carrying_a_copied_marker_still_answers_the_thread` | reply classification, the other way |
| `…::test_a_reply_with_no_named_author_is_treated_as_a_human_answer` | unattributable reply is a human answer |
| `tests/findings/test_sweep_publishers.py` (6 tests) | the sweep derives the publisher set (configured App, approval-check app slug), refuses the shared login, and says why when it has none |

## #914 — the learnings-migration read follows the publisher rule

Contract: run-bound comment id, then the expected-publisher set, never a bare bot-type
match; with an empty set skip the read, log at `info`, and record it.

| Test | Acceptance bullet |
| --- | --- |
| `tests/review_record/test_migration_sticky_read.py::test_a_comment_by_an_unexpected_bot_is_not_adopted` | unexpected bot not adopted, not retired |
| `…::test_a_comment_by_the_expected_publisher_is_adopted_and_retired` | expected publisher adopted |
| `…::test_an_empty_publisher_set_skips_the_read_and_the_record_says_so` | empty set → skipped with a named reason in the log and the record |
| `…::test_the_run_bound_comment_id_selects_when_no_publisher_identity_resolves` | run-bound id still selects |
| `…::test_no_legacy_comment_leaves_the_record_without_a_skip_note` | no false note when nothing was skipped |

## #926 — run-bound identity accepts runs that requested changes

Contract: completed runs with conclusion `success` or `failure` that carry an evidence
artefact naming `reviewed_head_sha`; keep rejecting `cancelled`, `skipped`, in-progress
and artefact-less runs, other events, other workflows and other PRs; stay fail-closed.

| Test | Acceptance bullet |
| --- | --- |
| `tests/mcp/test_checkout_run_bound_failure_runs.py::test_a_failure_run_with_an_artefact_yields_a_checkpoint` | `failure` + artefact → checkpoint |
| `…::test_a_newer_failure_run_outranks_an_older_success_run` | the re-review loop reads the newest run |
| `…::test_runs_that_did_not_complete_a_review_are_ignored` | `cancelled`, `skipped`, `timed_out`, `neutral`, in progress → none |
| `…::test_a_failure_run_from_another_event_or_pr_is_still_ignored` | event and PR conditions kept |
| `…::test_runs_are_read_only_through_the_trusted_workflow` | workflow condition kept |
| `…::test_a_newer_failure_run_without_an_artefact_falls_back_to_the_older_run` | artefact-less run is not a round |
| `…::test_a_failure_run_whose_packet_names_no_head_is_not_a_checkpoint` | no `reviewed_head_sha` → not a checkpoint |
| `…::test_only_artefactless_failure_runs_stay_fail_closed` | fail-closed fallback kept |
| `…::test_the_search_for_a_usable_run_is_bounded_and_says_so` | the scan is bounded and warns |
| `tests/mcp/test_checkout_run_bound_checkpoint.py` (existing) | `cancelled` replaces `failure` in the ignored-runs cases |

## #940 — changed-line coverage invariant

Contract (acceptance bullets of the issue, one row each):

| Acceptance bullet | Tests |
| --- | --- |
| a run whose files-API diff hits the page cap ends `inconclusive`; `coverage.uncovered` lists `diff_truncated` | `tests/mcp/test_checkout_coverage.py::test_a_files_api_diff_over_the_page_cap_is_recorded_as_truncated`; `tests/evidence/test_packet_coverage.py::test_the_run_packet_records_a_truncated_files_listing`; `tests/review/test_coverage_gate_finalize.py::test_an_undelivered_hunk_makes_a_submitted_verdict_inconclusive` |
| a file with line changes and no inline patch is listed `no_inline_patch` and makes the run `inconclusive` | `tests/mcp/test_checkout_coverage.py::test_a_file_with_line_changes_and_no_patch_is_recorded_as_unreviewable`; `tests/evidence/test_coverage_accounting.py::test_a_file_with_no_inline_patch_is_listed_and_never_cleared`; `tests/evidence/test_packet_coverage.py::test_the_run_packet_records_files_the_api_sent_no_patch_for` |
| a verdict submitted without a hunk's lines ever being delivered ends `inconclusive`, not `success` | `tests/review/test_coverage_gate_finalize.py::test_an_undelivered_hunk_makes_a_submitted_verdict_inconclusive`; `tests/evidence/test_coverage_accounting.py::test_a_hunk_missing_from_the_delivered_diff_is_uncovered_not_unknown` |
| generated hunks removed by policy appear as `excluded_generated` and do not by themselves make the run `inconclusive` | `tests/evidence/test_coverage_accounting.py::test_a_generated_hunk_removed_by_policy_is_listed_but_does_not_make_the_run_incomplete`; `…::test_a_delivered_generated_hunk_is_simply_covered` |
| the bounded follow-up fires at most once; if it covers the remaining hunks the run completes normally | `tests/review/test_coverage_followup.py` (8 tests: exactly the uncovered hunks, covered afterwards, at most once, no gap → none, no budget → none and `budget_exhausted`, unseen files not followed up, verdict replaceable only inside the window) |
| a Critical/Major finding still produces `failure` when coverage is incomplete | `tests/evidence/test_coverage_accounting.py::test_a_blocker_still_wins_over_incomplete_coverage`; `tests/review/test_coverage_gate_finalize.py::test_a_blocker_on_an_incomplete_run_still_fails_the_approval_check` |
| `coverage` is in the packet JSON Schema, the version gets a minor bump, the pin test is updated | `tests/evidence/test_packet_coverage.py::test_the_schema_version_is_bumped_by_a_minor_for_the_coverage_section`, `…::test_coverage_is_in_the_packet_json_schema_with_every_field`, `…::test_an_uncovered_row_names_path_range_and_cause`, `…::test_coverage_round_trips_through_json`, `…::test_a_packet_without_coverage_still_validates` |
| the `mergecraft-approval` summary shows hunk coverage and the uncovered ranges | `tests/evidence/test_coverage_accounting.py::test_summary_line_*` (4 tests); `tests/review/test_coverage_gate_finalize.py::test_the_recorded_packet_says_what_was_uncovered` |
| documented in `docs/evidence-packet.md`, `REVIEW-CHECKS.md`, `docs/REVIEW-DOCTRINE.md` | checked by hand at review; the packet doc's stale version line is fixed in the same pass |

Unit rows from the issue: coverage universe from `parse_diff_scope` (renames, deleted-only
hunks, binary headers, no newline at EOF) — `test_universe_*` (6 tests); coverage
accounting (delivered minus unreviewable/truncated, plus mediated reads) —
`test_a_fully_delivered_diff_is_complete`, `test_a_mediated_read_of_the_file_covers_its_hunks`,
`test_a_follow_up_turn_covers_exactly_the_hunks_it_handed_back`, `test_budget_exhaustion_is_named_*`;
outcome mapping (incomplete → `inconclusive`, complete unchanged, agent failure not masked) —
`test_an_incomplete_coverage_reason_*`, `test_a_complete_run_is_unchanged`,
`test_coverage_does_not_mask_an_agent_failure`; the knob (`review.coverage.onIncomplete`,
default `inconclusive`, read from the pinned snapshot) — `test_the_default_policy_is_inconclusive`,
`test_the_yaml_spelling_*`, `test_an_unknown_policy_value_is_rejected`,
`test_the_gate_reason_follows_the_pinned_policy`,
`tests/evidence/test_packet_coverage.py::test_the_policy_is_read_from_the_pinned_settings_snapshot`.

## #890 — deterministic triage tier

Contract: pure recognizers over the unified diff (pin substitution, prose-only,
whitespace-only, generated/lockfile regeneration), tiers `skip` / `full`, a gate at the
`agent-dispatch` seam, config `review.fastPath` read from the operator's base config only.
`skip` never grants `mergecraft-approval`. `lite` is not shipped (see the follow-up
issue linked from the pull request); the suite pins `skip`/`full` only.

| Acceptance bullet | Tests |
| --- | --- |
| replaying the pin-bump PR yields `skip (pinBump)` and zero LLM calls; the record states the tier and the check it relied on | `tests/review/test_fast_path_replay.py::test_a_verified_pin_bump_never_reaches_the_dispatcher`, `…::test_the_completion_check_states_the_tier_and_approval_is_not_granted`; `tests/classify/test_triage_tier.py::test_a_verified_pin_bump_is_skip_and_names_the_check_it_relied_on`, `…::test_the_run_record_line_states_the_tier`; `tests/classify/test_triage_recognizers.py::test_replay_of_the_pin_bump_pr_shape_is_a_pin_bump` |
| one `with:` input changed beside the SHA → `full` | `test_one_with_input_edited_beside_the_sha_is_not_a_pin_bump`; `tests/classify/test_triage_tier.py::test_one_with_input_changed_beside_the_sha_swap_is_full` |
| a different old→new pair on one line → `full` | `test_a_different_old_new_pair_on_one_line_is_not_a_pin_bump` |
| every recognizer has positive and adversarial cases (a semantic one-liner hidden in whitespace, a code block inside a `.md`, a lockfile changed with its manifest) | `tests/classify/test_triage_recognizers.py` (pin bump 12, prose 9, whitespace 9, generated 6 tests): `test_a_semantic_change_hidden_beside_whitespace_noise_is_not_whitespace_only`, `test_a_changed_line_inside_a_code_fence_is_not_prose`, `test_a_lockfile_changed_with_its_manifest_is_not_generated` |
| `fastPath.enabled: false` and missing config reproduce today's behaviour | `tests/classify/test_triage_tier.py::test_the_fast_path_is_off_by_default`, `…::test_missing_config_reproduces_todays_behaviour_for_every_diff`; `tests/review/test_fast_path_replay.py::test_fast_path_disabled_runs_the_agent_exactly_as_before`, `…::test_default_settings_run_the_agent`; `tests/review/test_fast_path_gate.py::test_a_disabled_fast_path_makes_no_request_at_all` |
| the tier appears in the evidence packet and the shadow record | `tests/review/test_fast_path_replay.py::test_the_tier_is_recorded_on_the_packet`, `…::test_the_shadow_record_carries_the_tier`, `…::test_a_skipped_run_writes_a_triage_row_beside_the_packet` |
| PR title, body, labels and head-side config can never select a tier | `tests/classify/test_triage_tier.py::test_no_pull_request_authored_field_is_an_input`; `tests/review/test_fast_path_replay.py::test_the_pull_request_title_body_and_labels_cannot_select_a_tier`; `tests/review/test_fast_path_gate.py::test_config_that_is_not_the_operators_base_side_config_is_ignored` |
| the gate only ever spends less when certain | `tests/review/test_fast_path_gate.py` (read failures, unreadable head text, truncation, files with no patch, an unpassed verifier → `full`) |
| `lite` respects its token cap | **not shipped** — tracked in a follow-up issue; no test pins a tier that does not exist |
