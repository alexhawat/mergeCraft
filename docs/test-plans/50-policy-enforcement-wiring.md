# Test plan — rules that decide something: policy-as-code at the approval gate

**Owner:** `test-creator` · **Branch:** `wave/policy-enforcement-wiring` · **Base:** `origin/main` @ `4417257a`

mergeCraft ships a policy engine that lints, tests, explains and simulates rules — and
decides nothing. `evaluate_enforcement` maps four enforcement modes onto the approval gate
with care and has no production caller, so a repository that writes a `blocking` rule still
gets an approval over the violation. Meanwhile the rules that judge a pull request arrive
from the pull request itself, the CLI silently falls back to shipped packs that assume a
detector nothing implements, and `required` rules block without saying what is missing.

This suite pins the wiring. It is written first, against the contracts in the wave plan,
and it is **red until the implementation lands**: every test below fails for the behaviour
it names, none is skipped, and none carries an `xfail` — the implementation wave must make
every assertion pass without touching this file.

Three rules the suite enforces throughout:

* **One gate, not two.** Policy enters as findings through the existing predicate. A row
  that reaches one approval seam and not the others is the defect, not the fix.
* **Fail closed, and say why.** A rule the run cannot evaluate blocks; a rules file that
  does not parse blocks; every row names the rule, the files, the source and its digest,
  and what is missing.
* **No rules file, no change.** A repository without `.mergecraft/policy/rules.yaml`
  reviews exactly as it does today, and the shipped packs are never loaded by review.

Verification commands:

```bash
uv run --extra dev pytest <paths> -q -n8          # collect + drive the contracts
uv run --extra dev pytest <paths> --collect-only -q  # collection diagnostic
make lint && make typecheck
```

## Names this suite pins

Implementation target for the seams this suite needs. The comments in the test modules
repeat the same list.

| Surface | Name | Shape |
| --- | --- | --- |
| Loader | `mergecraft.policy.review.load_repo_policy(root, *, operator_owned=False)` | reads `.mergecraft/policy/rules.yaml` and `exceptions.yaml`; no file means no rules |
| Source resolution | `mergecraft.policy.review.load_review_policy(snapshot, *, base_sha, changed_paths)` | applies the operator-owned / base-commit / head-unchanged rule |
| Evaluator | `mergecraft.policy.review.evaluate_review_policy(snapshot, *, changed_paths, org, repo, base_ref, exceptions_trusted, now)` | one `Finding` per triggered rule |
| Run integration | `mergecraft.policy.review.ensure_policy_evaluated(ctx)` | fills `ToolState.policy_evaluation` once per diff path; reads a `ToolContext` or an `AgentRunContext` |
| Summary | `mergecraft.policy.review.policy_summary_block(findings)` | `""` for no rows; otherwise a short *Policy rules* block |
| Snapshot | `PolicySnapshot` | `rules`, `exceptions`, `source`, `source_path` (repo-relative), `sha256`, `load_error`, `repo_root`, `operator_owned` |
| Evaluation | `PolicyEvaluation` | `diff_path`, `rows` |
| Tool state | `ToolState.policy_evaluation` | `PolicyEvaluation \| None`; `None` means not yet evaluated |
| Validation | `ValidationState.policy_findings` | tuple of policy rows; withdrawal never filters it |
| Scoping | `resolve_effective_rules(..., unresolved=frozenset())` | an unresolved dimension matches; layer depth still comes from the declared scope |
| Settings | `RepoSettingsSnapshot.policy` | `PolicySnapshot \| None`; carried through `rebaseline_repo_settings_snapshot` |
| Row shape | policy `Finding` | `tool="policy"`, `introduced_by_pr="true"`, `rule_id` = the rule or the reserved `policy.*` code |
| Reserved codes | `policy.unreadable`, `policy.unevaluated`, `policy.unverifiable_source`, `policy.changed_in_pr` | `rule_id` values for the rows the review synthesises |
| Evidence contract | every policy row | names the source (`operator-snapshot`, `base:<full sha>`, `head (unchanged)`), carries a `sha256:` digest and `.mergecraft/policy/rules.yaml`, the matched paths, and any unresolved scope dimension |

`base:<sha>` uses the full 40-character commit id, so a row is reproducible from the git
object it was read from.

## Contract → test map

