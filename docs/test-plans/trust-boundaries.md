# Who the reviewer thinks it is reviewing — trust boundaries — test plan

Wave plan: `.ignorelocal/waves/40-trust-boundaries-wave-plan.md`
Worktree: `mc-trust` @ `wave/trust-boundaries`
Authoring wave: **TB1** (`test-creator`). Implementation: **TB2–TB5**. Final: **TB6**.

This document maps every locked contract (**TB-D1 … TB-D14**) to the tests that
cover it, across unit / integration / functional layers and the happy-path,
edge-case and error-handling classes. It is the reconciliation ledger for the
cross-wave RED markers.

## Model

The suite is authored **first** and is deliberately RED: every test that
depends on a TB2–TB5 seam carries a **non-strict** marker

```python
@pytest.mark.xfail(reason="green after TB2: …", strict=False)
```

so collection, `make lint` and `make typecheck` stay clean while the assertions
fail. The repo sets `xfail_strict = true` globally, so the explicit
`strict=False` is required. After each implementation wave the `test-creator` is
re-dispatched to delete the now-satisfied markers (the `scripts/check_xpass.py`
ratchet fails any leftover XPASS).

Tests that encode behaviour that survives TB2–TB5 carry **no** marker: they are
the guards proving a fix did not widen or weaken a control.

## Contract → test matrix

### TB-D1 — an event that names a PR but carries no bound head is a fork

| Scenario | Tests | Layer |
| --- | --- | --- |
| Comment on a PR (no `pull_request`, `issue.pull_request` present) | `tests/config/test_trust_policy_comment_binding.py::test_comment_on_pr_without_pull_request_is_a_fork`, `::test_comment_on_pr_is_a_fork_regardless_of_commenter[OWNER/MEMBER/COLLABORATOR]` | unit |
| Comment on a plain issue (unchanged) | `…::test_comment_on_plain_issue_is_not_a_fork` | unit (guard) |
| Dispatch naming a PR | `…::test_dispatch_naming_a_pr_is_a_fork_until_bound` | unit |
| Dispatch naming no PR (unchanged) | `…::test_dispatch_without_a_pr_is_not_a_fork` | unit (guard) |
| Live dispatch prompt (`payload["prompt"]`) merged into the event | `…::test_bind_dispatch_review_prompt_is_pure_and_binds_the_composed_prompt`, `::test_bind_dispatch_review_prompt_adds_inputs_when_absent` | unit |
| Non-dispatch / PR-less / pre-populated / empty prompt unchanged | `…::test_bind_dispatch_review_prompt_ignores_a_non_dispatch_event`, `::test_bind_dispatch_review_prompt_ignores_a_pr_less_prompt`, `::test_bind_dispatch_review_prompt_does_not_clobber_an_existing_input`, `::test_bind_dispatch_review_prompt_ignores_a_missing_or_empty_prompt` | unit (guards) |
| Tier floor from the same predicate | `tests/security/test_trust_fallthrough.py::test_issue_comment_on_pr_without_head_is_untrusted[OWNER/MEMBER/COLLABORATOR]` | unit |
| Plain-issue tier (unchanged) | `…::test_issue_comment_on_plain_issue_stays_trusted` | unit (guard) |

### TB-D2 — bind by fetching, once, before the first trust read

