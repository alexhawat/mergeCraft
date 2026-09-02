# Self-review evidence — test plan

Maps **W1 RED** contracts for wave plan 17 to the test suite.
Source plan: `.ignorelocal/waves/17-self-review-evidence-wave-plan.md`.

Cross-wave reds use `@pytest.mark.xfail(..., strict=True)` per the lane plan —
`scripts/check_xpass.py` fails non-strict xfails that pass.

## W1.1 — cascade → W3

| Contract | Tests | Layer |
| --- | --- | --- |
| Codex `outcome == success` + packet `verdict=neutral` → `claude_fallback.need != true` | `tests/ci/test_self_review_cascade_w3.py::test_codex_success_with_neutral_packet_does_not_need_claude` | workflow script |
| Codex success + unparseable packet + post-baseline `mergecraft-approval` `neutral` → need false (D3 fall-through) | `…::test_codex_success_unparseable_packet_falls_through_to_neutral_check_run` | workflow script |
| `mergecraft-approval` id == `BASELINE_ID` discarded | `…::test_baseline_check_run_id_is_discarded` | workflow script (guard) |
| Codex `outcome == failure` + no packet + no new review → need true | `…::test_codex_failure_without_verdict_needs_claude` | workflow script (guard) |
| Codex skipped, Nous success + `verdict=success` → need false | `…::test_nous_success_with_success_verdict_does_not_need_claude` | workflow script (guard) |
| Codex skipped, Nous failed → need true | `…::test_nous_failed_needs_claude_backstop` | workflow script (guard) |
| Sole Claude reviewer clause preserved | `…::test_sole_claude_reviewer_clause_still_present` | parsed YAML (guard) |
| Nous → Codex: missing verdict still sets Codex `need=true` (D5) | `…::test_nous_missing_verdict_sets_codex_need_true` | workflow script (guard) |
| Nous `neutral` must not skip Codex (D5) | `…::test_nous_neutral_verdict_does_not_skip_codex` | workflow script (guard) |
| Codex `outcome == success` short-circuits even when lookups fail (D4) | `…::test_codex_success_short_circuits_even_when_lookups_fail` | workflow script |
| Claude decide `if:` excludes Codex success (W3 Step 1) | `…::test_claude_decide_step_not_gated_on_nous_failure_when_codex_succeeded` | parsed YAML |

Shared helpers: `tests/ci/support_self_review_cascade.py`.

Pinned workflow: `.github/workflows/mergecraft.yml` steps `fallback`, `claude_fallback`.

## W1.2 — config flip → W2

| Contract | Tests | Layer |
| --- | --- | --- |
| Committed `.mergecraft/config.yaml` has quoted `trust.selfReview: "full"` | `tests/config/test_self_review_trust_config_w2.py::test_committed_config_has_self_review_full_quoted` | config |
| Same-repo `pull_request_target` → execution=trusted, authority=trusted | `…::test_committed_config_resolves_execution_trusted_on_same_repo_prt` | config |
| Fork PR stays untrusted on both axes | `…::test_fork_pr_stays_untrusted_on_both_axes_with_analyzers`, `…::test_committed_config_fork_pr_stays_untrusted` | unit (guard) |

Pinned API: `mergecraft.config.trust_policy.resolve_trust_policy`.

## W1.3 — green ingest → W4

| Contract | Tests | Layer |
| --- | --- | --- |
| Declared artifacts downloaded when wait `state=complete` and `failed_count=0` | `tests/ci/test_self_review_green_ingest_w4.py::test_green_wait_ingests_declared_artifacts` | integration |
| `collect_ci_sarif_findings` fed head-SHA workflow run ids, not only failed suite | `…::test_green_wait_lists_workflow_runs_for_head_sha_not_only_failed_suite` | integration |
| Download 403 → warning, review continues | `…::test_artifact_download_403_logs_warning_and_continues` | integration |
| Dogfood `mergecraft.yml` review job `permissions` includes `actions: read` | `…::test_mergecraft_yml_review_job_includes_actions_read` | parsed YAML |
| Hardened template forwards wait env + `actions: read` | `…::test_hardened_example_review_job_includes_actions_read`, `…::test_hardened_example_review_job_forwards_wait_env_for_sarif_ingest` | parsed YAML |
| Non-complete wait state / blank head SHA → no ingest | `…::test_ingest_skips_when_ci_wait_state_not_complete`, `…::test_ingest_skips_when_head_sha_blank` | unit |
| Non-GitHub SCM / listing error / truncated listing → warning, no findings | `…::test_ingest_skips_without_github_client`, `…::test_ingest_workflow_listing_error_logs_warning`, `…::test_ingest_workflow_listing_incomplete_logs_warning` | integration |
| Action env lane (`MERGECRAFT_CI_WAIT_STATE` / `CI_STATE`) | `…::test_ci_wait_inputs_from_env_*`, `…::test_ingest_ci_sarif_from_action_env_*` | unit + integration |
| D8 guard — `mergecraft.yml` not SARIF upload surface | `tests/ci/test_ci_sarif_evidence_464.py::test_mergecraft_yml_is_not_the_sarif_upload_surface` | parsed YAML (guard, no xfail) |

