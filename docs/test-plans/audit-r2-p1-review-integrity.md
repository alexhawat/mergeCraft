# Test plan — audit-r2 lane A: P1 review integrity (RA1)

Plan: [`.ignorelocal/waves/20-audit-r2-a-p1-review-integrity-wave-plan.md`](../../.ignorelocal/waves/20-audit-r2-a-p1-review-integrity-wave-plan.md)
Owner: `test-creator`. Wave RA1 authors the entire RED suite for RA2–RA6; each
impl wave flips its own slice from `xfail(strict=False)` to green (D13b).

Baseline for every RED assertion: `origin/main @ 059634b0`, reproduced by RA0 in
`.ignorelocal/waves/evidence/ra0-baseline.txt`.

## RA1.1 — credential authority (RA2: N1 / N19 / N21)

| Contract (D-row) | Test file | Cases |
| --- | --- | --- |
| Fork invariant rejects indexed credentials before dispatch (D3, N1) | `tests/security/test_fork_credential_invariant.py` | `test_indexed_oauth_credential_is_rejected_on_fork_head`, `test_indexed_device_code_credential_is_rejected_on_fork_head`, `test_indexed_cloud_chain_credentials_are_rejected_on_fork_head`, `test_untrusted_tier_filtering_does_not_reintroduce_the_credential` |
| Flat spellings and same-repo events are untouched (guards) | same file | `test_flat_legacy_spellings_stay_rejected`, `test_same_repo_event_with_every_auth_kind_is_permitted` |
| Both consumer sets derive from the provider registry (D2) | `tests/security/test_credential_authority_drift.py` | `test_fork_invariant_covers_every_registry_credential_name`, `test_agent_env_filter_covers_every_registry_credential_name`, `test_indexed_registry_credential_is_rejected_on_fork_head`, `test_google_api_key_is_present_in_both_sets` |
| Indexed Codex credential reaches the run home's `auth.json` (D4, N19) | `tests/agents/test_codex_auth_indexed.py` | `test_indexed_codex_auth_json_writes_run_home_auth_file`, `test_flat_codex_auth_json_still_writes_auth_file` (control), `test_indexed_and_flat_conflict_resolves_to_the_registry_credential`, `test_setup_codex_auth_does_not_read_ambient_os_environ` |

The drift tests derive the registry's credential names from
`credential_env_keys_for_entry` / `_credential_suffixes_for_entry` over one
entry per `authKind` (`api_key`, `oauth`, `device_code`, `cloud_chain` bedrock,
`cloud_chain` vertex) and both spellings, so a provider added to one consumer
and not the other fails with a named list.

## RA1.2 — impact-based severity (RA3: N4 / N20)

| Contract (D-row) | Test file | Cases |
| --- | --- | --- |
| Matched-paraphrase pairs agree (D15) | `tests/findings/test_severity_impact_pairs.py` | the six r2 rows (`readme`, `comment`, `style`, `naming`, `typo`, correctness-`comment`) plus `test_control_paraphrases_retain_their_asserted_severity` |
| Auth stems and named classes infer Security (D6) | `tests/findings/test_security_vocabulary.py` | `test_auth_stems_infer_security_category`, `test_named_security_classes_infer_security_category`, `test_genuine_style_nit_is_still_capped` (deflation guard) |
| No impact-preserving lexical change crosses a blocking boundary (property) | `tests/findings/test_severity_property.py` | `test_no_impact_preserving_lexical_change_crosses_a_blocking_boundary` |
| Inference → cap → `BLOCKING_SEVERITIES` → `decide_approval` (D14) | `tests/findings/test_severity_end_to_end.py` | `test_critical_security_finding_reaches_decide_approval_as_blocking` |

### Property tests and their corpus

`tests/findings/test_severity_property.py` is the only Hypothesis property in
this lane's slice. It draws from two fixed corpora in
`tests/findings/fixtures/severity_pairs.py`:

- `IMPACT_STATEMENTS` — eight `(severity, impact)` rows: six security impacts
  asserted `Critical` and two correctness impacts asserted `Major`.
- `INCIDENTAL_TOKENS` — six docs/style tokens (`see README`, `see the comment`,
  `style`, `naming`, `typo`, `docstring`).

For every sampled `(impact, incidental)` pair the test runs the paraphrased
message through the real `infer_category_from_message` + `apply_severity_rubric`
composition and asserts the incidental member's severity equals the control's.
`max_examples=40`, `deadline=None`.

`tests/analyzers/test_cluster_permutation.py` and
`tests/findings/test_dedup_severity.py::test_dedupe_result_is_permutation_invariant`
are exhaustive permutation properties (no Hypothesis) over small fixed input
sets, because the audit's order-dependence is small-n.

## RA1.3 — severity-preserving collapse (RA4: N5)