| Scenario | Tests | Layer |
| --- | --- | --- |
| `bind_target_pull_request` is pure and sets number/head/base | `tests/config/test_trust_policy_comment_binding.py::test_bind_target_pull_request_is_pure_and_sets_the_bound_head` | unit |
| Binding a same-repo PR clears the floor | `…::test_binding_a_same_repo_pr_clears_the_fork_floor` | unit |
| Binding a fork keeps the floor | `…::test_binding_a_fork_pr_keeps_the_fork_floor` | unit |
| Bound same-repo comment stays trusted | `…::test_comment_after_binding_same_repo_is_trusted` | integration |
| Bound fork comment is untrusted | `…::test_comment_after_binding_a_fork_is_untrusted` | integration |
| Unbound comment-on-PR floors both axes | `…::test_comment_on_pr_resolves_untrusted_both_axes` | integration |
| Dispatch: unbound floors, bound same-repo trusted, bound fork untrusted | `…::test_dispatch_naming_a_pr_resolves_untrusted_before_binding`, `::test_dispatch_after_binding_same_repo_is_trusted`, `::test_dispatch_after_binding_a_fork_is_untrusted` | integration |
| `_resolve_credentials` binds before the invariant | `tests/test_main_phases.py::test_resolve_credentials_binds_the_target_pr_before_the_invariant` | integration |
| Fetch failure leaves the event unbound → refuses naming the unbound PR | `tests/test_main_phases.py::test_resolve_credentials_refuses_when_the_pr_fetch_fails` | integration |
| Bound same-repo run keeps trust | `tests/test_main_phases.py::test_resolve_credentials_binds_a_same_repo_pr_and_keeps_trust` | integration |
| Dispatch: PR only in `payload["prompt"]` → binds same-repo | `…::test_resolve_credentials_binds_a_dispatch_pr_from_the_composed_prompt` | integration |
| Dispatch: fork only in `payload["prompt"]` → refused as a fork | `…::test_resolve_credentials_refuses_a_dispatch_fork_from_the_composed_prompt` | integration |
| Dispatch: fetch failure → unbound refusal naming the PR | `…::test_resolve_credentials_refuses_a_dispatch_when_the_fetch_fails` | integration |
| Dispatch: PR-less payload → no fetch, unchanged | `…::test_resolve_credentials_leaves_a_pr_less_dispatch_alone` | integration (guard) |
| Dispatch: event-shape prompt still binds | `…::test_resolve_credentials_binds_a_dispatch_named_in_the_event_inputs` | integration (guard) |
| Plain-issue comment fetches nothing | `tests/test_main_phases.py::test_resolve_credentials_does_not_fetch_for_a_plain_issue` | integration (guard) |
| Uncredentialed fetch failure does not refuse | `tests/test_main_phases.py::test_resolve_credentials_leaves_uncredentialed_comment_runs_alone` | integration (guard) |
| Unbound message names the PR distinctly from a fork | `tests/action/test_fork_credential_invariant.py::test_comment_on_pr_with_credentials_is_refused` | unit |
| Bound-fork message still names the fork | `…::test_bound_fork_refusal_message_names_the_fork` | unit (guard) |
| Uncredentialed comment-on-PR allowed | `…::test_comment_on_pr_without_credentials_is_allowed` | unit (guard) |

### TB-D3 — one fork predicate

Covered transitively: `resolve_trust_policy` (above) and `derive_trust_tier`
(`tests/security/test_trust_fallthrough.py`) both consult
`is_fork_pull_request`. No separate structural test — the behavioural pins are
the contract.

### TB-D4 — checkout refuses an unbound or re-classified PR

| Scenario | Tests | Layer |
| --- | --- | --- |
| `pull_number` ≠ bound `ctx.payload.event.issue_number` → refuse | `tests/mcp/test_checkout_target_binding.py::test_checkout_refuses_a_pull_number_the_run_was_not_bound_to` | functional |
| Fork PR while execution trust is `trusted` → refuse | `…::test_checkout_refuses_a_fork_pr_on_a_trusted_run` | functional |
| Fork PR while authority trust is `trusted` → refuse | `…::test_checkout_refuses_a_fork_pr_when_authority_trust_is_trusted` | functional |
| Bound same-repo PR allowed | `…::test_checkout_allows_the_bound_same_repo_pull_number` | functional (guard) |
| Fork PR on an untrusted run allowed | `…::test_checkout_allows_a_fork_pr_on_an_untrusted_run` | functional (guard) |
| No bound PR number → no number refusal | `…::test_checkout_without_a_bound_pr_does_not_refuse_on_number` | functional (guard) |
| Dispatch payload, bound `ctx.gh_event` #42 → checking out #43 refused | `…::test_checkout_refuses_a_dispatch_pull_number_the_run_was_not_bound_to` | functional |
| Dispatch payload, bound `ctx.gh_event` #42 → #42 allowed | `…::test_checkout_allows_the_dispatch_bound_pull_number` | functional |
| `gh_event` present but no `pull_request` → payload number fallback | `…::test_checkout_falls_back_to_the_payload_number_without_a_bound_pull_request` | functional |
| Non-integer bound `number` does not bind | `…::test_checkout_ignores_a_non_integer_bound_number` | functional (guard) |
| Dispatch with no bound number anywhere → permissive | `…::test_checkout_without_a_bound_number_on_a_dispatch_is_permissive` | functional (guard) |

### TB-D5 — a files-API diff after a successful checkout is labelled as exactly that

| Scenario | Tests | Layer |
| --- | --- | --- |
| `git diff` fails → `provenance="api"`, `review_scope="files-api-diff"`, `degraded` reason, warning | `tests/mcp/test_checkout_degraded_diff.py::test_git_diff_failure_is_labelled_a_files_api_diff` | integration |

### TB-D6 — omitted patch: text is unreviewable, zero-line is binary

