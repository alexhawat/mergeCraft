# CRAP and mutation evidence — test plan

Wave plan: `.ignorelocal/waves/24-crap-mutation-evidence-wave-plan.md`
Worktree: `mc-crap` @ `wave/crap-mutation-evidence`
Authoring wave: **C1** (`test-creator`). Implementation: **C2–C4**. Final: **C5**.

C0 locked 2026-09-18. FindingSource is unchanged (C-D3): ingested → `ci`,
locally executed → `analyzer`. #593 has not landed; C4 refuses rather than
fail-open. A surviving mutant is evidence of a weak test; zero survivors is not proof of a correct one.

## xfail schedule

Cross-wave markers are `strict=False`. Never `strict=True`.

C2–C4 xfails were **removed** in post-impl reconciliation after C4 tip
`c1d9ded0` (this commit). No `C2_XFAIL` / `C3_XFAIL` / `C4_XFAIL` markers
remain. Do not re-add them.

| Marker | Greening wave | Status |
| --- | --- | --- |
| `C2_XFAIL` | C2 | **Green** — coverage parsers, CRAP, changed-function resolution, declared ingest, shadow, config |
| `C3_XFAIL` | C3 | **Green** — mutation parsers, survivor attribution, kill/escape rate, harness isolation |
| `C4_XFAIL` | C4 | **Green** — CLI `--with-coverage` / `--with-mutation`, bounds, untrusted / no-sandbox refusal |

Still green without xfail (C1 pins): FindingSource, unknown `coverage:` key,
internal harness existence, Makefile target, this file's C-D10 sentence.

Collected suite (post-reconciliation): **91** tests expected pass,
**0** xfail / xpass. Split: **54** C2 / **15** C3 / **16** C4 / **5** C1-green
/ **1** C2–C4 deliverable-symbol export.

C5-F2 escalation (2026-09-18): **2** additional tests pin the intelligence
sibling (`run_ci_intelligence` must list check runs and pass them into
`collect_*`). They are **not** xfailed — they fail on today's call site.

## Contract matrix