Pinned API (W4): `mergecraft.ci.sarif_ingest.ingest_ci_sarif_after_ci_wait`, `mergecraft.ci.intelligence.collect_ci_sarif_findings`.

## W1.4 — log groups → W6

| Contract | Tests | Layer |
| --- | --- | --- |
| `GITHUB_ACTIONS=true` → setup / model-chain / agent-dispatch / publish emit `::group::` / `::endgroup::` | `tests/action/test_self_review_gha_log_groups_w6.py::test_main_emits_log_groups_for_setup_model_chain_publish` | E2E harness |
| Failure reason for run record logged outside open group | `…::test_setup_failure_reason_is_logged_outside_group` | E2E harness |
| `GITHUB_ACTIONS` unset → no workflow-command noise | `…::test_gha_log_group_emits_nothing_without_github_actions` | unit (guard) |

Pinned module: `mergecraft.utils.gha_log`, `mergecraft.main.main`.

## W1.5 — SARIF extension → W5 (shipped subset + D12 skip)

| Contract | Tests | Layer |
| --- | --- | --- |
| `ci.yml` uploads actionlint / zizmor / semgrep SARIF artifacts | `tests/ci/test_self_review_sarif_extension_w5.py::test_ci_yml_uploads_extended_sarif_artifact` | parsed YAML |
| D12 — trufflehog has no SARIF upload or config entry | `…::test_ci_yml_does_not_upload_trufflehog_sarif`, `…::test_committed_config_omits_trufflehog_sarif_artifact` | parsed YAML + config |
| `.mergecraft/config.yaml` `ciEvidence.sarifArtifacts` lists shipped W5 names | `…::test_committed_config_lists_shipped_extended_sarif_artifacts` | config |
| `MERGECRAFT_WORKFLOW_SARIF_DIR` on static emit step | `…::test_ci_yml_static_job_sets_workflow_sarif_dir` | parsed YAML |
| `scripts/ci_extended_sarif.py` / `emit_semgrep_sarif` deliverable | `…::test_ci_extended_sarif_exports_emit_semgrep_sarif`, `…::test_ci_extended_sarif_cli_requires_output_path` | import + CLI |
| D8 guard — no SARIF upload names on `mergecraft.yml` | `…::test_mergecraft_yml_is_not_the_sarif_upload_surface_guard` | parsed YAML (guard) |

## xfail reconciliation

| Wave | Marker reason prefix | Files |
| --- | --- | --- |
| W2 | *(greened — xfails removed)* | `tests/config/test_self_review_trust_config_w2.py` |
| W3 | *(greened — xfails removed)* | `tests/ci/test_self_review_cascade_w3.py` |
| W4 | *(greened — xfails removed)* | `tests/ci/test_self_review_green_ingest_w4.py` |
| W5 | *(greened — xfails removed; trufflehog D12 skip asserted)* | `tests/ci/test_self_review_sarif_extension_w5.py` |
| W6 | *(greened — xfails removed)* | `tests/action/test_self_review_gha_log_groups_w6.py` |

Guard tests (no xfail) must stay green through W2–W6 implementation.

## Escalation notes

- **W5 test amendment (2026-09-01):** trufflehog is a named D12 skip (JSONL-only, no SARIF
  emitter). Shipped W5 tests assert actionlint / zizmor / semgrep uploads and config names;
  trufflehog tests assert absence from `ci.yml` uploads and `sarifArtifacts`, not a fake SARIF
  artifact.
- **W4 guard amendment (2026-09-01):** `test_dogfood_config_enables_first_wave_ci_evidence` requires
  the first-wave subset only; W5-extended names in `sarifArtifacts` are allowed.
- **W8 coverage escalation (2026-09-01):** added W4 skip/error/action-env branch tests in
  `test_self_review_green_ingest_w4.py` to cover `mergecraft.ci.sarif_ingest`
  `ingest_ci_sarif_after_ci_wait` / `ingest_ci_sarif_from_action_env` paths for the
  coverage-gate floor.
- W2 implementation waits on lane C W2 (#573) and lane B W2 coupling (D6a); tests are authored regardless.