| Scenario | Tests | Layer |
| --- | --- | --- |
| No `patch`, `additions + deletions > 0` → `unreviewablePaths` + `degraded` | `tests/mcp/test_checkout_degraded_diff.py::test_missing_text_patch_is_recorded_as_unreviewable` | integration |
| No `patch`, no line changes → header only, not flagged | `…::test_zero_line_missing_patch_is_not_unreviewable` | integration (guard) |
| Page cap hit → `degraded` truncation | `…::test_page_cap_records_a_truncation` | integration |

### TB-D7 — authorship follows P-17 (marker ∧ expected publisher)

| Scenario | Tests | Layer |
| --- | --- | --- |
| Marker + expected publisher counts | `tests/review/test_authorship.py::test_marker_from_an_expected_publisher_is_authored` | unit |
| Foreign App's bot refused | `…::test_marker_from_a_foreign_app_bot_is_not_authored` | unit |
| Human marker refused | `…::test_marker_from_a_human_is_not_authored` | unit |
| No marker refused | `…::test_no_marker_is_not_authored` | unit |
| Empty publisher set authorizes nothing | `…::test_empty_publisher_set_authorizes_nothing` | unit |
| Missing author refused | `…::test_missing_user_is_not_authored` | unit |
| App slug → `<slug>[bot]` | `…::test_expected_publishers_includes_the_app_bot_login` | unit |
| Lookup failure drops the login, never widens | `…::test_failed_lookup_drops_the_login_and_never_widens` | unit |
| Set built once per run (cached) | `…::test_expected_publishers_is_built_once_per_run` | unit |
| Helper is total with no App configured | `…::test_expected_publishers_returns_a_frozenset_without_an_app` | unit (guard) |
| Running-loop branch (the production path) resolves the App login | `…::test_expected_publishers_resolves_from_a_running_loop` | unit (async) |
| A failure on the running-loop branch never widens | `…::test_failed_lookup_from_a_running_loop_never_widens` | unit (async, guard) |
| `last_reviewed_sha` ignores an unexpected author | `tests/mcp/test_checkout.py::test_last_reviewed_sha_ignores_a_marker_from_an_unexpected_author` | unit |
| `last_reviewed_sha` ignores another App's bot | `…::test_last_reviewed_sha_ignores_a_marker_from_another_app_bot` | unit |
| `last_reviewed_sha` counts the publishing login (PAT run) | `…::test_last_reviewed_sha_counts_a_marker_from_the_publishing_login` | unit |
| `review_round_index` uses the same rule | `…::test_review_round_index_ignores_unexpected_authors` | unit |
| `list_mergecraft_reviews` paginates to the newest review | `…::test_list_mergecraft_reviews_paginates_to_find_the_newest` | integration |
| `list_mergecraft_reviews` oldest-first | `…::test_list_mergecraft_reviews_returns_oldest_first` | integration |
| `list_mergecraft_reviews` filters other authors | `…::test_list_mergecraft_reviews_drops_marker_reviews_from_other_authors` | integration |
| Existing checkpoint/round/incremental behaviour | `tests/mcp/test_checkout.py` (existing `last_reviewed_sha_*`, `test_incremental_*`) | unit + integration (guards) |
| Declared shared `github-actions[bot]` login is withheld | `…::test_declared_github_actions_bot_login_is_withheld` | unit |
| Withholding is case-insensitive | `…::test_withheld_shared_bot_login_is_matched_case_insensitively[github-actions[bot]/GitHub-Actions[Bot]]` | unit (edge) |
| A real declared App bot login is still added | `…::test_declared_app_bot_login_is_still_added` | unit (guard) |
| Declared shared bot does not suppress a real App login | `…::test_declared_shared_bot_does_not_suppress_a_real_app_login` | unit (guard) |
| Job-token publication adds nothing | `…::test_job_token_publication_adds_nothing` | unit |
| PAT publication adds the `GET /user` login | `…::test_pat_publication_adds_the_viewer_login` | unit (guard) |
| Withheld shared bot → exactly one warning naming identity + remedy | `…::test_withheld_shared_bot_warns_once_naming_the_identity_and_remedy` | unit (P-8) |
| Job-token withholding also warns once | `…::test_job_token_withholding_warns_once` | unit (P-8) |
| `is_mergecraft_authored` refuses the shared bot on a job-token run | `…::test_is_mergecraft_authored_refuses_the_job_bot_on_a_job_token_run` | unit |
| `last_reviewed_sha` ignores a shared-bot marker on a job-token run | `tests/mcp/test_checkout.py::test_last_reviewed_sha_does_not_adopt_a_github_actions_bot_review_on_a_job_token_run` | integration |
| `review_round_index` ignores a shared-bot marker on a job-token run | `…::test_review_round_index_ignores_a_github_actions_bot_review_on_a_job_token_run` | integration |
| App-publisher path still advances checkpoint and round | `…::test_app_publisher_still_advances_the_checkpoint_and_round` | integration (guard) |

