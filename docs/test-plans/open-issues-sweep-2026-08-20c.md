# Open issues sweep 2026-08-20c — Batch CA test plan (#350)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20c-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-2026-08-20c` @ `wave/open-issues-sweep-2026-08-20c`
Authoring wave: **W1** (Batch CA RED) · Implementation: **W2.1** (`a2c76fd9`) · Recon: **W2.2**
W3.1 impl: `16a01b47` · W3 recon: un-xfail `capabilities` + `SECURITY.md` pins

Issue #350 out of scope (honoured — no tests): MCP Bearer/auth-header gaps (#345/#346); trust tiers / privilege drop (`analyzers/trust.py`, `utils/privilege.py`).

## xfail schedule

All cross-wave markers use `@pytest.mark.xfail(..., strict=False)`.

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W2** | `test_production_registry_excludes_write_capable_modes` | `green after W2: review-only production boundary (#350)` | **PASS** — un-xfailed W2.2 |
| **W2** | `test_compute_modes_excludes_write_capable_modes` | same | **PASS** — un-xfailed W2.2 |
| **W2** | `test_static_modes_export_excludes_write_capable_modes` | same | **PASS** — un-xfailed W2.2 |
| **W2** | `test_select_mode_rejects_write_capable_names[*]` | same | **PASS** — un-xfailed W2.2 (5 names) |
| **W2** | `test_custom_config_cannot_reenable_write_capable_fix` | same (D12) | **PASS** — un-xfailed W2.2 |
| **W2** | `test_reviewer_shaped_run_cannot_edit_tracked_file[*]` | same | **PASS** — un-xfailed W2.2 |
| **W2** | `test_reviewer_shaped_run_cannot_git_commit[*]` | same | **PASS** — un-xfailed W2.2 |
| **W2** | `test_reviewer_shaped_run_cannot_git_push[*]` | same | **PASS** — un-xfailed W2.2 |
| **W2** | `test_reviewer_shaped_run_cannot_open_code_changing_pr[*]` | same | **PASS** — un-xfailed W2.2 |
| **W3** | `tests/cli/test_capabilities_cmd.py` (11 tests) | `green after W3: mergecraft capabilities manifest (#350 / D10)` | **PASS** — un-xfailed W3 recon |
| **W3** | `tests/test_security_md_review_only.py` (3 tests) | `green after W3: SECURITY.md review-only guarantee (D9 / #350)` | **PASS** — un-xfailed W3 recon |

W1.1 current-state pins (CA350a / still-accepts `select_mode`) **deleted** in W2.2.

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| CA350b | `_MODE_DEFS` is review-only (D12) | unit | happy | `tests/modes/test_review_only_boundary.py::test_production_registry_excludes_write_capable_modes` |
| CA350c | `compute_modes` / `modes` leak no write names | unit | happy | `test_compute_modes_excludes_write_capable_modes`, `test_static_modes_export_excludes_write_capable_modes` |
| CA350d | `select_mode` rejects write-capable names | integration | error | `test_select_mode_rejects_write_capable_names` |
| CA350e | Empty/unknown `select_mode` is existing behaviour (not this file) | — | — | existing `select_mode` tests if any |
| CA350f | Repo config cannot re-enable `Fix` (D12) | integration | error | `test_custom_config_cannot_reenable_write_capable_fix` |
| CA350g | Reviewer-shaped run cannot edit a tracked file | functional | error + edge (file unchanged) | `test_reviewer_shaped_run_cannot_edit_tracked_file` |
| CA350h | Reviewer-shaped run cannot `git commit` (`commit_changes`) | functional | error | `test_reviewer_shaped_run_cannot_git_commit` |
| CA350i | Reviewer-shaped run cannot `git push` (`push_branch`) | functional | error | `test_reviewer_shaped_run_cannot_git_push` |
| CA350j | Reviewer-shaped run cannot open a code-changing PR | functional | error | `test_reviewer_shaped_run_cannot_open_code_changing_pr` |
| CA350k | `git` MCP tool still does not forward `commit` | unit | already green | `test_git_mcp_tool_does_not_forward_commit` |
| CA350l | Write-mode modules remain importable (D12) | unit | happy | `test_write_mode_modules_remain_importable_as_negative_fixtures` |
| CA350m | Production catalog names are Review / IncrementalReview / Plan | unit | happy | `tests/test_modes.py::EXPECTED_MODE_NAMES` / `test_compute_modes_returns_all_built_ins` |
| CA350n | New `cli/capabilities_cmd.py` with `run` + `capabilities_manifest()` | unit | happy | `tests/cli/test_capabilities_cmd.py::test_capabilities_module_is_a_new_cli_file`, `test_capabilities_module_exports_run_and_manifest` |
| CA350o | `mergecraft capabilities` in root help; default table is review-only | functional | happy | `test_root_help_lists_capabilities_command`, `test_capabilities_help_describes_manifest`, `test_capabilities_table_states_review_only` |
| CA350p | Global `--format json` emits schema_versioned review-only manifest | functional | happy | `test_capabilities_json_uses_global_format_flag` |
| CA350q | Manifest allowed/forbidden sets; no write mode names | functional | edge | `test_capabilities_json_forbidden_covers_write_surface`, `test_capabilities_json_allowed_is_review_verbs_only`, `test_capabilities_json_modes_exclude_write_capable_names` |
| CA350r | Extra argv / unknown option → usage exit 2 | functional | error | `test_capabilities_rejects_unexpected_positional`, `test_capabilities_unknown_option_is_usage_error` |
| CA350s | `SECURITY.md` states review-only guarantee (D9) | unit | happy | `tests/test_security_md_review_only.py::test_security_md_states_review_only_guarantee` |
| CA350t | `SECURITY.md` forbids edit/commit/push/code-changing PR | unit | happy | `test_security_md_forbids_source_edits_commits_pushes_and_code_changing_prs` |
| CA350u | `SECURITY.md` allows identify/investigate/verify/explain/prioritize/suggest | unit | happy | `test_security_md_allows_identify_investigate_verify_explain_prioritize_suggest` |

