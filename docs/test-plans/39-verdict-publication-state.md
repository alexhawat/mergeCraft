# Test plan — what GitHub shows and what the run recorded

**Owner:** `test-creator` · **Branch:** `wave/verdict-publication-state` · **Base:** `origin/main` @ `d1ccaa95`

This document maps each contract of the review-state work to the tests that pin
it. The suite was written first, against the locked contracts, before any
implementation: every test that needed new behaviour carried a non-strict
`xfail` naming the implementation step that would green it, and every
regression guard was green from the start. Each implementation step was
followed by removing exactly the markers it satisfied.

**Status:** every contract below has landed except the five rows under
*The run record belongs to the final attempt*, added after the verification
gate and still red. No assertion was weakened or dropped to reach green.
Two notes from the lifting passes:

* Line overlap for thread retirement is matched against the new (RIGHT-side)
  hunk ranges; a thread whose anchor moved off the new side qualifies through
  GitHub's outdated flag, which is what the outdated-thread tests pin.
* One check was tightened rather than loosened: the
  `create_pull_request_review` variant of the different-verdict test parses the
  tool's JSON response instead of matching a `"skipped": true` substring, so any
  success-plus-skip answer fails it.

Verification commands:

```bash
MERGECRAFT_PYTEST_JOBS=0 uv run pytest <paths> --collect-only -q   # collection diagnostic
MERGECRAFT_PYTEST_JOBS=0 uv run pytest <paths> -q                  # red = xfailed, guards pass
MERGECRAFT_PYTEST_JOBS=0 uv run pytest <paths> --runxfail -q       # see the real reds
make lint && make typecheck
```

## Names this suite pins

The contracts left a few names open; the suite fixes them so the
implementation has one target.

| Surface | Name | Shape |
| --- | --- | --- |
| Receipt | `ReviewRecord.verdict`, `ReviewRecord.payload_hash` | both default `None`; a three-argument `ReviewRecord(id, node_id, reviewed_sha)` still constructs |
| Receipt hash | `payload_hash` | `sha256(verdict + "\n" + "\n".join(sorted(fingerprints)))`, fingerprints read from the `mergecraft-finding:v1` markers in the published inline comments and body |
| Mismatch flag | `ToolState.terminal_publication_mismatch` | `bool`, default `False` |
| Incomplete inline set | `ToolState.publication_incomplete`; publish response key `publicationIncomplete` | sorted list of submission fingerprints missing from GitHub's inline view |
| Classifier inputs | `_classify_outcome(..., terminal_publication_receipt=None, terminal_publication_mismatch=None)` | receipt: `None` not applicable, `True`/`False`; mismatch: `None` or `(published_verdict, recorded_verdict)` |
| Shadow predictor | `predict_verdict_protocol(...)` and `_verdict_protocol_publish(...)` | accept the same two inputs and agree with the classifier |
| Trajectory step | synthetic tool call `orchestrator.publish_review` | intent `complete`, `ok` = a receipt is present |
| Thread retirement | `resolvable_thread_ids(threads, *, current_fingerprints, changed_lines, publishers)` | `changed_lines: {path: [range, ...]}`; `publishers: frozenset[str]` |
| Listings | `incomplete` key on `get_issue_comments` / `list_pull_request_reviews` | `true` only when the page cap cut the listing |
| Closing issues | `closingIssuesUnavailable` key on `get_pull_request` | `true` only when the lookup failed |
| Test helper | `tests.support.tool_context.make_tool_context(tmp_path, *, trust_tier, ...)` | `trust_tier` is required, keyword-only, no default |

## Contract → test map

### The run publishes the recorded verdict