### TB-D8 — instruction files read only inside the resolved repo root

| Scenario | Tests | Layer |
| --- | --- | --- |
| Out-of-repo symlinked file not discovered | `tests/context/test_instruction_discovery.py::test_out_of_repo_symlinked_instruction_is_not_discovered` | unit |
| Out-of-repo symlinked file not read into the prompt | `…::test_out_of_repo_symlinked_instruction_is_not_read` | unit |
| Skip recorded in the bundle's `refusals` | `…::test_out_of_repo_symlinked_instruction_is_recorded_in_refusals` | unit |
| Out-of-repo symlinked directory not walked | `…::test_symlinked_directory_outside_repo_is_not_walked` | unit (guard) |
| In-repo symlink still works | `…::test_in_repo_symlinked_instruction_still_works` | unit (guard) |
| Read-time refusal of an out-of-root path | `…::test_instruction_body_refuses_a_path_outside_the_root` | unit |
| Candidate re-pointed outside after discovery is not read (TOCTOU) | `…::test_instruction_repointed_outside_after_discovery_is_not_read` | integration |

### TB-D9 — remove the D4 switch; do not gate it

| Scenario | Tests | Layer |
| --- | --- | --- |
| Legacy env var no longer removes the paragraph | `tests/utils/test_instructions.py::test_security_paragraph_cannot_be_disabled` | unit |
| The switch string is absent from `src/` | `…::test_disable_security_instructions_switch_is_absent_from_the_tree` | structural |
| Paragraph present by default | `…::test_security_paragraph_is_present_by_default` | unit (guard) |

### TB-D10 — grants match exact lowercase `owner/name`

| Scenario | Tests | Layer |
| --- | --- | --- |
| Exact slug authorizes; a different owner's same name does not | `tests/xrepo/test_linked_repos.py::test_grant_matches_exact_slug_not_a_tail` | unit (guard) |
| Bare-name grant matches nothing | `…::test_bare_name_grant_matches_nothing` | unit |
| Manifest intersection adds slugs only (no bare-name re-expansion) | `…::test_intersect_manifest_grant_adds_slugs_only` | unit |
| A slug grant does not leak to `attacker/foo` | `…::test_slug_grant_does_not_authorize_a_same_name_other_owner` | integration |
| Two entries sharing a `name` are both refused | `…::test_two_manifest_entries_sharing_a_name_are_both_refused` | unit |

### TB-D11 — review-path change set = pin movement

| Scenario | Tests | Layer |
| --- | --- | --- |
| Unmoved pin → zero findings | `tests/xrepo/test_review_change_set.py::test_unmoved_pin_yields_zero_findings` | integration |
| Moved pin → only surfaces that differ between pins | `…::test_moved_pin_reports_only_surfaces_changed_between_pins` | integration |
| Unchanged surfaces never reported | `…::test_unchanged_surfaces_are_not_reported_as_changed` | integration |
| Deleted surface reported at `base_commit` | `…::test_deleted_surface_is_a_finding_anchored_at_the_base_pin` | integration |
| Rename → old path at `base_commit`, new path at `head_commit` | `…::test_renamed_surface_yields_both_pins` | integration |
| Byte-identical surfaces still not reported after the base walk | `…::test_surface_identical_at_both_pins_is_still_not_reported` | integration (guard) |
| Explicit CLI `producer=` keeps whole-index semantics | `…::test_explicit_producer_keeps_whole_index_semantics` | integration (guard) |
| Real `_base_linked_repo_manifest`: absent vs corrupt vs valid | `tests/mcp/test_checkout_base_manifest_lookup.py::test_absent_base_manifest_reads_as_empty_without_a_reason`, `::test_corrupt_base_manifest_is_marked_unreadable`, `::test_valid_base_manifest_is_parsed`, `::test_binary_base_manifest_is_marked_unreadable`, `::test_no_base_ref_returns_an_empty_lookup` | unit (real git read path) |
| A readable base manifest drives the real pin-movement findings | `…::test_valid_base_manifest_drives_the_pin_movement_findings` | integration |

### TB-D12 — every linked-repo omission is in the payload

