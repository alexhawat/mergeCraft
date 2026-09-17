# Evals and calibration — test plan

Wave plan: `.ignorelocal/waves/25-evals-calibration-wave-plan.md`
Worktree: `mc-evals` @ `wave/evals-calibration`
Authoring wave: **test-creator** (this doc). Implementation: **E2**, **E4**.
Out of scope here: E1/E5 operator, E3 issue rewrite, E6 verifier.

Locked decisions covered: **E-D2** (keyless structural PR gate), **E-D3**
(honest structural-replay scope; `GateReport` names the moved metric),
**E-D9** (lift J2 `TokenBudget` + kill-switch; no second budget or judge),
**E-D10** (`tests/` has one writer). E0 fallout: ablation product and its
suite are gone — do not restore `AblationConfig` / `run_ablation` /
`ABLATION_DIMENSIONS`. The W10.2 mapping in
`docs/test-plans/open-issues-sweep-2026-08-20d-b-runtime.md` is superseded.

## E0 fallout (green)

| Contract | Test(s) | File |
| --- | --- | --- |
| Ablation harness tests deleted | (file gone) | ~~`tests/evals/test_ablation_harness.py`~~ |
| Methodology names corpora, not ablation | `test_eval_methodology_page_exists_and_names_metrics` | `tests/evals/test_eval_methodology_docs.py` |

## Contract matrix