| Contract | Layer | Test | Status |
| --- | --- | --- | --- |
| A recorded verdict with no agent publish is published exactly once by Phase 4 | functional | `tests/review/test_publication_split.py::test_orchestrator_publishes_a_recorded_verdict_exactly_once` | green |
| The published inline comments are exactly the submission's findings | functional | `tests/review/test_publication_split.py::test_orchestrator_publication_carries_the_submission_findings_inline` | green |
| With nothing pending, the internal publisher builds inline comments from the findings | unit | `tests/review/test_publication_split.py::test_publisher_fallback_builds_inline_comments_from_submission_findings` | green |
| An approve with no findings posts no inline comments | unit | `tests/review/test_publication_split.py::test_publisher_fallback_for_an_approve_posts_no_inline_comments` | green (guard) |
| Shadow mode never publishes from Phase 4 | functional | `tests/review/test_publication_split.py::test_orchestrator_does_not_publish_in_shadow_mode` | green (guard) |
| A matching agent-published receipt gets no second POST | functional | `tests/review/test_publication_split.py::test_orchestrator_does_not_republish_over_a_matching_receipt` | green (guard) |
| A submission finalize rejected (stale attempt) is never published | functional | `tests/review/test_publication_split.py::test_orchestrator_does_not_publish_a_submission_finalize_rejected` | green (guard) |
| A progress-only IncrementalReview posts no review | functional | `tests/review/test_publication_split.py::test_orchestrator_does_not_publish_an_incremental_progress_only_run` | green (guard) |
| A refused Phase-4 POST is inconclusive with the publication-failure reason, and does not escape | functional | `tests/review/test_publication_split.py::test_orchestrator_publication_failure_is_inconclusive` | green |
| `submit_review_verdict` says the run publishes; it no longer points at `create_pull_request_review` | unit | `tests/review/test_publication_split.py::test_submit_review_verdict_description_says_the_run_publishes` | green |
| A received submission with no receipt is inconclusive with its own reason (both review modes) | unit | `tests/review/test_terminal_publication_outcome_619.py::test_recorded_verdict_without_a_receipt_is_inconclusive_with_its_own_reason` | green |
| A receipt passes; shadow and non-review modes ignore a missing receipt | unit | `tests/review/test_terminal_publication_outcome_619.py::test_recorded_verdict_with_a_receipt_passes`, `::test_missing_receipt_is_ignored_in_shadow_mode`, `::test_missing_receipt_is_ignored_outside_review_modes` | green |
| Reason ordering: a failed POST and a missing submission keep their own reasons | unit | `tests/review/test_terminal_publication_outcome_619.py::test_publication_failure_keeps_its_own_reason_over_a_missing_receipt`, `::test_no_submission_keeps_the_missing_verdict_reason` | green |
| Offline classification is unchanged | unit | `tests/review/test_terminal_publication_outcome_619.py::test_offline_classification_is_unchanged` | green (guard) |
| The shadow predictor agrees with the new outcomes | unit | `tests/review/test_terminal_publication_outcome_619.py::test_shadow_prediction_agrees_with_the_new_publication_outcomes`, `tests/evidence/test_verdict_shadow.py::test_verdict_protocol_publish_carries_the_publication_inputs` | green |
| Predictor defaults keep today's prediction | unit | `tests/evidence/test_verdict_shadow.py::test_predictor_default_publication_inputs_keep_a_received_verdict_approved` | green (guard) |
| The publisher failing before any POST still reads inconclusive, naming publication | functional | `tests/test_run_outcome.py::test_recorded_verdict_the_run_could_not_publish_is_not_passed` | green |

### The receipt is bound to the verdict it published