### The rules file is the opt-in

| Behaviour | Layer | Test |
| --- | --- | --- |
| No `rules.yaml` ⇒ no rows, and the shipped packs are not loaded (a shipped blocking rule would have fired on the changed path) | unit | `tests/policy/test_review_evaluation.py::test_no_rules_file_produces_no_rows_and_loads_no_shipped_packs` |
| An unparseable `rules.yaml` (invalid YAML or schema) ⇒ one `Major` `policy.unreadable` row naming the file and the error | unit | `…::test_a_policy_file_that_does_not_parse_is_one_blocking_major_row[rules-invalid-yaml]`, `…[rules-schema]` |
| An unparseable `exceptions.yaml` ⇒ the same, naming that file | unit | `…::test_a_policy_file_that_does_not_parse_is_one_blocking_major_row[exceptions-schema]` |
| A `rules.yaml` that exists but cannot be read (`PermissionError`) ⇒ one `Major` `policy.unreadable` row naming the file and the error, through the loader | unit | `tests/policy/test_review_run_path.py::test_an_unreadable_rules_file_is_one_blocking_major_row` |
| The same unreadable file on the run path ⇒ the same row, not a review with no rules | integration | `…::test_the_run_path_records_an_unreadable_rules_file` |
| The snapshot digest is the SHA-256 of the bytes read, and the row publishes it | unit | `…::test_the_snapshot_digest_is_the_sha256_of_the_rules_document` |
| A diff that cannot be read once review scope exists ⇒ one `Major` `policy.unevaluated` row naming the path | integration | `tests/mcp/test_submit_review_verdict_policy.py::test_an_unreadable_diff_is_one_blocking_major_unevaluated_row` |

### A rule triggers on a changed file in its scope

| Behaviour | Layer | Test |
| --- | --- | --- |
| A changed file inside a `blocking` rule's scope ⇒ one `Major`-or-worse row, `tool="policy"`, `introduced_by_pr="true"`, and `decide_approval` fails | unit | `tests/policy/test_review_evaluation.py::test_a_changed_file_inside_a_blocking_rules_scope_is_one_policy_row` |
| A changed file outside the scope ⇒ no row | unit | `…::test_a_changed_file_outside_the_scope_produces_no_row` |
| Three matched files ⇒ one row; the message is sorted, counts the files and is capped; evidence lists every matched path; re-evaluation in another order is identical | unit | `…::test_three_matched_files_produce_one_row_with_a_deterministic_message` |
| `advisory` / `warning` / `required` / `blocking` produce the engine's severities, asserted against `evaluate_enforcement` rather than literals | unit | `…::test_each_enforcement_mode_uses_the_engines_gate_severity[*]` |
| An `advisory` rule over a declared blocker is recorded as `Trivial` and does not close the gate | unit | `…::test_an_advisory_rule_is_recorded_and_does_not_block` |
| A `required` rule with keys blocks at `Major` and names every missing key | unit | `…::test_a_required_rule_names_every_missing_evidence_key` |
| The submitted summary carries one *Policy rules* block naming rule, mode, gate severity and the missing key | unit | `…::test_a_summary_block_is_empty_without_rows_and_names_each_row` |

### Exceptions are bounded waivers, filtered by rule

| Behaviour | Layer | Test |
| --- | --- | --- |
| An exception for rule A does not waive rule B | unit | `…::test_an_exception_for_one_rule_does_not_waive_another` |
| An expired exception waives nothing | unit | `…::test_an_expired_exception_waives_nothing` |
| A partial waiver leaves the rule triggered on the unwaived paths | unit | `…::test_a_partial_waiver_leaves_the_rule_triggered` |
| A full waiver becomes a `Trivial` row naming the exception id, approver and expiry | unit | `…::test_a_full_waiver_is_recorded_as_a_trivial_row` |
| An exception set that is not operator-owned waives nothing | unit | `…::test_an_untrusted_exception_set_waives_nothing` |

### The rules that judge a pull request come from a source it cannot write