| Scenario | Tests | Layer |
| --- | --- | --- |
| Ungranted entry appears in `linkedRepoOmitted` | `tests/xrepo/test_review_change_set.py::test_ungranted_entry_appears_in_linked_repo_omitted` | integration |
| Unreachable previous pin is an omission, not a full index | `…::test_unreachable_previous_pin_is_an_omission_not_a_full_index` | integration |
| Absent base manifest (no manifest at `origin/<base>`) → no omission | `tests/mcp/test_checkout_base_manifest_lookup.py::test_absent_base_manifest_yields_no_omission` | integration |
| Unreadable base manifest → omission per entry, zero findings | `…::test_unreadable_base_manifest_omits_every_reviewable_entry` | integration |
| Failed base fetch → `unreadable_reason` names the failure | `…::test_unresolved_base_ref_with_a_fetch_failure_marks_the_manifest_unreadable` | unit (real git read path) |
| Failed base fetch → omission per otherwise-reviewable entry | `…::test_failed_base_fetch_omits_every_reviewable_entry` | integration |
| Absent manifest with no fetch failure → still no omission | `…::test_absent_manifest_with_no_fetch_failure_stays_omission_free` | integration (guard) |

### TB-D13 — no docs edits / floor numbers / new required check

No test; enforced by TB6's strictness sweep and `make ci-static`.

### TB-D14 — inside Actions the startup load reads no `.env` unless `$MERGECRAFT_ENV` names one

| Scenario | Tests | Layer |
| --- | --- | --- |
| Actions does not load a workspace `.env` | `tests/cli/test_local_env_loader.py::test_actions_does_not_load_a_workspace_env` | functional |
| Predicate is case-insensitive (mirrors `running_in_github_actions`) | `…::test_actions_predicate_is_case_insensitive[true/True/TRUE]` | functional |
| Explicit `$MERGECRAFT_ENV` file loads | `…::test_actions_loads_an_explicit_mergecraft_env` | functional (guard) |
| Outside Actions the root `.env` loads as today | `…::test_outside_actions_the_root_env_loads_as_today` | functional (guard) |
| Pre-set keys still win (`override=False`) | `…::test_preset_keys_still_win_over_the_env_file` | functional (guard) |
| No file in Actions is a silent no-op | `…::test_actions_with_no_env_file_is_a_silent_noop` | functional (guard) |

### TB6 — the recorded review tier matches the run's tier

The Action entry point binds its `ReviewContext` before credentials resolve, so
for a comment-on-PR run the pre-binding event floors to `untrusted` even when
the bound, same-repo PR resolves `trusted`. The raw floor is recorded under
`review.raw_event_trust_floor`; the tier the run actually used is stamped onto
`review.trust_tier` / `mergecraft.trust_tier` once materialize has resolved it.

| Scenario | Tests | Layer |
| --- | --- | --- |
| Pre-binding context records the raw floor and no run tier | `tests/tracing/test_review_trust_stamp.py::test_action_context_records_the_raw_floor_and_no_run_tier` | integration |
| Bound same-repo run → `review.trust_tier == tool_state.trust_tier == "trusted"`, floor still `untrusted` | `…::test_bound_same_repo_run_stamps_the_resolved_tier_and_keeps_the_floor` | integration |
| Both attribute spellings present and distinct | same test | integration |
| Stamping with no bound context is a total no-op | `…::test_stamp_is_a_noop_without_a_bound_context` | unit (guard) |

### TB6 — the shared Actions job bot is never accepted as proof of authorship

PR #866 review follow-up. The earlier TB-D7 rule added `github-actions[bot]` to
the expected-publisher set when the run published with the Actions job token.
That is unsound: `github-actions[bot]` is a *shared* identity, so any same-repo
collaborator with workflow permissions can add a `pull_request` workflow on
their branch that posts a marker-bearing review as that login, moving the
incremental checkpoint (`last_reviewed_sha`) to a commit of their choosing; the
next IncrementalReview then diffs *from* it and omits the commits in between.
Only an App bot login (`<slug>[bot]`) or a PAT login (`GET /user`) is accepted.
A run whose only candidate is the shared bot resolves to the **empty** set
(fail-closed) and says so exactly once at `warning`, naming the identity and the
App/PAT remedy (never a silent empty set).

`test_authorship.py`'s module doctrine bullet was corrected from "only when
job-token publication is enabled" to "never". The cases drive the real
`_collect_publisher_logins` path (no monkeypatched `publishers=`), so a
reverted product fix fails all of them except the intentional App/PAT guards.

| Scenario | Tests | Layer |
| --- | --- | --- |
| Declared shared login withheld; job token adds nothing; App and PAT logins unaffected | `tests/review/test_authorship.py` (12 cases above) | unit |
| Job-token run's empty set refuses `github-actions[bot]` for checkpoint and round | `tests/mcp/test_checkout.py::test_last_reviewed_sha_does_not_adopt_a_github_actions_bot_review_on_a_job_token_run`, `::test_review_round_index_ignores_a_github_actions_bot_review_on_a_job_token_run` | integration |
| Over-correction guard: App publisher still advances both | `…::test_app_publisher_still_advances_the_checkpoint_and_round` | integration (guard) |