| Contract | Layer | Test | Status |
| --- | --- | --- | --- |
| A receipt built from three fields states no verdict and no hash | unit | `tests/review/test_attempt_attribution.py::test_review_record_new_fields_default_to_none` | green |
| The stored receipt names the verdict and hashes the published markers | integration | `tests/review/test_attempt_attribution.py::test_receipt_binds_verdict_and_finding_fingerprints` | green |
| A different verdict on the same head: no second POST, no skip-as-success, mismatch flag set — for each of the three entrypoints | integration | `tests/review/test_attempt_attribution.py::test_a_different_verdict_on_the_same_head_is_never_skipped_as_success` (parametrized) | green |
| The mismatch reads inconclusive naming both verdicts, end to end through Phase 4 | functional | `tests/review/test_attempt_attribution.py::test_a_different_verdict_reads_inconclusive_naming_both_verdicts`; `tests/review/test_terminal_publication_outcome_619.py::test_verdict_mismatch_is_inconclusive_and_names_both_verdicts` | green |
| Same verdict, larger finding set: short-circuit, failure flag cleared, gap listed | integration | `tests/review/test_attempt_attribution.py::test_same_verdict_with_a_different_inline_set_short_circuits_and_lists_the_gap` | green |
| Identical replay: short-circuit with an empty gap | integration | `tests/review/test_attempt_attribution.py::test_matching_receipt_records_no_publication_gap` | green |
| An agent-published review with the same verdict (either order) is not a mismatch | functional | `tests/review/test_attempt_attribution.py::test_an_agent_published_review_with_the_same_verdict_is_not_a_mismatch` (parametrized) | green |
| A fallback attempt keeps the earlier receipt | unit | `tests/utils/test_cov_agent_resolve_paths.py::test_prepare_chain_attempt_keeps_the_publication_receipt` | green (guard) |
| A fallback attempt's different verdict sets the mismatch flag | integration | `tests/utils/test_cov_agent_resolve_paths.py::test_a_fallback_attempt_with_a_different_verdict_sets_the_mismatch_flag` | green |
| A matching replay clears a stale failure flag (existing semantics) | integration | `tests/mcp/test_review.py::test_matching_publication_replay_clears_stale_failure_after_scope_check` | green (guard) |

### A skipped roster slot is not an outcome

| Contract | Layer | Test | Status |
| --- | --- | --- | --- |
| A credential gap with a published `request_changes` keeps its event and classifies by its verdict | functional | `tests/test_run_outcome.py::test_credential_gap_with_a_published_request_changes_classifies_by_its_verdict` | green |
| The same, when the agent published | functional | `tests/test_run_outcome.py::test_credential_gap_with_an_agent_published_verdict_is_not_demoted` | green (guard) |
| The classifier reads the receipt, never the roster | unit | `tests/test_run_outcome.py::test_credential_gap_is_not_a_classifier_input` | green |
| The record still names the degradation | unit | `tests/review_record/test_credential_gap_verdict_775.py` | green (guard) |

### The trajectory keeps a completion step

| Contract | Layer | Test | Status |
| --- | --- | --- | --- |
| `submit_review_verdict` is a completion intent | unit | `tests/evidence/test_trajectory_completion.py::test_submit_review_verdict_is_a_completion_intent` | green |
| A compliant run published by the orchestrator has an ok `orchestrator.publish_review` step and completion claims | functional | `tests/evidence/test_trajectory_completion.py::test_a_compliant_run_published_by_the_orchestrator_has_a_complete_step` | green |
| A run with no receipt records the publish step as not ok and claims no completion for it | functional | `tests/evidence/test_trajectory_completion.py::test_a_run_with_no_receipt_has_no_successful_publish_step` | green |
| Unchanged intents; unknown tools are never `complete`; no submission, no publish step | unit / functional | `tests/evidence/test_trajectory_completion.py::test_create_pull_request_review_is_still_a_completion_intent`, `::test_an_unknown_tool_is_never_counted_as_completion`, `::test_a_run_that_never_submitted_records_no_publish_step` | green (guard) |

### The run record belongs to the final attempt

| Contract | Layer | Test | Status |
| --- | --- | --- | --- |
| A fallback attempt drops the previous attempt's prepared evidence packet | unit | `tests/review/test_attempt_attribution.py::test_prepare_chain_attempt_drops_the_prepared_run_packet` | red |
| On a fallback verdict mismatch, the record does not call the earlier verdict the reviewer's terminal verdict, and names both verdicts | functional | `tests/review/test_attempt_attribution.py::test_a_fallback_mismatch_record_names_both_verdicts_not_the_stale_one` | red |
| A same-verdict publication missing recorded findings inline lists their fingerprints in the record (wording free) | functional | `tests/review/test_attempt_attribution.py::test_a_same_verdict_publication_gap_is_listed_in_the_record` | red |
| The `orchestrator.publish_review` step carries the receipt's `payload_hash`, in state and in the built trajectory; its `publication_incomplete` is empty when nothing is missing | functional | `tests/evidence/test_trajectory_completion.py::test_the_publish_step_carries_the_receipt_hash` | red |
| The `orchestrator.publish_review` step is recorded (ok) even when the agent published the same verdict, and its `publication_incomplete` lists the sorted missing fingerprints | functional | `tests/evidence/test_trajectory_completion.py::test_the_publish_step_lists_findings_missing_from_the_inline_view` | red |

