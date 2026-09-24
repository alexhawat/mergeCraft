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
| `last_reviewed_sha` ignores an unexpected author | `tests/mcp/test_checkout.py::test_last_reviewed_sha_ignores_a_marker_from_an_unexpected_author` | unit |
| `last_reviewed_sha` ignores another App's bot | `…::test_last_reviewed_sha_ignores_a_marker_from_another_app_bot` | unit |
| `last_reviewed_sha` counts the publishing login (PAT run) | `…::test_last_reviewed_sha_counts_a_marker_from_the_publishing_login` | unit |
| `review_round_index` uses the same rule | `…::test_review_round_index_ignores_unexpected_authors` | unit |
| `list_mergecraft_reviews` paginates to the newest review | `…::test_list_mergecraft_reviews_paginates_to_find_the_newest` | integration |
| `list_mergecraft_reviews` oldest-first | `…::test_list_mergecraft_reviews_returns_oldest_first` | integration |
| `list_mergecraft_reviews` filters other authors | `…::test_list_mergecraft_reviews_drops_marker_reviews_from_other_authors` | integration |
| Existing checkpoint/round/incremental behaviour | `tests/mcp/test_checkout.py` (existing `last_reviewed_sha_*`, `test_incremental_*`) | unit + integration (guards) |

### TB-D8 — instruction files read only inside the resolved repo root

| Scenario | Tests | Layer |
| --- | --- | --- |
| Out-of-repo symlinked file not discovered | `tests/context/test_instruction_discovery.py::test_out_of_repo_symlinked_instruction_is_not_discovered` | unit |
| Out-of-repo symlinked file not read into the prompt | `…::test_out_of_repo_symlinked_instruction_is_not_read` | unit |
| Skip recorded in the bundle's `refusals` | `…::test_out_of_repo_symlinked_instruction_is_recorded_in_refusals` | unit |
| Out-of-repo symlinked directory not walked | `…::test_symlinked_directory_outside_repo_is_not_walked` | unit (guard) |
| In-repo symlink still works | `…::test_in_repo_symlinked_instruction_still_works` | unit (guard) |

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
| Explicit CLI `producer=` keeps whole-index semantics | `…::test_explicit_producer_keeps_whole_index_semantics` | integration (guard) |

### TB-D12 — every linked-repo omission is in the payload

| Scenario | Tests | Layer |
| --- | --- | --- |
| Ungranted entry appears in `linkedRepoOmitted` | `tests/xrepo/test_review_change_set.py::test_ungranted_entry_appears_in_linked_repo_omitted` | integration |
| Unreachable previous pin is an omission, not a full index | `…::test_unreachable_previous_pin_is_an_omission_not_a_full_index` | integration |

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

## Pinned implementation seams

These are the names the tests target; TB2–TB5 must expose them.

| Seam | Module | Consumed by |
| --- | --- | --- |
| `bind_target_pull_request(event, pull)` | `mergecraft.config.trust_policy` | TB-D2 tests |
| `is_fork_pull_request(event)` (extended) | `mergecraft.config.trust_policy` | TB-D1/D3 tests |
| `expected_publisher_logins(ctx)`, `is_mergecraft_authored(item, *, publishers)` | `mergecraft.review.authorship` (new) | TB-D7 tests |
| `list_mergecraft_reviews(ctx, *, pull_number)` | `mergecraft.mcp.checkout` | TB-D7 tests |
| `last_reviewed_sha(..., publishers=)`, `review_round_index(..., publishers=)` | `mergecraft.mcp.checkout` | TB-D7 tests |
| `review_linked_repos(..., base_manifest=)` | `mergecraft.xrepo.review` | TB-D11 tests |
| `attach_linked_repo_review(..., base_manifest=)` + `linkedRepoOmitted` | `mergecraft.review.linked_repos` | TB-D12 tests |

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
| TB4 | `green after TB4:` | `tests/context/test_instruction_discovery.py`, `tests/utils/test_instructions.py`, `tests/cli/test_local_env_loader.py` | still xfail (pending TB4) |
| TB5 | `green after TB5:` | `tests/xrepo/test_linked_repos.py`, `tests/xrepo/test_review_change_set.py` | still xfail (pending TB5) |

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
  tests/review/test_authorship.py \
  tests/context/test_instruction_discovery.py \
  tests/utils/test_instructions.py \
  tests/cli/test_local_env_loader.py \
  tests/xrepo/test_linked_repos.py \
  tests/xrepo/test_review_change_set.py
make lint
make typecheck
```