| Contract | Greening wave | Primary test(s) |
| --- | --- | --- |
| coverage.py JSON with `files.<path>.functions` | C2 | `test_coverage_ingest.py::test_coverage_py_json_with_function_records` |
| lcov `FN:` / `FNDA:` | C2 | `…::test_lcov_with_function_records` |
| Cobertura `<method>` | C2 | `…::test_cobertura_with_method_elements` |
| sniff each supported format | C2 | `…::test_parse_coverage_artifact_sniffs_each_supported_format` |
| `coverage_no_function_records` → zero findings | C2 | `…::test_coverage_py_without_function_records_skips_with_zero_findings` |
| `lcov_no_function_records` → zero findings | C2 | `…::test_lcov_without_function_records_skips_with_zero_findings` |
| `cobertura_no_method_elements` → zero findings | C2 | `…::test_cobertura_without_method_elements_skips_with_zero_findings` |
| `unsupported_coverage_format` → zero findings | C2 | `…::test_unsupported_coverage_format_skips_with_zero_findings` |
| C0 worked examples (C=1/5/4/5/10) | C2 | `test_crap_score.py::test_worked_example_crap_score` |
| Band boundaries inclusive lower / exclusive upper except `severe` | C2 | `…::test_crap_band_inclusive_lower_exclusive_upper_except_severe` |
| Display vs finding severity | C2 | `…::test_display_and_finding_severity_for_each_band` |
| Default bands `{watch:5, elevated:15, crap:30, severe:50}` | C2 | `…::test_default_bands_match_c0_table`, `test_coverage_mutation_settings.py` |
| Consumer bands move a score | C2 | `test_crap_score.py::test_consumer_bands_move_a_score_across_the_watch_line` |
| `C ≥ 1`, `cov ∈ [0,1]` | C2 | `…::test_crap_score_rejects_complexity_below_one`, `…::test_crap_score_rejects_coverage_outside_unit_interval` |
| Hunk → enclosing function | C2 | `test_changed_function_resolution.py::test_hunk_inside_function_resolves_enclosing_symbol` |
| Diff → changed functions only | C2 | `…::test_changed_functions_from_diff_returns_only_the_enclosing_function` |
| `enclosing_symbol_unresolved` emits nothing, never file-scope (C-D4) | C2 | `…::test_unresolvable_hunk_emits_nothing_never_file_scope` |
| Empty diff / unicode path | C2 | `…::test_empty_diff_yields_no_changed_functions`, `…::test_unicode_path_survives_resolution` |
| Clean band is not a finding; `coverage_clean` | C2 | `test_coverage_ingest.py::test_clean_band_does_not_emit_a_finding` |
| Watch+ findings on changed functions, `introduced_by_pr="true"` | C2 | `…::test_watch_and_above_emit_changed_function_finding` |
| Ingested findings `source="ci"` (C-D3) | C2 | `…::test_ingested_coverage_findings_are_ci_source` |
| `shadow` severe CRAP does not trip `has_blockers` (C-D5) | C2 | `…::test_shadow_severe_does_not_reach_has_blockers` |
| `coverage_default_bands` vs `coverage_consumer_bands` (C-D6) | C2 | `…::test_default_bands_run_note`, `…::test_consumer_bands_run_note` |
| Undeclared = no API call, `coverage_undeclared` (C-D2) | C2 | `…::test_undeclared_coverage_makes_no_api_call` |
| Declared success → changed-function finding | C2 | `…::test_declared_successful_coverage_artifact_emits_changed_function_finding` |
| Declared-failed → finding, never substitution (C-D2) | C2 | `…::test_declared_failed_coverage_check_emits_finding_never_substitution` |
| Intelligence sibling lists check runs and passes them into collect (C5-F2 / C-D2) | C5 | `test_intelligence_coverage_mutation.py::test_run_ci_intelligence_declared_failed_check_emits_finding_never_downloads` |
| Concurrent same-token ingest | C2 | `…::test_concurrent_same_token_coverage_ingest` |
| Config `ciEvidence.coverageArtifacts` / `coverage:` defaults | C2 | `test_coverage_mutation_settings.py::test_default_coverage_artifacts_empty_and_mode_shadow` |
| Consumer YAML override | C2 | `…::test_consumer_coverage_yaml_overrides_default_bands` |
| Unknown `coverage` key rejected | C2 | `…::test_unknown_coverage_key_is_rejected` |
| mutmut JSON survivors | C3 | `test_mutation_ingest.py::test_mutmut_json_parses_survivors` |
| Stryker JSON survivors | C3 | `…::test_stryker_json_parses_survivors` |
| `unsupported_mutation_format` → zero findings | C3 | `…::test_unsupported_mutation_format_skips_with_zero_findings` |
| Survivor on changed function is evidence | C3 | `…::test_survivor_on_changed_function_is_evidence` |
| Survivor on unchanged function is not emitted | C3 | `…::test_survivor_on_unchanged_function_is_not_emitted` |
| Kill / escape rate; `total=0` is None | C3 | `…::test_kill_and_escape_rate` |
| `survivorThreshold: 0` default | C3 | `…::test_survivor_threshold_zero_emits_any_changed_survivor` |
| Threshold 2 suppresses a single survivor | C3 | `…::test_survivor_threshold_two_suppresses_single_survivor` |
| `shadow` mutation does not trip `has_blockers` (C-D5) | C3 | `…::test_shadow_mutation_does_not_reach_has_blockers` |
| Ingest does not import internal harness (K6) | C3 | `…::test_mutation_ingest_does_not_import_internal_harness` |
| Undeclared mutation = no API call | C3 | `…::test_undeclared_mutation_makes_no_api_call` |
| Declared-failed mutation → finding, never substitution | C3 | `…::test_declared_failed_mutation_check_emits_finding_never_substitution` |
| Intelligence sibling, declared-failed mutation (C5-F2 / C-D2) | C5 | `test_intelligence_coverage_mutation.py` (parametrize `mutation-json`) |
| Declared mutmut artifact | C3 | `…::test_declared_successful_mutmut_artifact_attributes_survivor` |
| Config `mutationArtifacts` / `survivorThreshold` | C3 | `test_coverage_mutation_settings.py` |
| Internal harness still present (K6) | C1 green | `test_mutation_ingest.py::test_internal_harness_script_still_exists`, `…::test_makefile_still_has_mutation_test_decisions_target` |
| CLI `--with-coverage` / `--with-mutation` | C4 | `test_review_coverage_mutation.py::test_review_help_documents_coverage_and_mutation_flags`, `…::test_review_forwards_with_coverage_and_with_mutation` |
| Untrusted-tier refusal (C-D7) | C4 | `…::test_untrusted_tier_refuses_local_coverage`, `…::test_run_local_coverage_does_not_execute_on_untrusted_tier`, `…::test_review_with_coverage_refuses_untrusted_cli` |
| No-sandbox-backend refusal (C-D7) | C4 | `…::test_no_sandbox_backend_refuses_local_mutation`, `…::test_run_local_mutation_does_not_execute_without_sandbox` |
| `#593` fail-open is not inherited | C4 | `…::test_unsandboxed_shell_env_does_not_fail_open` |
| Empty `pathAllowlist` = changed paths only (C-D8) | C4 | `…::test_empty_path_allowlist_uses_changed_paths_only` |
| Allowlist ∩ changed paths | C4 | `…::test_path_allowlist_intersects_changed_paths` |
| `maxMutants: 50` | C4 | `…::test_max_mutants_bound_is_enforced` |
| `timeoutSeconds: 300` | C4 | `…::test_timeout_seconds_default_is_300` |
| Local findings `source="analyzer"` (C-D3) | C4 | `…::test_local_coverage_findings_are_analyzer_source`, `…::test_local_mutation_findings_are_analyzer_source` |
| Absent toolchain is an honest skip | C4 | `…::test_absent_toolchain_is_honest_skip_not_silent_pass` |
| FindingSource unchanged (C-D3) | C1 green | `test_coverage_mutation_settings.py::test_finding_source_is_unchanged_by_this_plan` |
| Docs: green does not prove correctness (C-D10) | C1 green | `…::test_docs_state_what_green_does_not_prove` |