### Thread retirement by line and author

| Contract | Layer | Test | Status |
| --- | --- | --- | --- |
| The five original cases hold on the line-and-author signature | unit | `tests/test_review_resolution.py` (first five `test_*` after the extractor test) | green |
| A line outside every hunk stays open though the file changed; hunk bounds are inclusive; an outdated thread qualifies without overlap; an unknown line resolves nothing | unit | `tests/test_review_resolution.py::test_a_thread_whose_line_is_outside_every_hunk_stays_open_even_when_its_file_changed`, `::test_hunk_boundaries_are_inclusive`, `::test_the_line_just_outside_a_hunk_does_not_qualify`, `::test_an_outdated_thread_qualifies_without_line_overlap`, `::test_an_unknown_line_resolves_nothing`, `::test_no_changed_lines_resolves_only_outdated_threads` | green |
| A marked thread by an unexpected login, by the shared Actions bot, or with no author stays open | unit | `tests/test_review_resolution.py::test_a_marked_thread_by_a_login_outside_the_publisher_set_stays_open`, `::test_a_marked_thread_by_the_shared_actions_bot_stays_open`, `::test_a_comment_with_no_author_resolves_nothing` | green |
| An empty publisher set resolves nothing and logs once why | unit | `tests/test_review_resolution.py::test_an_empty_publisher_set_resolves_nothing_and_says_so_once` | green |
| An outdated thread by an expected publisher whose finding is gone resolves | unit / integration | `tests/test_review_resolution.py::test_an_expected_publisher_outdated_thread_whose_finding_is_gone_resolves`; `tests/mcp/test_review.py::test_rereview_resolves_threads_whose_findings_are_gone` | green |
| Re-review keeps a thread whose line no hunk touched; resolves one whose line was touched | integration | `tests/mcp/test_review.py::test_rereview_keeps_a_thread_whose_line_no_hunk_touched`; `::test_rereview_resolves_a_thread_whose_line_a_hunk_touched` (guard) | green |
| A finding demoted to the body, or still in the terminal submission but not inline, keeps its thread open | integration | `tests/mcp/test_review.py::test_rereview_keeps_the_thread_of_a_finding_demoted_to_the_body`, `::test_rereview_keeps_the_thread_of_a_finding_still_in_the_terminal_submission` | green |
| An unexpected author, or `github-actions[bot]` even when it posted the review, keeps the thread open; no publisher → nothing resolves and the log says why | integration | `tests/mcp/test_review.py::test_rereview_keeps_a_marked_thread_by_an_unexpected_author`, `::test_rereview_never_trusts_the_shared_actions_bot`, `::test_rereview_with_no_expected_publisher_resolves_nothing_and_says_why` | green |
| Re-raised findings and full reviews never resolve | integration | `tests/mcp/test_review.py::test_rereview_keeps_threads_for_findings_it_raised_again`, `::test_full_review_never_resolves_threads` | green (guard) |

### A missing resolve payload is not a resolution

| Contract | Layer | Test | Status |
| --- | --- | --- | --- |
| Empty, null or stateless payloads return not resolved | unit | `tests/mcp/test_review.py::test_resolve_review_thread_treats_a_missing_payload_as_not_resolved` | green |
| The tool does not mark the run updated on such a payload | unit | `tests/mcp/test_review.py::test_resolve_tool_does_not_mark_the_run_updated_on_a_missing_payload` | green |
| Well-formed payloads are reported as-is; a real resolution marks the run updated | unit | `tests/mcp/test_review.py::test_resolve_review_thread_reports_what_github_said`, `::test_resolve_tool_marks_the_run_updated_when_github_resolved` | green (guard) |
| The MCP helper agrees with the SCM adapter, which already fails closed | unit | `tests/scm/test_protocol.py::test_mcp_resolve_helper_agrees_with_the_adapter`; `::test_adapter_resolve_review_thread_fails_closed_on_a_missing_payload` (guard) | green |