Write-capable names under test: `Build`, `AddressReviews`, `Fix`, `ResolveConflicts`, `Task`.
Reviewer-shaped modes: `Review`, `IncrementalReview`.
Production modes: `Review`, `IncrementalReview`, `Plan`.

Error contract for W2 negatives: `ToolResult.is_error is True` and the message contains **`review-only`** (plus `commit` / `push` where those verbs apply). `create_pull_request` must not call `scm.post`. `commit_changes` / `push_branch` must not invoke `_run_git` with those verbs.

## Recon notes (W2.2)

- Un-xfailed every `green after W2` marker in `tests/modes/test_review_only_boundary.py`.
- Deleted W1.1 still-registered / still-accepts pins (CA350a).
- Kept D12 import fixture (`modes/Fix.py` and siblings remain importable).
- Updated `tests/test_modes.py` `EXPECTED_MODE_NAMES` to Review / IncrementalReview / Plan. Write-mode prompt pins (`Build` signed-commits, `ResolveConflicts`, `AddressReviews` withdrawn heading, `mergecraft-reviewer` on Build) render unregistered templates via `_expand_template` so D12 modules stay covered without being in the production catalog.

## Acceptance (W2.2)

- W2 negatives **PASS** (no leftover xfail, no XPASS)
- W1.1 still-registered pins gone
- `make lint` + `make typecheck` clean
- No `src/` edits; no CHANGELOG (Unreleased Security bullet already in `a2c76fd9`)

## W3 recon (`mergecraft capabilities` + SECURITY.md)

- Un-xfailed every `green after W3` marker in `tests/cli/test_capabilities_cmd.py`
  and `tests/test_security_md_review_only.py` (14 tests).
- W3.1 (`16a01b47`) already added `capabilities_cmd.py`, additive
  `app.command("capabilities")`, and the `SECURITY.md` review-only guarantee.
- CAF not started.

## Acceptance (W3 recon)

- W3 pins **PASS** (no leftover xfail, no XPASS)
- `make lint` + `make typecheck` clean
- No `src/` or `SECURITY.md` edits; CAF not marked

---

# Batch CB — wire dead packages (#351–#353)

Authoring wave: **W4** (Batch CB RED) · Implementation: **W5** `#351 pr` · **W6** `#352 requirements` · **W7** `#353 xrepo`

Helper: `tests/support/dead_package_wiring.py` (runtime import scan; `TYPE_CHECKING` and package-internal imports do not count).

Out of scope (D8 — no tests): P12–P31 / #377–#385. D6 — no README / `docs/cli.md` / `AGENTS.md` / file 7 / 20b product files.

After each impl wave, recon **deletes** the matching W4.1 current-state "unwired" pins and **un-xfails** `green after W5|W6|W7` markers (`strict=False`).

