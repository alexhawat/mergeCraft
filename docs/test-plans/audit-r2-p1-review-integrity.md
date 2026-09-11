# Test plan — audit-r2 lane A: P1 review integrity (RA1)

Plan: [`.ignorelocal/waves/20-audit-r2-a-p1-review-integrity-wave-plan.md`](../../.ignorelocal/waves/20-audit-r2-a-p1-review-integrity-wave-plan.md)
Owner: `test-creator`. Wave RA1 authors the entire RED suite for RA2–RA6; each
impl wave flips its own slice green (D13b). All RA1 `xfail(strict=False)`
markers were removed in the RA7 strictness sweep — see **RA1.7** below.

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
| Author-family prose is **not** a security signal (RA3 regression) | `tests/findings/test_security_vocabulary.py` | `test_security_auth_forms_infer_security_category` (×8), `test_unauth_forms_infer_security_category` (×2), `test_author_family_prose_does_not_infer_security_category` (×8) |
| An author-family word does not cross a blocking boundary (D5/D15) | `tests/findings/test_severity_impact_pairs.py` | `test_author_family_pair_agrees_on_severity` (×4), `test_style_nit_with_authors_tail_is_not_raised_to_blocking`, `test_style_nit_with_authorship_in_the_core_is_not_raised_to_blocking`, `test_docs_nit_with_authoritative_tail_is_not_raised_to_blocking`, `test_correctness_impact_keeps_its_asserted_severity_with_an_authors_tail` |
| No impact-preserving lexical change crosses a blocking boundary (property) | `tests/findings/test_severity_property.py` | `test_no_impact_preserving_lexical_change_crosses_a_blocking_boundary` |
| Inference → cap → `BLOCKING_SEVERITIES` → `decide_approval` (D14) | `tests/findings/test_severity_end_to_end.py` | `test_critical_security_finding_reaches_decide_approval_as_blocking` |

### Property tests and their corpus

`tests/findings/test_severity_property.py` is the only Hypothesis property in
this lane's slice. It draws from two fixed corpora in
`tests/findings/fixtures/severity_pairs.py`:

- `IMPACT_STATEMENTS` — eight `(severity, impact)` rows: six security impacts
  asserted `Critical` and two correctness impacts asserted `Major`.
- `INCIDENTAL_TOKENS` — thirteen tokens: six docs/style tokens (`see README`,
  `see the comment`, `style`, `naming`, `typo`, `docstring`) plus seven
  author-family prose tokens (`authors`, `authoring`, `authored`, `authorship`,
  `authoritative`, `authority`, `authorities`).

For every sampled `(impact, incidental)` pair the test runs the paraphrased
message through the real `infer_category_from_message` + `apply_severity_rubric`
composition and asserts the incidental member's severity equals the control's.
`max_examples=40`, `deadline=None`.

### RA1.2 follow-up — author-family regression (RA3)

RA3's stem relaxation (`\bauth(?!or\b)\w*`) still matched `authors`,
`authoring`, `authored`, `authoritative`, `authority`, `authorities` and
`authorship`, so an incidental prose word could infer `Security & Privacy` and
— because the security lane is non-capping (D5) — keep a style/docs finding at
`Critical`/`Major` and block approval. The follow-up narrows the lookahead to
`\bauth(?!or(?!iz))\w*` and these tests pin the observable contract:

- `tests/findings/test_security_vocabulary.py` — the eight security `auth`
  forms still infer Security, the two `unauth` forms keep their own pattern
  (guard), and the eight `author`-family prose forms infer the same non-security
  category as an author-free control (the exact other category is not pinned).
- `tests/findings/test_severity_impact_pairs.py` — matched author-family pairs
  (`AUTHOR_FAMILY_PAIRS` in `tests/findings/fixtures/severity_pairs.py`): a
  style nit and a docs nit with/without an incidental author word must agree on
  a **non-blocking** severity and reach `decide_approval` as `success`, while a
  genuine correctness impact keeps its asserted `Critical`.
- `tests/findings/test_severity_property.py` — the property corpus now samples
  the author-family tokens (`INCIDENTAL_TOKENS`).

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
- Severity corpus: `tests/findings/fixtures/severity_pairs.py` (`SEVERITY_PAIRS`,
  `IMPACT_STATEMENTS`, `INCIDENTAL_TOKENS`, and the RA1.2 follow-up
  `AUTHOR_FAMILY_PAIRS` / `AuthorFamilyPair`).
- `docs/test-plans/audit-r2-p1-review-integrity.md` (this file).

### Pre-existing tests whose expectation was inverted

| Test | Owning wave | Change |
| --- | --- | --- |
| `tests/mcp/test_reviewer_resilience_degraded_scope.py::test_get_commit_info_registers_scope_for_pr_head` → renamed `test_get_commit_info_does_not_register_scope_for_pr_head` | RA5 (N3) | The old expectation pinned `get_commit_info` registering review scope for the PR head as intended behaviour. The contract inverted: the tool is `REPOSITORY_READ` and must not advance `review_phase` or set `primary.diff_path`. Docstring rewritten; the temporary `xfail(strict=False)` was removed in the RA7 sweep (RA1.7). |