### Listings that do not truncate

| Contract | Layer | Test | Status |
| --- | --- | --- | --- |
| 250 comments over three pages come back complete | unit | `tests/mcp/test_issue_comments.py::test_250_comments_over_three_pages_come_back_complete` | green |
| A full last page asks once more and stops on the empty page | unit | `tests/mcp/test_issue_comments.py::test_exactly_one_full_page_asks_once_more_and_stops_on_the_empty_page` | green |
| The page cap stops the listing and says `incomplete` | unit | `tests/mcp/test_issue_comments.py::test_the_page_cap_stops_the_listing_and_says_incomplete`; `tests/mcp/test_review_comments.py::test_the_page_cap_stops_the_listing_and_says_incomplete` | green |
| More than 100 reviews include the newest | unit | `tests/mcp/test_review_comments.py::test_more_than_100_reviews_include_the_newest` | green |
| A short first page is one request with the same rows; no comments is an empty complete listing | unit | `tests/mcp/test_issue_comments.py::test_a_short_first_page_is_one_request`, `::test_no_comments_is_an_empty_complete_listing`; `tests/mcp/test_review_comments.py::test_a_short_first_page_is_one_request_with_the_same_row_shape` | green (guard) |
| The recorded endpoint pins for both tools are unchanged | integration | `tests/scm/test_protocol.py::test_github_tool_endpoint_behaviour_is_unchanged` | green (guard) |

### Unknown trust is untrusted

| Contract | Layer | Test | Status |
| --- | --- | --- | --- |
| `None`, `""` or an unrecognized tier normalizes terminal findings as `untrusted` | integration | `tests/mcp/test_submit_review_verdict.py::test_unknown_trust_tier_normalizes_as_untrusted` | green |
| The same for draft findings in verification | integration | `tests/mcp/test_verification.py::test_unknown_trust_tier_normalizes_draft_findings_as_untrusted` | green |
| The same for learning provenance, and its docstring says so | unit | `tests/utils/test_learnings_provenance.py::test_unknown_trust_tier_stamps_learning_provenance_untrusted`, `::test_provenance_docstring_no_longer_promises_a_trusted_fallback` | green |
| A recognized tier passes through unchanged at all three sites | unit / integration | `::test_known_trust_tier_is_passed_through`, `::test_known_trust_tier_reaches_draft_normalization`, `::test_known_trust_tier_is_stamped_on_learning_provenance` | green (guard) |
| A bare `ToolContext` is `untrusted` on both axes, and the field metadata and `__init__` state that one default | unit | `tests/mcp/test_tool_context_trust_defaults.py::test_a_bare_context_is_untrusted_on_both_axes`, `::test_dataclass_metadata_states_the_same_default` | green |
| An explicit tier is honoured; an explicit authority stays split; the helper demands a tier | unit | `tests/mcp/test_tool_context_trust_defaults.py::test_an_explicit_tier_is_honoured_and_authority_follows_it`, `::test_an_explicit_authority_is_kept_apart_from_execution_trust`, `::test_the_test_helper_requires_a_tier` | green (guard) |
| The local `mergecraft agents` and pipeline-executor contexts stay `trusted` | unit | `tests/mcp/test_tool_context_trust_defaults.py::test_mergecraft_agents_local_context_stays_trusted`, `::test_pipeline_executor_local_context_stays_trusted` | green (guard) |
| The deterministic-record fallback context is `untrusted` | integration | `tests/mcp/test_tool_context_trust_defaults.py::test_deterministic_record_fallback_context_is_untrusted` | green |

### The two named fallbacks