## xfail schedule (W4)

| Wave | Tests | Marker reason | Status |
|------|-------|---------------|--------|
| **W5** | `tests/pr/test_pr_wiring.py` (8 wiring + D10 pins) | `green after W5: wire mergecraft.pr (#351)` | **PASS** — un-xfailed W5 recon |
| **W6** | `tests/requirements/test_requirements_wiring.py` (12 wiring + D14 pin) | `green after W6: wire mergecraft.requirements (#352)` | **PASS** — un-xfailed W6 recon |
| **W7** | `tests/xrepo/test_xrepo_wiring.py` (8 wiring pins) | `green after W7: wire mergecraft.xrepo (#353)` | **PASS** — un-xfailed W7 recon |

W5 wiring tests (un-xfailed W5 recon): `test_pr_has_a_review_or_cli_production_call_site`, `test_pr_cli_is_a_new_cmd_module`, `test_root_help_lists_describe`, `test_describe_help_names_output_only_summary`, `test_describe_cli_emits_title_summary_walkthrough_risk_and_tests`, `test_describe_cli_does_not_write_the_reviewed_tree`, `test_production_wiring_invokes_pr_library_surfaces`, `test_similar_issues_and_changes_are_wired`, `test_unknown_describe_option_is_usage_error`.

W6 wiring tests (un-xfailed W6 recon): `test_requirements_has_a_review_or_cli_production_call_site`, `test_requirements_cli_is_a_new_cmd_module`, `test_root_help_lists_requirements`, `test_requirements_inspect_help_is_registered`, `test_requirements_explain_help_is_registered`, `test_ingest_fences_external_requirement_text_with_nonce`, `test_requirement_states_are_the_five_named_outcomes`, `test_ingest_accepts_named_requirement_sources[*]`, `test_inspect_cli_lists_states`, `test_explain_unknown_requirement_id_is_an_error`, `test_policy_may_require_requirements_evidence`.

W7 wiring tests (un-xfailed W7 recon): `test_xrepo_has_a_review_or_cli_production_call_site`, `test_xrepo_cli_is_a_new_cmd_module`, `test_root_help_lists_xrepo`, `test_xrepo_explain_help_is_registered`, `test_review_path_uses_sha_pinned_linked_repos`, `test_unauthorized_linked_repo_is_blocked_on_the_review_path`, `test_explain_unknown_finding_id_is_an_error`, `test_multi_service_fixture_reports_producer_consumer_breakage`.