| Contract | Greening wave | Primary test(s) |
| --- | --- | --- |
| **E-D2** `ci.yml` runs on `pull_request` | E2 | `tests/ci/test_eval_pr_gate.py::test_ci_yml_runs_on_pull_request` |
| **E-D2** blocking `eval-gate` job (not `continue-on-error`) | E2 | `…::test_ci_yml_has_blocking_eval_gate_job` |
| **E-D2** job cannot be deleted | E2 | `…::test_removing_eval_gate_job_fails` |
| **E-D2** keyless (no provider secrets) | E2 | `…::test_eval_gate_pr_job_is_keyless` |
| **E-D2** job runs replay + `--baseline` / `--candidate` vs `evals/results/latest.json` | E2 | `…::test_eval_gate_pr_job_runs_replay_and_regression_comparison` |
| **E-D2** `bench-detect` stays out of the PR job | E2 | `…::test_eval_gate_pr_job_does_not_run_bench_detect` |
| **E-D2** no `bench-detect` CI job | E2 (green today) | `…::test_ci_yml_has_no_bench_detect_job` |
| **V1** `mutation-advisory` stays advisory | E2 (green today) | `…::test_mutation_advisory_is_not_the_eval_gate` |
| **E-D3** check summary: structural replay, not live detection | E2 | `…::test_eval_gate_pr_check_summary_states_structural_not_live_scope` |
| **E-D3** failure surface names the metric (step summary or helper) | E2 | `…::test_eval_gate_pr_job_writes_step_summary` |
| Job permissions are read-only | E2 | `…::test_eval_gate_pr_job_permissions_are_read_only` |
| Make targets exist (`eval-gate` / `eval-replay` / `eval-convergence` / `bench-detect`) | E2 (green today) | `…::test_makefile_keeps_keyless_eval_targets` |
| `release.yml` still gates | E2 (green today) | `…::test_release_yml_still_has_eval_gate` |
| Baseline versioned + loadable | E2 (green today) | `tests/evals/test_eval_pr_gate.py::test_structural_baseline_is_versioned_and_loadable` |
| Baseline tracked in git | E2 (green today) | `…::test_structural_baseline_is_tracked_in_git` |
| DoD — clean candidate passes | E2 (green today) | `…::test_clean_committed_baseline_passes_eval_gate` |
| DoD — +0.25 `unsafe_approval_rate` fails and names the metric | E2 (green today) | `…::test_deliberately_regressed_baseline_fails_and_names_the_metric` |
| Direction-aware pass-rate drop is named | E2 (green today) | `…::test_pass_rate_drop_is_a_named_regression` |
| `format_pr_gate_summary` states E-D3 scope | E2 | `…::test_format_pr_gate_summary_states_structural_not_live_scope` |
| `format_pr_gate_summary` prints metric + baseline / candidate / delta | E2 | `…::test_format_pr_gate_summary_names_regressed_metric_ledger` |
| `format_pr_gate_summary` rejects a non-report | E2 | `…::test_format_pr_gate_summary_requires_gate_report` |
| `.gitignore` keeps `latest.json` | E2 (green today) | `…::test_gitignore_does_not_drop_the_published_baseline` |
| Path constant matches the published file | E2 (green today) | `…::test_baseline_path_constant_matches_release_and_checkout` |
| CLI: `--baseline` / `--candidate` together | E2 (green today) | `tests/cli/test_eval_regression_gate_output.py::test_baseline_and_candidate_must_be_given_together` |
| CLI failure names metric + ledger | E2 (green today) | `…::test_regression_gate_failure_names_metric_and_ledger` |
| CLI clean pair exits 0 | E2 (green today) | `…::test_clean_regression_gate_exits_zero` |
| **E-D9** `TokenBudget` / `compute_cost` are the J2 objects | E4 (xfail) | `tests/agents/test_provider_token_budget.py::test_token_budget_is_the_jev_class_not_a_fork` |
| **E-D9** `PROVIDER_PATHS` covers five agents + `jev` | E4 (xfail) | `…::test_provider_paths_cover_every_agent_and_jev` |
| Kill-switch stops `AgentImpl._run` per provider | E4 (xfail) | `…::test_kill_switch_stops_provider_dispatch` |
| Unreported tokens stay `cost_known=False` | E4 (xfail) | `…::test_unreported_tokens_stay_honest_on_the_shared_path` |
| Partial `None` tokens are not coerced to zero | E4 (xfail) | `…::test_record_provider_usage_does_not_zero_partial_none` |
| Concurrent same-budget dispatches share one cap | E4 (xfail) | `…::test_concurrent_same_credential_shares_one_budget` |
| Budget keyed by pinned model id | E4 (xfail) | `…::test_budget_is_keyed_by_pinned_model_id` |
| Stop reason is `kill_switch` | E4 (xfail) | `…::test_kill_switch_stop_reason_is_the_j2_token` |
| Collect rates from `ParallelJudgeResult` | E4 (xfail) | `tests/evals/test_faithfulness_alerts.py::test_collect_faithfulness_signals_from_parallel_judge` |
| Empty pack is honest zero | E4 (xfail) | `…::test_empty_judge_result_is_honest_zero` |
| `says_nothing` is a quote-verification failure | E4 (xfail) | `…::test_says_nothing_is_a_quote_verification_failure` |
| No second judge / no `AsyncJevClient` | E4 (xfail) | `…::test_collect_does_not_require_a_client` |
| Logfire-hookable span attrs (zeros included) | E4 (xfail) | `…::test_emit_faithfulness_alerts_writes_all_three_signals` |
| `None` tracer is a no-op | E4 (xfail) | `…::test_emit_faithfulness_alerts_null_tracer_is_a_noop` |
| Signal name set | E4 (xfail) | `…::test_faithfulness_signal_names_match_the_locked_set` |
| Non-judge input is TypeError / ValueError | E4 (xfail) | `…::test_collect_rejects_a_non_judge_result` |

Cross-wave reds use `@pytest.mark.xfail(reason="green after E4: …", strict=False)`.
Never `strict=True` (`xfail_strict = true` in this repo).

## Deliverable symbols

Every named symbol has ≥1 direct test (`git grep -c` under `tests/`).

