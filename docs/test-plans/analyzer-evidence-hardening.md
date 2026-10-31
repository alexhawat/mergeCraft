# Test plan — analyzer and evidence hardening

The red suite below is authored before the implementation commits that make it
green. Each row maps one behaviour to the test that pins it. "Red until" names the
behaviour the implementation adds; "Guard" rows must stay green throughout.

## How to run

```bash
make lint
make typecheck
MERGECRAFT_PYTEST_JOBS=0 uv run --extra dev pytest \
  tests/analyzers tests/ci tests/classify tests/evidence tests/mcp -q
make catalog-check
```

## Coverage matrix

| Behaviour | Layer | Test file · test |
| --- | --- | --- |
| #851 A changed instruction file that is a symlink to a file outside the repo is never read | Unit / security | `tests/analyzers/test_agentsec_symlink_refusal.py` · `test_changed_agents_md_symlink_to_outside_file_is_not_read`, `test_outside_symlink_content_never_reaches_the_scan_result`, `test_cursor_rule_symlinked_to_outside_directory_is_refused` |
| #851 A refused file is reported with a named skip reason | Unit | `tests/analyzers/test_agentsec_symlink_refusal.py` · `test_refusal_is_reported_not_silent` |
| #851 An in-repo symlink is still scanned | Guard | `tests/analyzers/test_agentsec_symlink_refusal.py` · `test_in_repo_symlink_is_still_scanned` |
| #877 Token counts survive the entropy pass | Unit | `tests/analyzers/test_redact_numeric_metadata.py` · `test_token_counts_survive` |
| #877 Credential assignments, credential-shaped keys and long numeric runs still redact | Guard | `tests/analyzers/test_redact_numeric_metadata.py` · `test_credential_assignments_still_redact`, `test_credential_shaped_keys_are_not_exempted_by_numeric_values`, `test_long_digit_runs_under_a_neutral_key_are_not_blanket_exempt` |
| #887 Untrusted gates launch no subprocess without isolation, whatever `shell` says | Unit / security | `tests/mcp/test_static_checks_fail_closed.py` · `test_untrusted_gates_never_launch_a_subprocess_without_isolation` |
| #887 The executor itself refuses an untrusted gate without a sandbox context | Unit / defence in depth | `tests/mcp/test_static_checks_fail_closed.py` · `test_run_checks_refuses_an_untrusted_gate_without_a_sandbox_context` |
| #887 Untrusted-tier withhold and trusted carve-out at the tool level | Guard | `tests/mcp/test_static_checks.py` · `test_discovered_makefile_gates_*` |
| #878 A trusted catalog analyzer is launched behind the identity drop | Unit | `tests/analyzers/test_trusted_uid_drop.py` · `test_trusted_catalog_analyzer_is_launched_behind_the_identity_drop` |
| #878 Scratch is handed to the drop target before the payload runs; symlinks are never followed | Unit / security | `tests/analyzers/test_trusted_uid_drop.py` · `test_scratch_tree_is_handed_to_the_drop_target_before_the_payload_runs`, `test_symlinked_scratch_entries_are_never_followed_by_the_chown` |
| #878 An unlandable drop is a named `unavailable`, never a root run | Unit / error handling | `tests/analyzers/test_trusted_uid_drop.py` · `test_unlandable_drop_is_a_named_unavailable_not_a_root_run` |
| #878 Off the root backend, and for static gates, nothing changes | Guard | `tests/analyzers/test_trusted_uid_drop.py` · `test_no_drop_is_requested_off_the_root_backend`, `test_static_check_runs_are_not_dropped_twice` |
| #878 The payload runs as a non-root UID and can write scratch | Privileged (root, Linux, `setpriv`) | `tests/analyzers/test_trusted_uid_drop.py` · `test_root_backend_trusted_analyzer_payload_runs_unprivileged_and_writes_scratch` |
| #854 Manifest, parser, skip reason, opt-in selection, fallback config and trust behaviour | Unit | `tests/analyzers/test_gherkin_lint.py` |
| #941 Hit identity, required reasons, per-stage dispositions, verifier hook | Unit | `tests/analyzers/test_dispositions.py` |
| #941 Every raw hit ends with exactly one disposition through the full pipeline | Property / integration | `tests/analyzers/test_dispositions.py` · `test_pipeline_gives_every_raw_hit_exactly_one_terminal_disposition`, `test_property_every_raw_hit_has_exactly_one_terminal_disposition` |
| #941 A leaky stage leaves a named orphan; the run becomes inconclusive; blockers still win | Integration | `tests/analyzers/test_dispositions.py` · `test_a_leaky_stage_leaves_a_named_orphan`; `tests/evidence/test_packet_dispositions.py` · `test_an_open_ledger_makes_the_run_inconclusive_and_names_the_orphan`, `test_blockers_still_win_over_an_open_ledger` |
| #941 Packet carries the ledger, per-stage counts and persisted suppression audit rows; schema version bumped | Unit / schema pin | `tests/evidence/test_packet_dispositions.py` |
| #941 The pre-merge Analyzers row shows raw, kept and drops by stage | Unit | `tests/analyzers/test_dispositions.py` · `test_pipeline_pre_merge_row_shows_raw_kept_and_stage_counts` |
| #941 SARIF from `ciEvidence.sarifArtifacts` follows the same contract | Unit | `tests/ci/test_sarif_dispositions.py` |
| #942 Added suppression markers per language, with rule codes, severity and untrusted bump; pre-existing markers and prose files ignored | Unit | `tests/analyzers/test_self_silencing.py` · `test_each_added_marker_*`, `test_untrusted_tier_bumps_*`, `test_markers_already_on_base_*`, `test_removed_lines_and_prose_files_*` |
| #942 Loosening edits to mergeCraft, ruff, pyproject, ESLint and ignore-file config are reported with the specific change; tightening is not | Unit | `tests/analyzers/test_self_silencing.py` · `test_*config*`, `test_ruff_*`, `test_eslint_*` |
| #942 Eligible under `shell: disabled` and on the untrusted tier | Unit | `tests/analyzers/test_self_silencing.py` · `test_self_silencing_is_an_in_process_analyzer_eligible_on_every_tier` |
| #942 Settings resolve from the base sha / base snapshot; symlinked or unreadable base fails closed; provenance is recorded | Integration (real git) | `tests/analyzers/test_analyzer_settings_pinning.py` |
| #942 A head-only analyzer config change has no effect on the analyzers selected or on the global gate | Integration | `tests/analyzers/test_analyzer_settings_pinning.py` · `test_run_analyzers_ignores_a_head_only_analyzer_config_change`, `test_a_head_side_global_disable_does_not_switch_the_analyzer_surface_off` |
| #942 Review-governing config paths map to a non-eligible lane | Unit | `tests/classify/test_blast_radius_review_config.py` |
| #891 A failing same-fingerprint base run clears a failure with no agent arguments; the runs used are recorded | Integration (mocked client) | `tests/ci/test_base_branch_runs.py` · `test_matching_failing_base_run_clears_the_failure_with_no_agent_arguments`, `test_the_base_runs_used_appear_in_the_recorded_evidence` |
| #891 Passing, unrecognised, other-fingerprint and other-workflow base runs never clear | Guard | `tests/ci/test_base_branch_runs.py` · `test_a_passing_or_unrecognised_base_status_never_clears`, `test_a_base_failure_with_a_different_fingerprint_does_not_clear`, `test_a_base_failure_in_another_workflow_is_not_consulted` |
| #891 A listing failure or a missing base degrades to the unattributed report | Error handling | `tests/ci/test_base_branch_runs.py` · `test_listing_failure_degrades_to_the_unattributed_report`, `test_no_base_branch_in_the_event_makes_no_api_call` |