## Contract matrix (W4)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| CB351a | `mergecraft.pr` has no production importer yet | unit | current | **deleted W5 recon** (`test_pr_package_has_no_production_call_site_yet`) |
| CB351b | No `cli/pr_cmd.py` / `describe_cmd.py` yet | unit | current | **deleted W5 recon** (`test_pr_cli_cmd_module_does_not_exist_yet`) |
| CB351c | `describe` absent from root help / usage-exit | functional | current | **deleted W5 recon** (`test_root_help_does_not_list_describe_yet`, `test_describe_command_is_currently_a_usage_error`) |
| CB351d | D10 root callback still owns `--format` / `--quiet` / `--color` | unit | happy | `test_d10_root_callback_still_owns_format_quiet_color`, `test_w5_does_not_fold_describe_into_root_callback` |
| CB351e | Review path or CLI imports `mergecraft.pr` | integration | happy | `test_pr_has_a_review_or_cli_production_call_site` |
| CB351f | New `cli/*_cmd.py` (not `app.py`) | unit | happy | `test_pr_cli_is_a_new_cmd_module` |
| CB351g | `mergecraft describe` help + sections | functional | happy | `test_root_help_lists_describe`, `test_describe_help_names_output_only_summary`, `test_describe_cli_emits_title_summary_walkthrough_risk_and_tests` |
| CB351h | Describe is output-only (D13) | functional | edge | `test_describe_cli_does_not_write_the_reviewed_tree` |
| CB351i | Library surfaces invoked from production | integration | happy | `test_production_wiring_invokes_pr_library_surfaces` |
| CB351j | Similar issues / similar changes wired | integration | happy | `test_similar_issues_and_changes_are_wired` |
| CB351k | Unknown describe flag → usage 2 | functional | error | `test_unknown_describe_option_is_usage_error` |
| CB352a | `mergecraft.requirements` unwired | unit | current | **deleted W6 recon** (`test_requirements_package_has_no_production_call_site_yet`) |
| CB352b | No `cli/requirements_cmd.py` / command | functional | current | **deleted W6 recon** (`test_requirements_cli_cmd_module_does_not_exist_yet`, `test_root_help_does_not_list_requirements_yet`, `test_requirements_command_is_currently_a_usage_error`) |
| CB352c | Review/CLI import + new cmd module | integration | happy | `test_requirements_has_a_review_or_cli_production_call_site`, `test_requirements_cli_is_a_new_cmd_module` |
| CB352d | `requirements inspect` / `explain` | functional | happy | `test_root_help_lists_requirements`, `test_requirements_inspect_help_is_registered`, `test_requirements_explain_help_is_registered`, `test_inspect_cli_lists_states` |
| CB352e | Ingest + nonce fence | integration | happy | `test_ingest_fences_external_requirement_text_with_nonce`, `test_ingest_accepts_named_requirement_sources` |
| CB352f | Five requirement states | unit | happy | `test_requirement_states_are_the_five_named_outcomes` |
| CB352g | Unknown requirement id | functional | error | `test_explain_unknown_requirement_id_is_an_error` |
| CB352h | D14: `decide_approval` remains the only gate | unit | current | `test_decide_approval_is_the_only_approval_gate` |
| CB352i | Policy may require requirements evidence | integration | happy | `test_policy_may_require_requirements_evidence` |
| CB353a | `mergecraft.xrepo` unwired | unit | current | **deleted W7 recon** (`test_xrepo_package_has_no_production_call_site_yet`) |
| CB353b | No `cli/xrepo_cmd.py` / command | functional | current | **deleted W7 recon** (`test_xrepo_cli_cmd_module_does_not_exist_yet`, `test_root_help_does_not_list_xrepo_yet`, `test_xrepo_command_is_currently_a_usage_error`) |
| CB353c | Review/CLI import + new cmd module | integration | happy | `test_xrepo_has_a_review_or_cli_production_call_site`, `test_xrepo_cli_is_a_new_cmd_module` |
| CB353d | `xrepo explain` | functional | happy / error | `test_root_help_lists_xrepo`, `test_xrepo_explain_help_is_registered`, `test_explain_unknown_finding_id_is_an_error` |
| CB353e | SHA-pinned linked repos on review path | integration | happy | `test_review_path_uses_sha_pinned_linked_repos` |
| CB353f | Authorization boundary (`LinkedRepoAccessError`) | integration | error | `test_unauthorized_linked_repo_is_blocked_on_the_review_path` |
| CB353g | Multi-service producer/consumer breakage fixture | functional | happy | `test_multi_service_fixture_reports_producer_consumer_breakage` |

## Acceptance (W4)

- Collection clean; current-state pins **PASS**; wiring-exists pins **XFAIL** (`strict=False`); **no XPASS**
- `make lint` + `make typecheck` clean
- No `src/` edits; W5 not started

## Recon notes (W5)

- Un-xfailed every `green after W5: wire mergecraft.pr (#351)` marker in `tests/pr/test_pr_wiring.py` (8 XPASS → real PASS).
- `test_root_help_lists_describe` now matches capabilities (`"describe" in help_text` after ANSI strip + casefold). Rich help is `│ describe`, so `^\s+describe\b` never matched.
- Deleted W4.1 current-state pins: `test_pr_package_has_no_production_call_site_yet`, `test_pr_cli_cmd_module_does_not_exist_yet`, `test_describe_command_is_currently_a_usage_error`, plus `test_root_help_does_not_list_describe_yet` (same regex would false-pass against Rich tables).
- Left W6/W7 xfails in place. D10 root-callback pins kept.
- W5.1 impl: `17b0ed2e`.

## Acceptance (W5 recon)

- W5 wiring pins **PASS** (no leftover xfail, no XPASS)
- W4.1 `#351` current-state pins gone
- W6/W7 still **XFAIL** (`strict=False`)
- `make lint` + `make typecheck` clean
- No `src/` edits; W6 not started

## Recon notes (W6)