## Pinned implementation seams

These are the names the tests target; TB2–TB5 must expose them.

| Seam | Module | Consumed by |
| --- | --- | --- |
| `bind_target_pull_request(event, pull)` | `mergecraft.config.trust_policy` | TB-D2 tests |
| `bind_dispatch_review_prompt(event, *, event_name, prompt)` | `mergecraft.config.trust_policy` | F1 tests |
| `is_fork_pull_request(event)` (extended) | `mergecraft.config.trust_policy` | TB-D1/D3 tests |
| `expected_publisher_logins(ctx)`, `is_mergecraft_authored(item, *, publishers)` | `mergecraft.review.authorship` (new) | TB-D7 tests |
| `list_mergecraft_reviews(ctx, *, pull_number)` | `mergecraft.mcp.checkout` | TB-D7 tests |
| `last_reviewed_sha(..., publishers=)`, `review_round_index(..., publishers=)` | `mergecraft.mcp.checkout` | TB-D7 tests |
| `_base_linked_repo_manifest(*, cwd, base_ref) -> BaseManifestLookup` | `mergecraft.mcp.checkout` | F4 tests |
| `review_linked_repos(..., base_manifest=, base_manifest_error=)` | `mergecraft.xrepo.review` | TB-D11 / F4 tests |
| `attach_linked_repo_review(..., base_manifest=, base_manifest_error=)` + `linkedRepoOmitted` | `mergecraft.review.linked_repos` | TB-D12 / F4 tests |
| `_base_linked_repo_manifest(*, cwd, base_ref, base_fetch_failure=)` | `mergecraft.mcp.checkout` | F4 / TB6 fetch-failure tests |
| `stamp_review_context(**overrides)`, `_stamp_review_trust_tier(ctx)` | `mergecraft.tracing.review_context`, `mergecraft.main` | TB6 tier-stamp tests |

**Documented assumptions (amend at reconciliation if the implementation names
them differently):**

- A PR-naming `workflow_dispatch` event is encoded as
  `{"action": "workflow_dispatch", "inputs": {"prompt": "Review pull request #N. …"}}`
  — the composed dispatch review input. If TB2 reads the number from a different
  field, the three dispatch tests in
  `tests/config/test_trust_policy_comment_binding.py` are the ones to amend.
- `expected_publisher_logins` reads the reviewer App slug from a `GET /app`
  response shaped `{"slug": "mergecraft"}` and renders `<slug>[bot]`.
- `_intersect_manifest_grant` returning the empty set is the encoding of
  "two same-name entries are both refused".

## RED evidence (TB1)

- `62 xfailed` (non-strict, tagged `green after TB2/TB3/TB4/TB5`) — the missing
  contract.
- `96 passed` across the touched files — surviving guards and pre-existing tests.
- `0 failed`, `0 xpassed` at authoring time.
- `make lint` → exit 0; `make typecheck` → `Success: no issues found in 538
  source files`.

## xfail reconciliation ledger

| Wave | Marker prefix | Files to reconcile | Status |
| --- | --- | --- | --- |
| TB2 | `green after TB2:` | `tests/config/test_trust_policy_comment_binding.py`, `tests/security/test_trust_fallthrough.py`, `tests/action/test_fork_credential_invariant.py`, `tests/test_main_phases.py`, `tests/mcp/test_checkout_target_binding.py` | ✅ reconciled 2026-09-24 (all markers removed, real passes) |
| TB3 | `green after TB3:` | `tests/mcp/test_checkout.py`, `tests/mcp/test_checkout_degraded_diff.py`, `tests/review/test_authorship.py` | ✅ reconciled 2026-09-24 (all markers removed, real passes) |
| TB4 | `green after TB4:` | `tests/context/test_instruction_discovery.py`, `tests/utils/test_instructions.py`, `tests/cli/test_local_env_loader.py` | ✅ reconciled 2026-09-24 (all markers removed, real passes) |
| TB5 | `green after TB5:` | `tests/xrepo/test_linked_repos.py`, `tests/xrepo/test_review_change_set.py` | ✅ reconciled 2026-09-24 (all markers removed, real passes) |

### TB5 test-creator reconciliation (2026-09-24)

All TB4/TB5 markers are removed; the trust-boundaries suite now carries **zero**
`xfail`/`xpass` markers. Three test-side fixes landed with the reconciliation:

1. **Fixture bug** — `tests/xrepo/test_review_change_set.py::test_ungranted_entry_appears_in_linked_repo_omitted`
   called `git_commit_all(secrets)` without `git_init_repo(secrets)`, so `git add -A`
   exited 128 inside the fixture before any product code ran. Added the missing
   `git_init_repo(secrets)` (the pattern `tests/xrepo/test_xrepo_wiring.py` already
   uses). This was the last remaining XFAIL.