## Deliverable symbols

| Symbol | Module (planned) | Test anchor |
| --- | --- | --- |
| `crap_score` / `crap_band` / `crap_display_severity` / `crap_finding_severity` | `ci/crap.py` | `test_crap_score.py` |
| `DEFAULT_CRAP_BANDS` / `CrapError` | `ci/crap.py` | `test_crap_score.py` |
| `parse_coverage_py_json` / `parse_lcov` / `parse_cobertura` / `parse_coverage_artifact` | `ci/coverage.py` | `test_coverage_ingest.py` |
| `coverage_findings` / `collect_ci_coverage_findings` | `ci/coverage.py` | `test_coverage_ingest.py` |
| Skip / note tokens (`coverage_no_function_records`, …) | `ci/coverage.py` | `test_coverage_ingest.py` |
| `resolve_enclosing_symbol` / `changed_functions_from_diff` | `ci/changed_functions.py` | `test_changed_function_resolution.py` |
| `parse_mutmut_json` / `parse_stryker_json` / `parse_mutation_artifact` | `ci/mutation.py` | `test_mutation_ingest.py` |
| `mutation_findings` / `collect_ci_mutation_findings` | `ci/mutation.py` | `test_mutation_ingest.py` |
| `kill_rate` / `escape_rate` | `ci/mutation.py` | `test_mutation_ingest.py` |
| `CrapBands` | `ci/crap.py` | `test_coverage_mutation_settings.py::test_c2_c4_deliverable_symbol_export` |
| `ChangedFunction` | `ci/changed_functions.py` | `…::test_c2_c4_deliverable_symbol_export` |
| `CoverageSettings` / `CoverageBandSettings` | `config/settings.py` | `test_coverage_mutation_settings.py` |
| `CoverageFunction` / `ParsedCoverage` / `CoverageIngestResult` | `ci/coverage.py` | `…::test_c2_c4_deliverable_symbol_export` |
| `complexity_from_source` / `coverage_inputs_from_context` | `ci/coverage.py` | `…::test_c2_c4_deliverable_symbol_export` |
| `ci_coverage_artifacts` / `ci_mutation_artifacts` | `mcp/context.py` | `…::test_c2_c4_deliverable_symbol_export` |
| `MutationSurvivor` / `ParsedMutation` / `MutationIngestResult` | `ci/mutation.py` | `…::test_c2_c4_deliverable_symbol_export` |
| `MutationSettings` | `config/settings.py` | `test_coverage_mutation_settings.py` |
| `CiEvidenceSettings.coverage_artifacts` / `mutation_artifacts` | `config/settings.py` | `test_coverage_mutation_settings.py` |
| `LocalEvidenceResult` | `ci/local_evidence.py` | `…::test_c2_c4_deliverable_symbol_export` |
| `require_trusted_sandboxed_execution` / `LocalEvidenceRefused` | `ci/local_evidence.py` | `test_review_coverage_mutation.py` |
| `run_local_coverage` / `run_local_mutation` | `ci/local_evidence.py` | `test_review_coverage_mutation.py` |
| `plan_local_mutation_paths` / `bound_mutants` | `ci/local_evidence.py` | `test_review_coverage_mutation.py` |
| `--with-coverage` / `--with-mutation` | `cli/diff_review_cmd.py` | `test_review_coverage_mutation.py` |