- Un-xfailed every `green after W6: wire mergecraft.requirements (#352)` marker in `tests/requirements/test_requirements_wiring.py` (12 XPASS → real PASS; parametrize ingest sources counted in that 12).
- `test_root_help_lists_requirements` now matches describe (`"requirements" in help_text` after ANSI strip + casefold). Rich help is `│ requirements`, so `^\s+requirements\b` never matched.
- Deleted W4.1 current-state pins: `test_requirements_package_has_no_production_call_site_yet`, `test_requirements_cli_cmd_module_does_not_exist_yet`, `test_root_help_does_not_list_requirements_yet`, `test_requirements_command_is_currently_a_usage_error`.
- Left W7 xfails in place. D14 `decide_approval` pin kept.
- W6.1 impl: `d5771791`.

## Acceptance (W6 recon)

- W6 wiring pins **PASS** (no leftover xfail, no XPASS)
- W4.1 `#352` current-state pins gone
- W7 still **XFAIL** (`strict=False`)
- `make lint` + `make typecheck` clean
- No `src/` edits; W7 not started

## Recon notes (W7)

- Un-xfailed every `green after W7: wire mergecraft.xrepo (#353)` marker in `tests/xrepo/test_xrepo_wiring.py` (7 XPASS + 1 help-regex XFAIL → real PASS).
- `test_root_help_lists_xrepo` now matches requirements (`"xrepo" in help_text` after ANSI strip + casefold). Rich help is `│ xrepo`, so `^\s+xrepo\b` never matched.
- Deleted W4.1 current-state pins: `test_xrepo_package_has_no_production_call_site_yet`, `test_xrepo_cli_cmd_module_does_not_exist_yet`, `test_root_help_does_not_list_xrepo_yet`, `test_xrepo_command_is_currently_a_usage_error`.
- W7.1 impl: `c5a26137`.

## Acceptance (W7 recon)

- W7 wiring pins **PASS** (no leftover xfail, no XPASS)
- W4.1 `#353` current-state pins gone
- CB pr/requirements/xrepo wiring tests **PASS**
- `make lint` + `make typecheck` clean
- No `src/` edits; CBF not started

---

# Batch CC — evidence through memory (#354–#360)

Authoring wave: **W8** (Batch CC RED) · Implementation: **W9** `#354` · **W10** `#355` · **W11** `#356+#357` · **W12** `#358+#359` · **W13** `#360`

Helper: `tests/support/cc_batch.py`.

Out of scope honoured (no extra tests): D8 P12–P31 / #377–#385; D6 file 7 / 20b; #354 second `decide_approval()`; #355 rebuild of dedup/causality; #355→memory until W13; #356 retrieval half already shipped; #357 authoring mergeCraft AGENTS.md; #358 schema/enforcement already shipped; #359 engine widening; #360 producing dismissal codes.

Canonical impl modules the RED suite pins (W9–W13):

- W9: `mergecraft.evidence.audit`, `mergecraft.cli.evidence_cmd` (new `cli/*_cmd.py`, D10)
- W10: `mergecraft.findings.materiality`
- W11: `mergecraft.context.operator`, `instruction_discovery` extras, `mergecraft.context.external_files`
- W12: `mergecraft.policy.lifecycle`, `mergecraft.policy.packs` + `src/mergecraft/policy/packs/*.yaml`
- W13: `mergecraft.memory`

After each impl wave, recon **deletes** matching W8 current-state usage-error pins and **un-xfails** `green after W9|W10|W11|W12|W13` markers (`strict=False`).

## xfail schedule (W8)

| Wave | Tests | Marker reason | Status |
|------|-------|---------------|--------|
| **W9** | `tests/evidence/test_cc_verifier_states.py` (10) + `tests/cli/test_evidence_cmd.py` (5) | `green after W9: evidence states + CLI (#354)` | **PASS** — un-xfailed W9 recon |
| **W10** | `tests/findings/test_cc_materiality.py` (7) | `green after W10: materiality / calibration / dismissal (#355)` | **PASS** — un-xfailed W10 recon |
| **W11** | `tests/context/test_cc_search_explain.py` (8) + `tests/context/test_cc_instruction_sources.py` (6) | `green after W11: context search/explain/budgets (#356)` / `instruction sources + external files (#357)` | **PASS** — un-xfailed W11 recon |
| **W12** | `tests/policy/test_cc_lifecycle.py` (7) + `tests/policy/test_cc_packs.py` (4) | `green after W12: policy lifecycle back half (#358)` / `policy packs (#359)` | XFAIL |
| **W13** | `tests/memory/test_cc_validation.py` (9) | `green after W13: memory validation / org / effectiveness (#360)` | XFAIL |