### Identified but not modified (lane B ownership)

`tests/findings/test_agent_adapter.py::test_category_hints_match_whole_tokens_not_substrings`
is lane B's file (Parallel contract: `tests/findings/test_agent_adapter*.py`).
Its first assertion pins `infer_category_from_message("Update the author bio copy")`
to `Functional Correctness`. If RA3 relaxes `\bauth\b` to `\bauth\w*\b`, that
pattern also matches `author`, so the assertion would flip. RA3 must either
narrow the stem (exclude `author`) or coordinate the expectation change with
lane B before Final — this plan does not touch the file.
The RA1.2 follow-up above narrows the lookahead further so the whole `author`
family (`authors`, `authority`, `authoritative`, …) stays non-security; lane B's
single-`author` assertion remains satisfied.

No pre-existing test pins a *first-survivor* dedupe severity: `tests/findings/test_dedup.py`
and `tests/analyzers/test_cluster.py` assert collapse counts, not which member
survives. That gap is why the RA1.3 survival cases are new.

## RA1.7 — strictness sweep (RA7 Step 1)

After RA2–RA6 all landed, every RA1 `xfail(strict=False)` marker on the
RA1.1–RA1.5 slices was removed. The tests are ordinary passing tests; **no
`xfail` remains in the lane**. D13b is closed: the ratchet (`tests/conftest.py`
session hook → `scripts/check_xpass.py`) reports **0 xpassed**.

| Slice | File | `pytest.mark.xfail` declarations removed |
| --- | --- | --- |
| RA1.1 | `tests/security/test_fork_credential_invariant.py` | 1 |
| RA1.1 | `tests/security/test_credential_authority_drift.py` | 1 |
| RA1.1 | `tests/agents/test_codex_auth_indexed.py` | 1 |
| RA1.2 | `tests/findings/test_severity_impact_pairs.py` | 1 |
| RA1.2 | `tests/findings/test_security_vocabulary.py` | 1 |
| RA1.2 | `tests/findings/test_severity_property.py` | 1 |
| RA1.2 | `tests/findings/test_severity_end_to_end.py` | 1 |
| RA1.3 | `tests/analyzers/test_cluster_severity.py` | 1 |
| RA1.3 | `tests/analyzers/test_cluster_permutation.py` | 1 |
| RA1.3 | `tests/findings/test_dedup_severity.py` | 1 |
| RA1.4 | `tests/mcp/test_analyzer_rerun_retention.py` | 1 |
| RA1.4 | `tests/mcp/test_commit_info_scope.py` | 1 |
| RA1.4 | `tests/mcp/test_reviewer_resilience_degraded_scope.py` | 1 |
| RA1.5 | `tests/utils/test_offline_diff_untracked.py` | 1 |
| RA1.5 | `tests/utils/test_offline_diff_coverage_limits.py` | 1 |

The 15 declarations decorated 48 test functions, collecting as **54 test
cases** (parametrization expands the RA1.1/RA1.5 rows). `import pytest` was
dropped from the eight files that used it only for the marker; in
`tests/agents/test_codex_auth_indexed.py` the surviving `pytest.MonkeyPatch`
annotation moved under `TYPE_CHECKING`.

### Fixture repairs in the same commit (test-owned)

1. `tests/utils/test_offline_diff_coverage_limits.py::_init_repo` created the
   repo with `repo.mkdir()`, but callers pass `tmp_path/"clean"` /
   `tmp_path/"excluded"`, whose parents did not exist — the fixture raised during
   setup and the D12 case xfailed without ever exercising the product.
   `mkdir(parents=True)` fixes it. The test now asserts the distinction it was
   written for: a clean repo returns `empty is True` with **no** coverage
   limitations, while an all-excluded diff (`huge.py` over the byte cap) reports
   a coverage limitation, so the two empty states are distinguishable.
2. `tests/instructions/test_offline_review_fence.py::_make_diff_repo` initialised
   the reviewed repository at `tmp_path` itself, and both tests wrote their prompt
   capture files into that same directory. Under RA6's D11 behaviour the run-1
   capture became an eligible untracked addition, so run 2's diff gained a second
   file and the outside-fence prompt diverged — a fixture artifact, not a fence
   regression. The repo now lives at `tmp_path/repo` and the captures at
   `tmp_path/*.txt`, outside the reviewed tree. Both runs materialize the same
   one-file diff and the test asserts the fenced-body-only difference it intends.

### Non-lane xfails

Twelve `xfail` tests elsewhere in `tests/` (tracing/evals/evidence waves) remain
and are genuine xfails; they are outside lane A and untouched. The repo-wide
ratchet is clean: **0 xpassed**.