| Contract | Layer | Test | Status |
| --- | --- | --- | --- |
| A malformed run timeout keeps a finite chain deadline from the default and warns | unit | `tests/utils/test_cov_agent_resolve_paths.py::test_malformed_run_timeout_keeps_a_finite_chain_deadline` | green |
| Any run-bounds resolution failure warns and uses the default | unit | `tests/utils/test_cov_agent_resolve_paths.py::test_failing_run_bounds_resolution_warns_and_uses_the_default` | green |
| A valid run timeout bounds the chain exactly | unit | `tests/utils/test_cov_agent_resolve_paths.py::test_configured_run_timeout_sets_the_chain_deadline` | green (guard) |
| A failed closing-issues lookup (HTTP or transport) is flagged and logged at warning; the rest of the PR still returns | unit | `tests/mcp/test_pr_info.py::test_a_failed_closing_issues_lookup_is_flagged_and_logged` | green |
| A successful or empty lookup is not flagged; a failed PR read is still an error | unit | `tests/mcp/test_pr_info.py::test_a_successful_lookup_lists_the_issues_and_is_not_flagged`, `::test_a_pr_with_no_closing_issues_is_not_flagged`, `::test_a_failure_fetching_the_pull_itself_is_still_an_error` | green (guard) |

### `finalize_agent_result` describes what it does

| Contract | Layer | Test | Status |
| --- | --- | --- | --- |
| `success`, `error`, output and diagnostics are preserved on both paths | unit | `tests/review/test_post_run_terminal_gate.py::test_finalize_preserves_success_and_error_on_both_paths` | green (guard) |
| A missing submission is classified by the resolver, not failed by finalize | unit | `tests/review/test_post_run_terminal_gate.py::test_finalize_without_a_submission_does_not_fail_the_result` | green (guard) |
| The docstring no longer claims a hard-fail | unit | `tests/review/test_post_run_terminal_gate.py::test_finalize_docstring_does_not_claim_a_hard_fail` | green |
| The post-run nudge asks for the verdict only, not for `create_pull_request_review` | unit | `tests/review/test_post_run_terminal_gate.py::test_post_run_nudge_no_longer_asks_for_create_pull_request_review` | green |

## Fixture sweep: trust is never implicit

Every `ToolContext(...)` built by a test states its tier. The sweep added
`trust_tier="trusted"` to each constructor call that relied on the old
permissive default (88 call sites across 83 files, plus one shared keyword dict),
so flipping the default changes no existing test's behaviour. New tests build
their contexts through `tests/support/tool_context.py::make_tool_context`,
whose `trust_tier` has no default. The one deliberate exception is
`tests/mcp/test_tool_context_trust_defaults.py`, which constructs a context
without a tier in order to pin what the default is.

The sweep was checked by applying the default flip, the three validator
fallbacks and the three constructor decisions to a scratch copy of the source
and running the whole unit suite against it: every existing test stayed green,
and the only change was the expected greening of this suite's trust tests.

## Support modules

* `tests/support/publication.py` — an offline GitHub fake that records review
  POSTs and resolve mutations and serves review threads; a Review/IncrementalReview
  context bound to PR #7 at a fixed head with a real diff; helpers to record a
  verdict through the real tool and to read fingerprints back.
* `tests/support/finalize_harness.py` — runs the orchestrator's Phase 4 with the
  real `finalize_agent_result` and the real publisher, recording only the
  outcome handed to the sticky/packet publisher.
* `tests/support/paged_scm.py` — an SCM stand-in that serves numbered, oldest-first
  issue comments and reviews page by page, or endlessly.

## Scenario classes

* **Happy path** — one recorded verdict, one review, findings inline, run passes;
  a touched line by an expected publisher whose finding is gone resolves; 250
  comments come back whole.
* **Edge cases** — shadow mode, a progress-only incremental run, identical
  replay, hunk boundaries, outdated anchors, a full last page, an empty
  listing, an explicit split between execution and authority trust.
* **Error handling** — a refused POST, a publisher that raises, a different
  verdict on the same head through each entrypoint, forged markers, the shared
  Actions login, an empty publisher set, malformed resolve payloads, an
  endless listing, a malformed run timeout, an HTTP or transport failure on
  the closing-issues lookup, and unknown trust at every validator.