Current-state **PASS** (not xfailed; recon deletes the usage-error rows after the matching impl wave): D14 `decide_approval` only in `agents/gates.py`; D10 root-callback pin; shipped retrieval/dedup/policy front-half files; CLI usage-error for `policy effective|simulate`, `memory validate`. `evidence` and `context search|explain` usage-error pins deleted after W9 / W11.

W8 run: **12 passed / 56 xfailed / 0 XPASS**. `make lint` + `make typecheck` clean.

## Recon notes (W9)

- Un-xfailed every `green after W9: evidence states + CLI (#354)` marker in
  `tests/evidence/test_cc_verifier_states.py` (10) and `tests/cli/test_evidence_cmd.py` (5)
  (15 XPASS → real PASS).
- `test_root_help_lists_evidence` already matches W5/W6 (`"evidence" in help_text` after
  ANSI strip + casefold). Rich help is `│ evidence`.
- Deleted W8 current-state pin `test_evidence_command_is_currently_a_usage_error`
  (evidence is registered; the usage-error pin failed after W9.1).
- Left W10–W13 xfails in place. D14 `decide_approval` and D10 root-callback pins kept.
- W9.1 impl: `b086c292`.

## Acceptance (W9 recon)

- W9 evidence pins **PASS** (no leftover xfail, no XPASS)
- W8 `#354` current-state usage-error pin gone
- W10–W13 still **XFAIL** (`strict=False`)
- `make lint` + `make typecheck` clean
- No `src/` edits; W10 not started

## Recon notes (W10)

- Un-xfailed every `green after W10: materiality / calibration / dismissal (#355)` marker in
  `tests/findings/test_cc_materiality.py` (7 XPASS → real PASS).