| Behaviour | Layer | Test |
| --- | --- | --- |
| A PR that adds a waiver for its own violation is still judged by the base rule, and gets the advisory change row | integration | `tests/policy/test_review_evaluation.py::test_a_pull_request_exception_is_ignored_when_policy_comes_from_the_base_commit` |
| A PR that downgrades a rule is judged by the base rule | integration | `…::test_a_pull_request_that_downgrades_a_rule_is_judged_by_the_base_rule` |
| A PR that deletes `rules.yaml` is judged by the base rules | integration | `…::test_a_pull_request_that_deletes_rules_yaml_is_judged_by_the_base_rules` |
| The run path (`ensure_policy_evaluated`) resolves the base copy when the PR deletes `rules.yaml`, and still adds the advisory change row | integration | `tests/policy/test_review_run_path.py::test_a_pr_that_deletes_rules_yaml_is_judged_by_the_base_rules` |
| The terminal submission over a deleting PR records `request_changes`, not an unqualified `approve` | functional | `…::test_the_submission_over_a_deleting_pr_is_not_an_unqualified_approve` |
| Rows name `base:<sha>` and their digest | integration | `…::test_base_commit_rows_name_the_source_and_the_digest` |
| An operator-owned snapshot governs, whatever the base commit says | integration | `…::test_an_operator_owned_snapshot_ignores_the_base_commit` |
| Base unreadable and the diff touches `.mergecraft/policy/**` ⇒ `Major` `policy.unverifiable_source`; nothing from the PR head is evaluated | integration | `…::test_an_unreadable_base_with_a_policy_change_fails_closed` |
| Base unreadable and the PR deleted `rules.yaml` ⇒ the run path records that same blocking `policy.unverifiable_source` row instead of an empty population | integration | `tests/policy/test_review_run_path.py::test_a_deleting_pr_with_an_unreadable_base_fails_closed` |
| Base unreadable and the diff leaves the policy tree alone ⇒ the head copy is used, labelled `head (unchanged)` | integration | `…::test_an_unreadable_base_without_a_policy_change_uses_the_head_copy` |
| Touching `.mergecraft/policy/**` always adds an advisory change row that does not block and says it applies after merge | integration | `…::test_a_policy_change_in_the_pr_adds_an_advisory_row` |
| The settings snapshot carries the policy; a rebaseline after checkout keeps the run-start rules; an operator-owned capture is recorded as such | integration | `tests/mcp/test_review_settings_snapshot.py::test_the_snapshot_carries_the_repository_policy`, `…::test_rebaseline_preserves_the_run_start_policy`, `…::test_a_pull_request_target_capture_is_operator_owned` |

### Dimensions a review cannot resolve match, and the row says so

| Behaviour | Layer | Test |
| --- | --- | --- |
| A `language`-scoped rule applies over a matched path and names the unresolved dimension | unit | `tests/policy/test_review_evaluation.py::test_a_language_scoped_rule_applies_and_names_the_unresolved_dimension` |
| A `symbol`-scoped rule applies and names the unresolved dimension | unit | `…::test_a_symbol_scoped_rule_applies_and_names_the_unresolved_dimension` |
| With the base branch unknown a `branch`-scoped rule applies and says so; a resolved, different branch still excludes it | unit | `…::test_a_branch_scoped_rule_applies_when_the_base_branch_is_unknown`, `…::test_a_branch_scoped_rule_does_not_apply_on_a_different_branch` |
| `resolve_effective_rules` gains `unresolved` without changing its default | unit | `…::test_resolve_effective_rules_treats_unresolved_dimensions_as_matching` |
| Two rules with the same id at repo and symbol layers ⇒ one row, from the deeper rule | unit | `…::test_the_deeper_layer_wins_for_the_same_rule_id` |

### The terminal submission