2. **Superseded bare-grant guard** — `tests/xrepo/test_linked_repos.py::test_authorized_linked_repo_content_is_read_from_checkout`
   pinned the pre-TB-D10 behaviour (`RunGrant({"api-contracts"})` authorizing
   `repo="api-contracts"`). Under TB-D10 a bare-name grant matches nothing, so the
   test now grants the slug `{"acme/api-contracts"}` and reads `repo="acme/api-contracts"`
   (`repo_roots` stays keyed by the bare `entry.name`, mirroring
   `discover_linked_repo_roots`). The assertion is unchanged: content is still read
   from the granted repo's checkout root.
3. **`tests/xrepo/test_xrepo_wiring.py:176`** — the plan's TB5.2 bare grant became a
   slug grant (`frozenset({"acme/api-contracts"})`), so the wiring test exercises the
   grant path instead of staying green only because bare names are inert.

**Verification:** `MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/xrepo tests/context
tests/utils/test_instructions.py tests/cli/test_local_env_loader.py
tests/cli/test_local_env_path.py tests/instructions -q -p no:randomly` →
**150 passed, 0 failed, 0 xfailed, 0 xpassed**; `make lint` → exit 0;
`make typecheck` → `Success: no issues found`.

### TB3 amendment — `init_pr_clone` base branch (2026-09-24)

`tests/mcp/reviewer_resilience_support.py::init_pr_clone` created the work repo's
base branch as `base`, while the shared `_StubGitHub.get_pull` in
`tests/mcp/test_reviewer_resilience_degraded_scope.py` returns `base.ref == "main"`.
After TB3/P10 an unresolvable base correctly degrades to `files-api-diff`, so the
non-degraded test `test_successful_checkout_pr_sets_scope_provenance_checkout`
must have a base branch the stub resolves. The fixture now names the base branch
`main` (safe: exactly one test consumes it, and no assertion depends on the old
name). TB-D5 is unchanged; the degraded path stays covered by
`tests/mcp/test_checkout_degraded_diff.py`.


### TB6 follow-up coverage (F1, F4, F5, F6 — 2026-09-24)

The Final verifier returned `changes_required` on the TB6 diff. Four findings
were test-side gaps or silent skips; the product fixes landed with TB6 and this
section records the coverage added against them. No marker is carried: the
product behaviour is in place, so every test is a real pass.

- **F1 (blocking) — dispatch PR-naming on the live path.** The TB1 dispatch
  tests set `event["inputs"]["prompt"]`, but the live review dispatch composes
  the prompt into the Action `prompt` input (`payload["prompt"]`) and leaves
  `github.event.inputs.prompt` empty. Added unit tests for the pure
  `bind_dispatch_review_prompt` (copy, never mutates; only binds a
  `workflow_dispatch` whose composed prompt names `pull request #<n>` and whose
  `inputs.prompt` is empty) in
  `tests/config/test_trust_policy_comment_binding.py`, and live-path
  `_resolve_credentials` tests in `tests/test_main_phases.py` (same-repo →
  trusted; fork → refused; fetch failure → unbound refusal naming the PR;
  PR-less → no fetch; event-shape dispatch still binds). The driver
  `_drive_credentials` gained `event_name=` / `payload=` parameters.
- **F4 — base linked-repo manifest absent vs unreadable.** New
  `tests/mcp/test_checkout_base_manifest_lookup.py` exercises the **real**
  `_base_linked_repo_manifest` over a checkout with an `origin/<base>` ref
  (absent → empty, no reason; corrupt/binary → `unreadable_reason`; valid →
  parsed) and feeds the lookup into `attach_linked_repo_review` (absent → no
  omission; unreadable → `linkedRepoOmitted` per otherwise-reviewable entry,
  zero findings; valid → the real pin-movement finding).
- **F5 — TOCTOU re-check in `_instruction_body`.** Added a direct unit test of
  the read-time refusal and a live-path test that re-points an accepted symlink
  outside the repo between discovery and read
  (`tests/context/test_instruction_discovery.py`). Both fail if the re-check is
  deleted.
- **F6 — silent skip in test code.** `tests/mcp/test_checkout.py::_pin_publishers`
  now imports `mergecraft.review.authorship` directly and patches
  `checkout.expected_publisher_logins` by direct attribute access (no
  `try/except ImportError`, no `hasattr`), so a missing seam fails loudly.

**Verification (TB6):** the scoped acceptance command below →
`0 failed, 0 xfailed, 0 xpassed`; `make lint` + `make typecheck` clean.

