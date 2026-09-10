# Test plan — audit r2 lane A: P1 review integrity

Wave plan: `.ignorelocal/waves/20-audit-r2-a-p1-review-integrity-wave-plan-b.md`

RED suite authored in **RA1** (`test-creator`). Implementation waves RA2–RA6 flip
their slice from `xfail(strict=False)` to strict green; lane B's RB6 depends on
the `kept_indices` contract in RA1.3.

## RA1.1 — credential authority (RA2)

| Contract | Test |
| --- | --- |
| Indexed OAuth rejected on fork head | `tests/security/test_fork_credential_invariant.py::test_indexed_oauth_credential_is_rejected_on_fork_head` |
| Indexed device-code rejected | `…::test_indexed_device_code_credential_is_rejected_on_fork_head` |
| Indexed cloud-chain rejected | `…::test_indexed_cloud_chain_credentials_are_rejected_on_fork_head` |
| Flat spellings stay rejected (guard) | `…::test_flat_legacy_spellings_stay_rejected` |
| Same-repo event permitted | `…::test_same_repo_event_with_every_auth_kind_is_permitted` |
| Untrusted filter is not the guard | `…::test_untrusted_tier_filtering_does_not_reintroduce_the_credential` |
| Fork invariant covers registry (D2) | `tests/security/test_credential_authority_drift.py::test_fork_invariant_covers_every_registry_credential_name` |
| Agent-env strip covers registry | `…::test_agent_env_filter_covers_every_registry_credential_name` |
| N21 GOOGLE_API_KEY drift pinned | `…::test_google_api_key_is_present_in_both_sets` |
| Indexed Codex writes auth.json | `tests/agents/test_codex_auth_indexed.py::test_indexed_codex_auth_json_writes_run_home_auth_file` |
| Flat Codex control | `…::test_flat_codex_auth_json_still_writes_auth_file` |
| Indexed wins over flat | `…::test_indexed_and_flat_conflict_resolves_to_the_registry_credential` |
| D4 resolved mapping threaded | `…::test_setup_codex_auth_does_not_read_ambient_os_environ` |

## RA1.2 — impact-based severity (RA3)

| Contract | Test |
| --- | --- |
| Matched pairs (D15) | `tests/findings/test_severity_impact_pairs.py` — corpus in `tests/findings/fixtures/severity_pairs.py` |
| Auth stems infer security | `tests/findings/test_security_vocabulary.py::test_auth_stems_infer_security_category` |
| Named security classes | `…::test_named_security_classes_infer_security_category` |
| Deflation guard survives repair | `…::test_genuine_style_nit_is_still_capped` |
| **Property (N20)** | `tests/findings/test_severity_property.py::test_no_impact_preserving_lexical_change_crosses_a_blocking_boundary` — Hypothesis over `IMPACT_STATEMENTS` × `INCIDENTAL_TOKENS` in `severity_pairs.py` |
| End-to-end composition (D14) | `tests/findings/test_severity_end_to_end.py::test_critical_security_finding_reaches_decide_approval_as_blocking` |

### Property tests (RA1.6)

| Property | Module | Corpus |
| --- | --- | --- |
| No impact-preserving lexical change crosses a blocking boundary | `tests/findings/test_severity_property.py` | `IMPACT_STATEMENTS` × `INCIDENTAL_TOKENS` in `tests/findings/fixtures/severity_pairs.py` |
| Cluster output permutation-invariant | `tests/analyzers/test_cluster_permutation.py` | Three-member cluster (Minor/Major/Critical agents) × all orderings |
| Dedupe output permutation-invariant | `tests/findings/test_dedup_severity.py::test_dedupe_result_is_permutation_invariant` | Retry-loop-timeout paraphrase pair × both orderings |

## RA1.3 — severity-preserving collapse (RA4)