| Behaviour | Layer | Test |
| --- | --- | --- |
| A triggered `blocking` rule over an `approve` records `request_changes`; the row is recorded once; the summary carries the block | functional | `tests/mcp/test_submit_review_verdict_policy.py::test_a_blocking_rule_turns_an_approve_into_request_changes` |
| Advisory rows keep the `approve` and stay in the record | functional | `…::test_an_advisory_row_is_recorded_and_the_approve_stands` |
| Withdrawing the policy fingerprint does not unblock `approve` | functional | `…::test_the_agent_cannot_withdraw_a_policy_fingerprint` |
| `create_pull_request_review` with `approved` over a blocking rule is rejected and posts nothing | functional | `…::test_approve_through_create_pull_request_review_is_rejected` |
| Post-run revalidation sees the policy population | functional | `…::test_post_run_revalidation_sees_the_policy_population` |
| Re-submitting the same payload is idempotent: same id, one row | functional | `…::test_resubmitting_an_identical_payload_stays_idempotent` |
| Policy never relaxes a verdict: agent findings that normalize to empty plus one advisory policy row still record `request_changes` | functional | `…::test_an_advisory_policy_row_never_relaxes_request_changes` |
| `ValidationState` carries the rows from both builders, and withdrawal never removes them | integration | `…::test_validation_state_carries_policy_rows_outside_withdrawal` |
| One evaluation per diff path, cached on `ToolState`; a re-scoped diff evaluates again | integration | `…::test_policy_evaluation_is_computed_once_per_diff_path`, `…::test_a_new_diff_path_is_evaluated_again` |
| No rules file ⇒ the recorded submission is identical to one with no policy tree at all | functional | `…::test_no_rules_file_records_the_same_submission_as_before` |

### The packet and the approval check

| Behaviour | Layer | Test |
| --- | --- | --- |
| `load_run_findings_with_drops` includes the policy row exactly once | integration | `tests/evidence/test_run_findings_policy.py::test_the_policy_row_reaches_the_gate_loader_exactly_once` |
| The backfill does not duplicate a policy row into `agent_findings`, and the loader still sees it once | integration | `…::test_backfill_does_not_duplicate_the_policy_row_into_agent_findings` |
| `decide_approval(packet)` fails over a blocking rule and the `mergecraft-approval` check concludes `failure` | integration | `…::test_the_packet_decision_and_the_approval_check_both_fail` |

### End to end over the offline review path

| Behaviour | Layer | Test |
| --- | --- | --- |
| A scripted agent that submits `approve` on a PR that touches the guarded path, downgrades the blocking rule and waives itself still records `request_changes`; the packet carries the base commit's two rule rows plus the advisory change row, names `base:<sha>`, and never mentions the self-waiver | functional | `tests/e2e/test_policy_offline_review.py::test_offline_review_of_a_self_weakening_pr_still_requests_changes` |

### The advertised surface tells the truth

| Behaviour | Layer | Test |
| --- | --- | --- |
| The `policy` group help says review enforces the rules in `.mergecraft/policy/rules.yaml` when a changed file matches a scope, keeps the verbs, and carries no stale non-enforcement claim | functional | `tests/cli/test_policy_help_honest.py::test_policy_group_help_says_review_enforces_the_rules_file` |
| The enforcement module docstring names the mapping onto the approval gate through `policy/review.py` and drops the "nothing consumes this" sentences | unit | `…::test_enforcement_module_docstring_names_the_review_gate_mapping` |
| With no `rules.yaml`, `policy effective` says the shipped example packs are shown and review evaluates no rules until the file exists, while still listing them | functional | `tests/cli/test_policy_verbs.py::test_policy_effective_says_review_evaluates_no_rules_without_rules_yaml` |

## Run path, not only the resolver

`load_review_policy` is the resolver; the seam a review actually drives is
`ensure_policy_evaluated(ctx)`, which also reads provenance off `ToolState`
(`before_sha`, `dir`, `diff_path`) and caches one population per diff. A correct
resolver is unreachable if the run path returns early above it, so every
fail-open shape — a deleted rules file, an unreadable base, an unreadable
document — is asserted through the run path (and the terminal submission where
the gate is the subject), never only against the resolver with hand-passed
`base_sha` / `changed_paths`.

## Deliberate non-assertions

* **The engine's mapping.** `policy/enforcement.py`'s mode table is taken as written; the
  suite asserts the review path agrees with it, never that the table changed.
* **No producer for evidence keys.** `available_evidence` stays empty in review, so a
  `required` rule with keys blocks; the suite asserts the row names the keys rather than
  inventing evidence.
* **No content detector.** A rule triggers on a scope match over the full-PR diff. The
  suite never asserts a rule reads file contents.
* **No new required check, no coverage floor change, no prompt edit.** Nothing here
  constrains `modes/`, the workflow, or the check-run inventory.
* **`make test` is not made green by this suite.** The seven pre-existing tests in the
  extended files stay green; the fifty-seven new assertions are red until the
  implementation waves land, and must not be weakened to reach green.