| Contract (D-row) | Test file | Cases |
| --- | --- | --- |
| Corroboration cannot lower a blocker (D7) | `tests/analyzers/test_cluster_severity.py` | `test_major_alone_and_major_plus_minor_duplicate_gate_identically`, `test_corroboration_cannot_lower_should_verify` |
| Wording vs severity are separate selections (D8) | same file | `test_canonical_keeps_agent_wording_but_not_a_weaker_severity` |
| Cluster is permutation-invariant | `tests/analyzers/test_cluster_permutation.py` | `test_cluster_result_is_permutation_invariant` |
| Semantic dedupe keeps the strongest survivor | `tests/findings/test_dedup_severity.py` | `test_semantic_dedupe_keeps_the_strongest_survivor`, `test_dedupe_result_is_permutation_invariant`, `test_evidence_from_discarded_members_is_retained`, `test_kept_indices_still_point_at_the_surviving_row` |

`test_kept_indices_still_point_at_the_surviving_row` is the cross-lane contract:
lane B's RB6 (`findings/agent_adapter._apply_row_level_precision`) realigns
original rows on `kept_indices`, so the index must name the row actually kept.

## RA1.4 — canonical scope and evidence retention (RA5: N2 / N3)

| Contract (D-row) | Test file | Cases |
| --- | --- | --- |
| Retention by covered scope (D9) | `tests/mcp/test_analyzer_rerun_retention.py` | `test_clean_partial_rerun_does_not_erase_a_prior_blocker`, `test_same_scope_rerun_supersedes` (guard), `test_unavailable_analyzer_rerun_does_not_supersede`, `test_no_match_rerun_does_not_supersede`, `test_concurrent_overlapping_runs_do_not_lose_findings`, `test_terminal_approve_stays_rejected_after_a_partial_clean_rerun` |
| A metadata read may not register scope (D10) | `tests/mcp/test_commit_info_scope.py` | `test_get_commit_info_does_not_change_canonical_scope`, `test_get_commit_info_still_returns_a_usable_diff_file` (control), `test_admissible_changed_files_survive_head_inspection`, `test_blast_radius_survives_head_inspection`, `test_inline_anchors_survive_head_inspection` |

`test_concurrent_overlapping_runs_do_not_lose_findings` drives two overlapping
scopes through `asyncio.gather`. The two-commit PR fixture lives in
`tests/mcp/support_two_commit_pr.py`: commit 1 touches `security.py`, commit 2
touches `docs.md`, and a recording SCM returns per-commit patches.

## RA1.5 — untracked source in default local review (RA6: N7)

| Contract (D-row) | Test file | Cases |
| --- | --- | --- |
| Default materialization includes eligible untracked adds (D11) | `tests/utils/test_offline_diff_untracked.py` | `test_default_materialization_includes_an_untracked_addition`, `test_mixed_tracked_and_untracked_changes_include_both`, `test_unicode_quoted_path_is_included` |
| Staged and commit-range semantics are unchanged (guards) | same file | `test_staged_mode_semantics_are_unchanged`, `test_commit_range_semantics_are_unchanged` |
| Every exclusion is visible | same file | `test_gitignored_file_is_excluded`, `test_oversized_untracked_file_is_excluded_and_reported`, `test_binary_untracked_file_is_excluded_and_reported`, `test_symlink_is_excluded` |
| Empty states are distinguishable (D12) | `tests/utils/test_offline_diff_coverage_limits.py` | `test_exclusions_are_reported_as_review_coverage_limitations`, `test_empty_because_nothing_changed_is_distinguishable_from_empty_because_excluded` |

All RA1.5 cases use real `git init` repositories in `tmp_path`; none mock the
diff runner, because the defect is in what `git diff` omits.

## RA1.6 — fixtures and inverted expectations

- Two-commit PR fixture: `tests/mcp/support_two_commit_pr.py`.
- Severity corpus: `tests/findings/fixtures/severity_pairs.py`.
- `docs/test-plans/audit-r2-p1-review-integrity.md` (this file).

### Pre-existing tests whose expectation was inverted

| Test | Owning wave | Change |
| --- | --- | --- |
| `tests/mcp/test_reviewer_resilience_degraded_scope.py::test_get_commit_info_registers_scope_for_pr_head` → renamed `test_get_commit_info_does_not_register_scope_for_pr_head` | RA5 (N3) | The old expectation pinned `get_commit_info` registering review scope for the PR head as intended behaviour. The contract inverted: the tool is `REPOSITORY_READ` and must not advance `review_phase` or set `primary.diff_path`. Docstring rewritten; tagged `xfail(strict=False)`. |

### Identified but not modified (lane B ownership)

`tests/findings/test_agent_adapter.py::test_category_hints_match_whole_tokens_not_substrings`
is lane B's file (Parallel contract: `tests/findings/test_agent_adapter*.py`).
Its first assertion pins `infer_category_from_message("Update the author bio copy")`
to `Functional Correctness`. If RA3 relaxes `\bauth\b` to `\bauth\w*\b`, that
pattern also matches `author`, so the assertion would flip. RA3 must either
narrow the stem (exclude `author`) or coordinate the expectation change with
lane B before Final — this plan does not touch the file.

No pre-existing test pins a *first-survivor* dedupe severity: `tests/findings/test_dedup.py`
and `tests/analyzers/test_cluster.py` assert collapse counts, not which member
survives. That gap is why the RA1.3 survival cases are new.