**TB6 CI amendment — state the Actions environment (2026-09-24).** GitHub
Actions surfaced `tests/cli/test_local_env_path.py::test_cli_loader_reads_repo_root_env_from_subdirectory`
as red: it asserted the workspace `.env` loads, but the TB1 / TB-D14 startup rule
skips it inside Actions and CI sets `GITHUB_ACTIONS`. The test's intent — proving
the local load path from a subdirectory — is unchanged; the module's autouse
fixture now clears `GITHUB_ACTIONS` (alongside `MERGECRAFT_ENV`) so each case
states the environment it means. `tests/cli/test_local_env_loader.py` already
pinned non-Actions in its fixture; its docstring now records that contract. No
assertion weakened, no source touched.

### TB6 post-PR test pinning (2026-09-24)

Both mergeCraft reviews of PR #866 flagged five behaviours the post-review fixes
in the working tree address. This pass pins each fix; no marker is carried, so
the suite ends with zero `xfail`/`xpass`. Every test below was confirmed to fail
against a temporary local revert of its product change (removed again before
this document was updated).

1. **Checkout binds the PR from `ctx.gh_event`, not only the payload (TB-D4).**
   `_resolve_credentials` writes the fetched `pull_request.number` onto
   `ctx.gh_event`, but `checkout_pr` read only `ctx.payload.event.issue_number` —
   empty on a `workflow_dispatch` (and a comment-on-PR), so the mismatch guard
   was inert there. `tests/mcp/test_checkout_target_binding.py` gains the
   dispatch-shaped cases (bound #42 refuses #43; allows #42), the payload
   fallback when the bound event has no `pull_request`, the non-integer `number`
   guard, and the dispatch-unbound permissive guard. `_pr_repo` now takes a
   `pull_number`; `_ctx_for` takes `payload_event=` / `gh_event=`.
2. **The change set walks the base index too (TB-D11).** A moved pin that
   deleted or renamed a surface a consumer referenced at the base pin produced
   no finding. `tests/xrepo/test_review_change_set.py` gains deletion and rename
   fixtures: a removed surface is anchored at `base_commit` (one row per indexed
   symbol), a rename yields the old path at `base_commit` and the new path at
   `head_commit`, and byte-identical surfaces still yield nothing.
3. **The authorship running-loop branch is under test (TB-D7).** Production calls
   `expected_publisher_logins` from async code, so `_await_sync` takes its
   `asyncio.get_running_loop()` branch; the sync tests exercised the other one.
   `tests/review/test_authorship.py` gains two `async def` tests calling the
   helper from a running loop (App login resolves; a failure never widens).
4. **The recorded review tier matches the run's tier (TB6).**
   `tests/tracing/test_review_trust_stamp.py` (new) records the raw floor for a
   comment-on-PR event with no run tier, then stamps the resolved
   `tool_state.trust_tier` and asserts `review.trust_tier` /
   `mergecraft.trust_tier` are `trusted` while
   `review.raw_event_trust_floor` stays `untrusted`.
5. **A failed base fetch is an omission (F4).**
   `tests/mcp/test_checkout_base_manifest_lookup.py` gains the
   `base_fetch_failure` path (unresolvable `origin/<base>` → `unreadable_reason`
   naming the failure; `attach_linked_repo_review` omits each otherwise-reviewable
   entry) and an explicit absent-manifest/no-fetch-failure guard.

**Verification (post-PR pinning):**
`MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/mcp tests/xrepo tests/review tests/tracing tests/config tests/test_main_phases.py -q -p no:randomly`
→ **1899 passed, 45 skipped, 0 failed, 0 xfailed, 0 xpassed**; `make lint` →
exit 0; `make typecheck` → `Success: no issues found in 539 source files`.

## Verification

```bash
export PATH="$HOME/.local/bin:$PATH"
MERGECRAFT_PYTEST_JOBS=0 uv run pytest -q -rX \
  tests/config/test_trust_policy_comment_binding.py \
  tests/security/test_trust_fallthrough.py \
  tests/action/test_fork_credential_invariant.py \
  tests/test_main_phases.py \
  tests/mcp/test_checkout.py \
  tests/mcp/test_checkout_target_binding.py \
  tests/mcp/test_checkout_degraded_diff.py \
  tests/mcp/test_checkout_base_manifest_lookup.py \
  tests/review/test_authorship.py \
  tests/context/test_instruction_discovery.py \
  tests/utils/test_instructions.py \
  tests/cli/test_local_env_loader.py \
  tests/xrepo/test_linked_repos.py \
  tests/xrepo/test_review_change_set.py \
  tests/tracing/test_review_trust_stamp.py
make lint
make typecheck
```