| Contract | Test |
| --- | --- |
| Major + Minor gate identically | `tests/analyzers/test_cluster_severity.py::test_major_alone_and_major_plus_minor_duplicate_gate_identically` |
| D8 wording vs severity split | `…::test_canonical_keeps_agent_wording_but_not_a_weaker_severity` |
| Corroboration cannot clear verify | `…::test_corroboration_cannot_lower_should_verify` |
| Cluster permutation property | `tests/analyzers/test_cluster_permutation.py::test_cluster_result_is_permutation_invariant` |
| Dedupe keeps strongest | `tests/findings/test_dedup_severity.py::test_semantic_dedupe_keeps_the_strongest_survivor` |
| Dedupe permutation property | `…::test_dedupe_result_is_permutation_invariant` |
| Evidence retained | `…::test_evidence_from_discarded_members_is_retained` |
| `kept_indices` contract (RB6) | `…::test_kept_indices_still_point_at_the_surviving_row` |

## RA1.4 — scope and evidence retention (RA5)

| Contract | Test |
| --- | --- |
| Partial rerun retains blocker | `tests/mcp/test_analyzer_rerun_retention.py::test_clean_partial_rerun_does_not_erase_a_prior_blocker` |
| Same-scope rerun supersedes | `…::test_same_scope_rerun_supersedes` |
| Unavailable rerun does not supersede | `…::test_unavailable_analyzer_rerun_does_not_supersede` |
| No-match rerun does not supersede | `…::test_no_match_rerun_does_not_supersede` |
| Terminal approve stays rejected | `…::test_terminal_approve_stays_rejected_after_a_partial_clean_rerun` |
| Concurrent overlapping runs | `…::test_concurrent_overlapping_runs_do_not_lose_findings` |
| Commit info does not change scope | `tests/mcp/test_commit_info_scope.py::test_get_commit_info_does_not_change_canonical_scope` |
| Commit info still returns diff | `…::test_get_commit_info_still_returns_a_usable_diff_file` |
| Admissible files survive | `…::test_admissible_changed_files_survive_head_inspection` |
| Blast radius survives | `…::test_blast_radius_survives_head_inspection` |
| Inline anchors survive | `…::test_inline_anchors_survive_head_inspection` |
| Two-commit PR fixture | `tests/mcp/support_two_commit_pr.py` |

## RA1.5 — untracked source (RA6)

| Contract | Test |
| --- | --- |
| Untracked add in default materialization | `tests/utils/test_offline_diff_untracked.py::test_default_materialization_includes_an_untracked_addition` |
| Mixed tracked + untracked | `…::test_mixed_tracked_and_untracked_changes_include_both` |
| Staged guard | `…::test_staged_mode_semantics_are_unchanged` |
| Commit-range guard | `…::test_commit_range_semantics_are_unchanged` |
| Gitignored excluded + reported | `…::test_gitignored_file_is_excluded` |
| Oversized excluded + reported | `…::test_oversized_untracked_file_is_excluded_and_reported` |
| Binary excluded + reported | `…::test_binary_untracked_file_is_excluded_and_reported` |
| Symlink excluded | `…::test_symlink_is_excluded` |
| Unicode path round-trip | `…::test_unicode_quoted_path_is_included` |
| D11 coverage limitations | `tests/utils/test_offline_diff_coverage_limits.py::test_exclusions_are_reported_as_review_coverage_limitations` |
| D12 empty states distinguishable | `…::test_empty_because_nothing_changed_is_distinguishable_from_empty_because_excluded` |

## Inverted existing tests (RA1.6)

| File | Test | Change |
| --- | --- | --- |
| `tests/mcp/test_reviewer_resilience_degraded_scope.py` | `test_get_commit_info_does_not_register_scope_for_pr_head` (renamed from `test_get_commit_info_registers_scope_for_pr_head`) | Expectation inverted: metadata read must **not** register scope (`xfail` until RA5) |

No other tests under `tests/findings/`, `tests/analyzers/`, or `tests/mcp/` pinned the defective keyword-cap, first-survivor dedupe, or commit-info scope behaviour as intended.