| Symbol | Module / surface | Greening wave |
| --- | --- | --- |
| `eval-gate` (CI job id) | `.github/workflows/ci.yml` | E2 |
| `eval-replay` / `replay-bank` | CI job + Makefile | E2 (Make green) |
| `eval-gate` / `eval-convergence` / `bench-detect` | Makefile | E2 (green) |
| `evals/results/latest.json` | tracked baseline | E2 (green) |
| `GateReport` / `GateReport.regressed_metrics` | `mergecraft.evals.gate` | E2 (green; summary helper RED) |
| `eval_gate` / `load_result_set` | `mergecraft.evals.gate` | E2 (green) |
| `format_pr_gate_summary` | `mergecraft.evals.gate` | E2 |
| `TokenBudget` / `compute_cost` | `mergecraft.agents.token_budget` re-export of `mergecraft.jev.cost` | E4 |
| `PROVIDER_PATHS` | `mergecraft.agents.token_budget` | E4 |
| `bind_run_budget` | `mergecraft.agents.token_budget` | E4 |
| `record_provider_usage` | `mergecraft.agents.token_budget` | E4 |
| `token_budget_for` | `mergecraft.agents.token_budget` | E4 |
| `apply_kill_switch` | `mergecraft.agents.token_budget` | E4 |
| `FaithfulnessSignals` | `mergecraft.evals.faithfulness` | E4 |
| `collect_faithfulness_signals` | `mergecraft.evals.faithfulness` | E4 |
| `emit_faithfulness_alerts` | `mergecraft.evals.faithfulness` | E4 |
| `FAITHFULNESS_SIGNAL_NAMES` | `mergecraft.evals.faithfulness` | E4 |

Shared fixtures / constants: `tests/evals/support_eval_calibration.py`.

## What E2 must implement

1. A blocking `eval-gate` job on `.github/workflows/ci.yml` (PR + push), **not**
   `continue-on-error`, no provider-key env, no `bench-detect`.
2. Job steps run keyless replay (`make eval-replay` or `mergecraft eval replay-bank`)
   then `mergecraft eval gate --baseline evals/results/latest.json --candidate …`.
3. Check summary / `GITHUB_STEP_SUMMARY` states it proves **structural replay**,
   **not** **live detection** quality (E-D3).
4. `mergecraft.evals.gate.format_pr_gate_summary(report)` — string naming
   `regressed_metrics` plus each row's baseline / candidate / delta; rejects a
   non-`GateReport` with `TypeError` or `ValueError`.
5. Do **not** restore `evals/ablation.py`. Do **not** drop `release.yml`'s
   `eval-gate` job or the tracked baseline.

## What E4 must implement

1. `mergecraft.agents.token_budget` re-exports J2 `TokenBudget` and
   `compute_cost` (identity, not a fork). `PROVIDER_PATHS` is
   `{claude, codex, cursor, gemini, opencode, jev}`.
2. `bind_run_budget` around `AgentImpl.run` so a stopped budget never calls
   `_run` and records `diagnostics["reason"] == "kill_switch"` (or that token
   in `error`).
3. `record_provider_usage` is J2 `record_usage` semantics: any `None` token
   count sets `cost_known=False` and does not increment `tokens_used`.
4. `token_budget_for(model=…, max_tokens=…)` + `apply_kill_switch` →
   `"kill_switch"` / `"ok"`.
5. `mergecraft.evals.faithfulness` — pure collector over J4
   `ParallelJudgeResult` (no `AsyncJevClient`, `replaces_verifier` stays
   false). Signals: `unverified_finding_rate`, `contradicts_rate`,
   `quote_verification_failures`. `emit_faithfulness_alerts` writes a
   `mergecraft.faithfulness` span with the three `mergecraft.faithfulness.*`
   attrs (zero is real data); `tracer=None` is a no-op.

## xfail reconciliation

After E2: the `tests/ci/test_eval_pr_gate.py` job-missing failures and the
three `format_pr_gate_summary` ImportErrors should become real passes. After
E4: delete the `E4_XFAIL` markers (`strict=False` only — never flip to
`strict=True`). The xpass ratchet in `tests/conftest.py` will fail the session
if those markers are left on passing tests.