- Kept `test_dedup_and_causality_modules_remain_the_shipped_precision_half` (out-of-scope
  current-state pin; #355 must not rebuild dedup/causality).
- No W8 usage-error pin for materiality (none existed).
- Left W11–W13 xfails in place.
- W10.1 impl: `b2cb86c0`.
- W10 recon: `43e55f84`.

## Acceptance (W10 recon)

- W10 materiality pins **PASS** (no leftover xfail, no XPASS)
- W11–W13 still **XFAIL** (`strict=False`)
- `make lint` + `make typecheck` clean
- No `src/` edits; W11 not started

## Recon notes (W11)

- Un-xfailed every `green after W11` marker in `tests/context/test_cc_search_explain.py`
  (8) and `tests/context/test_cc_instruction_sources.py` (6) (14 XPASS → real PASS).
- Help pins already use `"search"` / `"explain"` in stripped help text (Rich tables).
- Deleted W8 current-state pins: `test_context_search_is_currently_a_usage_error`,
  `test_context_explain_is_currently_a_usage_error`,
  `test_discovery_currently_omits_gemini_copilot_and_windsurf`.
- Left W12–W13 xfails in place. Retrieval-half current-state pin kept (#356 out of scope).
- W11.1 impl: `e03a7aec`.

## Acceptance (W11 recon)

- W11 context pins **PASS** (no leftover xfail, no XPASS)
- W8 `#356/#357` current-state pins gone
- W12–W13 still **XFAIL** (`strict=False`)
- `make lint` + `make typecheck` clean
- No `src/` edits; W12 not started

## Contract matrix (W8)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| CC354a | Six verifier states | unit | happy | `test_verifier_states_are_the_six_named_outcomes` |
| CC354b | Major/Critical require packets | unit | happy | `test_medium_high_critical_findings_require_an_evidence_packet` |
| CC354c | Packet evidence kinds | unit | happy | `test_evidence_packet_supports_the_named_kinds` |
| CC354d | Unverified does not block unless policy | unit | edge | `test_unverified_findings_do_not_block_unless_policy_permits` |
| CC354e | Falsification-first rubric | unit | happy | `test_falsification_first_rubric_is_wired` |
| CC354f | Freshness / hash / completeness | unit | happy | `test_evidence_freshness_provenance_hash_and_completeness_scoring` |
| CC354g | Tool vs LLM contradiction | unit | happy | `test_contradiction_detection_between_tools_and_llm` |
| CC354h | Verification replay | unit | happy | `test_verification_replay_is_deterministic` |
| CC354i | Policy evidence by severity/path/change/rule | integration | error | `test_policy_evidence_requirements_cover_severity_path_change_type_and_rule` |
| CC354j | Verifier failure cannot promote | unit | error | `test_verifier_failure_cannot_silently_promote_a_finding` |
| CC354k | D14 no second approval path | unit | current | `test_decide_approval_remains_the_only_approval_path` |
| CC354l | New `evidence_cmd.py` + show/verify | functional | happy/error | `tests/cli/test_evidence_cmd.py` |
| CC354m | JSON export / D10 root callback | functional | happy | `test_evidence_show_json_is_exportable`, `test_w9_does_not_fold_evidence_into_root_callback` |
| CC355a | Materiality + high-impact over style | unit | happy | `test_materiality_scoring_ranks_security_above_style` |
| CC355b | Benchmark-calibrated confidence | unit | happy | `test_confidence_is_calibrated_from_benchmark_outcomes` |
| CC355c | Budgets by severity/category/file/review | unit | edge | `test_finding_budgets_cover_severity_category_file_and_review` |
| CC355d | Publication + blocking thresholds | unit | happy | `test_publication_and_blocking_thresholds_are_configurable` |
| CC355e | Dismissal reason codes | unit | happy | `test_dismissal_reason_codes_are_a_closed_set` |
| CC355f | Dismissal → eval, not memory | integration | edge | `test_dismissal_feeds_evaluation_not_durable_memory` |
| CC355g | Blocker precision > 95% gate | integration | happy | `test_precision_regression_gate_targets_blocker_precision_above_95` |
| CC356a | `context search` / `explain` | functional | happy/error | `tests/context/test_cc_search_explain.py` |
| CC356b | Relevance, specialist budgets, lazy tools | unit | happy | `test_context_relevance_scoring`, `test_context_budget_allocation_per_specialist`, `test_lazy_context_retrieval_goes_through_controlled_tools` |
| CC356c | Omission downgrade | unit | edge | `test_context_omission_reporting_downgrades_the_outcome` |
| CC356d | Retrieval quality ≠ model quality | integration | happy | `test_context_retrieval_quality_is_benchmarked_separately_from_models` |
| CC357a | GEMINI / Copilot / Windsurf / custom | integration | happy | `test_discovers_gemini_copilot_windsurf_and_custom_list` |
| CC357b | Instruction hashes + conflicts | unit | happy | `test_injected_instructions_are_hashed_into_the_run_manifest`, `test_competing_instruction_sources_are_resolved` |
| CC357c | Untrusted GEMINI fenced | functional | error | `test_untrusted_gemini_renders_through_the_nonce_fence` |
| CC357d | External files type/size/trust/provenance | unit | error | `test_external_context_files_enforce_type_size_trust_and_provenance` |
| CC358a | `policy effective` / `simulate` | functional | happy | `tests/policy/test_cc_lifecycle.py` |
| CC358b | Symbol scope + conflicts + metrics + audit | unit | happy/error | `test_policy_resolution_stays_deterministic_at_symbol_scope`, `test_conflicting_policies_are_detected`, `test_policy_metrics_include_trigger_fp_waiver_and_blocking_rates`, `test_policy_audit_artifacts_are_emitted` |
| CC359a | Seven packs + identity fields | integration | happy | `tests/policy/test_cc_packs.py` |
| CC359b | Fixtures via `policy test`; no schema widen | functional | happy | `test_pack_fixtures_are_runnable_by_policy_test`, `test_packs_do_not_widen_the_policy_schema` |
| CC360a | `memory validate` | functional | happy/error | `test_memory_validate_help_is_registered`, `test_memory_validate_rejects_a_corrupt_store` |
| CC360b | Historical validation; no one-shot durable memory | unit | error | `test_historical_validation_is_required_before_activation`, `test_one_reviewer_action_does_not_silently_create_durable_memory` |
| CC360c | Kinds + FP over-suppression + org backend | unit | happy/edge | `test_memory_kinds_are_separated`, `test_false_positive_memory_has_expiry_scope_and_over_suppression_guard`, `test_organization_memory_backend_is_pluggable` |
| CC360d | Effectiveness; consume dismissal codes | integration | happy | `test_memory_effectiveness_improves_precision_without_reducing_recall`, `test_w13_consumes_dismissal_codes_it_does_not_define_them` |

## Acceptance (W8)

- Collection clean; current-state pins **PASS**; wiring pins **XFAIL** (`strict=False`); **no XPASS**
- `make lint` + `make typecheck` clean
- No `src/` edits; W9 not started
- W8 commit: `ba8f6f4d`
