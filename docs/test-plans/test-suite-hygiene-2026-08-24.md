# Test plan — test-suite hygiene wave (TH1–TH9)

Wave plan: `.ignorelocal/waves/test-suite-hygiene-2026-08-24-wave-plan.md`
Branch: `wave/test-suite-hygiene-2026-08-24`
Base SHA: `ef7e70d8` (PR #495, lane A merged)

Authoring: **TH1 RED** (this update). Implementation waves TH2–TH9 green their contracts.

## xfail schedule

| Batch | Marker | Reason |
| --- | --- | --- |
| TH2 | `strict=False` | `green after TH2: …` on integration + delta wrapper |
| TH5 | `strict=True` | `TH5` on four security xfails |
| TH8 | `strict=False` | `green after TH8: …` on tracing extra collection |

Plain **FAIL** (no xfail) until the impl wave: coverage HH skip sibling, ratchet honesty, cheat lint.

## ConfigLayer precedence audit (D17)

Regression audit after PR #491 (#468 / #470 closed). Every precedence-named test must pin **CLI > env > YAML/file** — none may assert the old inverted order.

| Test module | Test name | Expected order | Audit |
| --- | --- | --- | --- |
| `tests/cli/test_config_surface.py` | `test_config_explain_names_the_winning_layer` | env beats YAML when CLI unset | pass |
| `tests/cli/test_config_surface.py` | `test_config_explain_model_reports_cli_over_env_and_yaml` | CLI beats env beats YAML | pass |
| `tests/utils/test_cov_agent_resolve_paths.py` | `test_resolve_model_explicit_slug_outranks_the_env_override` | explicit slug beats `MERGECRAFT_MODEL` | pass |
| `tests/utils/test_cov_agent_resolve_paths.py` | `test_resolve_model_falls_back_to_the_env_override_without_a_slug` | env when slug absent | pass |
| `tests/tracing/exporters/test_cli_precedence.py` | `test_cli_env_config_precedence` | CLI > env > config > default | pass |
| `tests/tracing/test_trace_id_bridge.py` | env precedence tests (×3) | env layer ordering | pass |
| `tests/cli/test_tracing_logfire_cmd.py` | flag > env > prompt section | CLI > env | pass |
| `tests/cli/test_source_resolver.py` | `test_auth_precedence_order` | auth source ordering | pass |
| `tests/config/test_setup_timeout_precedence.py` | setup timeout precedence suite | action > env > YAML | pass |
| `tests/config/test_tracing_tri_state.py` | `test_cli_precedence_layer_is_already_tri_state` | CLI precedence helper | pass |
| `tests/action/test_action_yml_contract.py` | Action default empty for YAML precedence | YAML not defeated by Action default | pass |

**Escalation:** none — no survivor asserting inverted ConfigLayer order on `ef7e70d8`.

## TH1 contract matrix

| # | Contract | Primary test | Status |
| --- | --- | --- | --- |
| TH1.1a | Stale 70% coverage fails gate (not skip) | `tests/ci/test_coverage_hh.py::test_repo_coverage_report_fails_on_stale_low_coverage` | RED |
| TH1.1b | Integration job executes ≥1 test | `tests/ci/test_integration_job_ran.py::test_integration_marker_executes_at_least_one_test` | xfail TH2 |
| TH1.1c | Delta base measures without floor gate | `tests/ci/test_coverage_delta_wrapper.py::test_delta_wrapper_base_measures_without_floor_gate` | xfail TH2 |
| TH1.2a | Catch-all → `schema_failure` | `tests/agents/test_gate_rule_selection.py::test_catch_all_returns_schema_failure` | pass |
| TH1.2b | One behavioural case per rule id | `…::test_each_rule_predicate_has_a_behavioural_case` | pass |
| TH1.2c | Self-assessment-only → neutral, not auto_merge | `…::test_self_assessment_only_neutral_verdict_and_no_auto_merge_action` | pass |
| TH1.2d | `has_blockers` outranks changed-unread-file | `…::test_has_blockers_outranks_changed_unread_file` | pass |
| TH1.2e | #41 tautology removed (self_assessment) | `tests/evidence/test_self_assessment.py::test_self_assessment_alone_blocks_auto_merge` | pass |
| TH1.2f | #41 tautology removed (trajectory) | `tests/evidence/test_trajectory.py` (blocking trajectory case) | pass |
| TH1.3a | Branch mismatch excludes rule | `tests/policy/test_scoping.py::test_branch_mismatch_excludes_scoped_rule` | pass |
| TH1.3b | Language mismatch excludes rule | `…::test_language_mismatch_excludes_scoped_rule` | pass |
| TH1.3c | Change classifier exact bool fixtures | `tests/classify/test_change_classifier.py` (parametrised) | pass |
| TH1.4 | Four security xfails tagged TH5 | offline fence ×2, fence, auth_nous | xfail TH5 |
| TH1.5a | Lowering fail_under fails ratchet | `tests/ci/test_coverage_ratchet_honesty.py::test_lowering_fail_under_without_baseline_commit_fails` | pass |
| TH1.5b | Above-ceiling warns not fails | `…::test_raising_coverage_above_ceiling_warns_not_fails` | pass |
| TH1.6 | Cheat-signature lint rejects tautology | `tests/ci/test_cheat_signature_lint.py::test_lint_script_flags_getattr_tautology_fixture` | RED |
| TH1.7 | Tracing extra collects exporter tests | `tests/tracing/exporters/test_optional_extra.py::test_subprocess_with_tracing_extra_collects_exporter_tests` | xfail TH8 |

## Preserve (D20)

Do not weaken: `tests/test/coverage-431`, `tests/mcp/test_git_tool.py`, `tests/integration/test_provider_failures.py` (unit job), `tests/ci/test_live_opt_in.py`.

## Measurement notes (TH6 / TH9 — fill on impl)

### TH6 coverage floors (2026-08-24, HEAD `34cd99f9`, MP4 not merged)

Measured via `make coverage-measure` on `wave/test-suite-hygiene-2026-08-24` @ `34cd99f9`.
`mcp/public.py` absent on this tree; floors baselined against current tip per D21.

| Target | Measured line | Measured branch | Floor line (m−2) | Floor branch (m−2) |
| --- | ---: | ---: | ---: | ---: |
| **global** | 83.04 | — | 82.00 (`fail_under`) | — |
| `utils/token.py` | 53.9 | 41.2 | 51.9 | 39.2 |
| `utils/git_setup.py` | 93.5 | 88.9 | 91.5 | 86.9 |
| `main.py` | 87.3 | 77.3 | 85.3 | 75.3 |
| `mcp/` | 82.6 | 68.9 | 80.6 | 66.9 |
| `action/` | 91.1 | 85.7 | 89.1 | 83.7 |
| `security/` | 82.4 | 73.3 | 80.4 | 71.3 |
| `analyzers/` | 86.9 | 74.0 | 84.9 | 72.0 |
| `agents/` | 87.8 | 78.1 | 85.8 | 76.1 |
| `review/` | 89.4 | 68.8 | 87.4 | 66.8 |

Ratchet (D12): merge-base `fail_under` comparison via `git merge-base HEAD origin/pre-0.0.1`;
`measured > floor + 5` warns (exit 0); `--hard-ceiling` opts into legacy fail.

- Mutation escape rate: measure on `ef7e70d8` before setting TH9 threshold.