## Fixture corpus

Under `tests/analyzers/fixtures/`:

| Path | Role |
| --- | --- |
| `crap/fn_clean` … `crap/fn_severe` | C0 worked examples (source + coverage.py JSON + diff + meta) |
| `crap/formats/coverage.py.json` | coverage.py JSON with function records |
| `crap/formats/coverage.py.nofn.json` | `coverage_no_function_records` |
| `crap/formats/lcov.info` / `lcov.nofn.info` | lcov with / without `FN:` |
| `crap/formats/cobertura.xml` / `cobertura.nofn.xml` | Cobertura with / without `<method>` |
| `crap/formats/unsupported.html` | `unsupported_coverage_format` |
| `crap/ingest/declared-success/coverage.json` | declared successful artifact |
| `crap/ingest/declared-failed/check-run.json` | declared-but-failed check |
| `crap/unresolvable/` | hunk with no enclosing symbol |
| `mutation/mutmut-survivor.json` | mutmut survivor on `fn_watch` |
| `mutation/stryker-survivor.json` | Stryker survivor |
| `mutation/unsupported.xml` | `unsupported_mutation_format` |

## Skip reasons and run notes (C0 tokens)

`coverage_no_function_records` · `lcov_no_function_records` ·
`cobertura_no_method_elements` · `unsupported_coverage_format` ·
`enclosing_symbol_unresolved` · `unsupported_mutation_format` ·
`untrusted_tier` · `no_sandbox_backend` · `toolchain_absent`

`coverage_undeclared` · `coverage_clean` · `coverage_default_bands` ·
`coverage_consumer_bands`

## Escalation notes

- **C5-F3:** K6 isolation pins harness-file loads (plus mutation AST imports), not a `sys.modules` name substring — full-suite collection already includes `tests.ci.test_mutate_decision_modules`.
- **C5-F2 / C-D2 sibling:** `run_ci_intelligence` must call
  `list_check_runs_for_ref` (or equivalent) and pass `check_runs=` into
  `collect_ci_coverage_findings` / `collect_ci_mutation_findings`. A declared
  failed check emits a `source="ci"` `check-run/failure` finding; the failed
  job's artifact is never downloaded; `substitutions` / `satisfied-by-ci` must
  not appear. Guard deletion: omitting `check_runs=` fails this test (the
  poison zip would otherwise ingest as a receipt).
- Display severity `note` is not a `Finding.severity` value. Clean maps to
  `Trivial` and does not emit a finding; watch+ use Minor / Major / Critical.
- `has_blockers` is pinned via `_packet_has_blockers` on a packet of the
  produced findings plus `CoverageIngestResult.reaches_has_blockers`.
- Local CLI refusal must not honour `MERGECRAFT_ALLOW_UNSANDBOXED_SHELL`
  (C-D7 does not inherit #593).
