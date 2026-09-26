# Evals and verification correctness — test plan

Wave plan: `.ignorelocal/waves/43-evals-verify-correctness-wave-plan.md`
Branch: `wave/evals-verify-correctness` (base `origin/main` @ `1ec73a1f`)
Authoring wave: **EV1** (tests-first, RED). Implementation waves: **EV2**
(`evals/`) and **EV3** (`verify/` + `cli/verify_behavior_cmd.py`). Final:
**EV4** (wave-verifier).

This doc is authored in one pass (EV1) — the whole suite for EV2 and EV3, left
RED. It maps every contract the two implementation waves will satisfy to the
test that pins it, and records the expected failure mode today. No xfail
markers are used: collection stays clean and every contract is a genuine
assertion/runtime failure at test time, so EV2/EV3 turn the suite green by
changing `src/` only (tests are frozen after this wave except for the
orchestrator's reconciliation dispatch).

## Thesis the suite pins

Four scorers with one shape — a number that improves when the evidence behind
it gets worse. The tests deliberately construct the failure mode rather than a
happy path:

- the release gate watches rates that a crashed case can only help, and never
  counts the cases the detection fold drops;
- greedy nearest-first matching lets an earlier issue take the only finding a
  later issue had;
- the local criterion heuristic drops the cue words that carry a negation, so
  "No error is shown" passes on a page that says "Error shown";
- `--allow-stub` skips the browser unconditionally and the report does not say
  a stub produced it.

## Environment and invocation

All tests are keyless and offline (synthetic fixtures only; no calibration or
benchmark-number claim). Commands used in EV1:

- `MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/evals tests/verify tests/cli/test_eval_gate_cmd.py tests/cli/test_eval_regression_gate_output.py -q`
- `uv run pytest --collect-only -q <touched files>` (collection check)
- `make lint`, `make typecheck`

## Contract → test mapping

### Gate coverage metrics (implementation EV2)

| Contract (locked decision) | Test(s) | File | RED today? |
| --- | --- | --- | --- |
| Structural `inconclusive_rate` (lower is better) is gated with the shared tolerance band | `test_one_added_structural_inconclusive_regresses_the_gate` | `tests/evals/test_release_gate.py` | yes — metric not compared, gate passes |
| A fully-failed detection half (`cases_run=0`, empty aggregate of 1.0) regresses and names `detection.failed_case_rate` despite `detection.recall` delta `>= 0` | `test_all_failed_detection_half_regresses_and_names_failed_case_rate` | `tests/evals/test_release_gate.py` | yes — gate passes, no `failed_case_rate` row |
| Dropping a failed low-recall case can no longer pass by raising recall | `test_dropping_a_low_recall_case_cannot_pass_by_raising_recall` | `tests/evals/test_release_gate.py` | yes |
| Both sides carrying no detection half keeps today's skip (PR check) | `test_detection_half_is_skipped_when_both_sides_do_not_carry_it` | `tests/evals/test_release_gate.py` | no (regression guard, already green) |
| `require_halves=True` fails a candidate missing the baseline detection half and names it; without the flag it is skipped | `test_require_halves_fails_a_candidate_missing_the_baseline_detection_half` | `tests/evals/test_release_gate.py` | yes — no `require_halves` keyword |
| `require_halves=True` passes when both sides carry the half | `test_require_halves_passes_when_both_sides_carry_the_half` | `tests/evals/test_release_gate.py` | yes — keyword absent |
| Committed baseline self-compares clean and the delta ledger carries `inconclusive_rate` (detection skipped, never fabricated) | `test_clean_committed_baseline_passes_eval_gate`, `test_committed_baseline_self_compare_carries_the_inconclusive_rate_row` | `tests/evals/test_eval_pr_gate.py` | yes — row missing from the ledger |
| CLI `eval gate --baseline --candidate` exits non-zero and the step summary names `inconclusive_rate` with baseline/candidate/delta | `test_gate_regression_names_inconclusive_rate_in_the_step_summary` | `tests/cli/test_eval_gate_cmd.py` | yes — no regression detected, exit 0 |
| CLI `--require-halves` fails a candidate missing the detection half; absent flag keeps the skip | `test_require_halves_flag_fails_a_candidate_missing_the_detection_half` | `tests/cli/test_eval_gate_cmd.py` | yes — unknown option (exit 2) |

### `DetectionMetrics.failed_case_rate` (implementation EV2)

| Contract | Test(s) | File | RED today? |
| --- | --- | --- | --- |
| Computed property `cases_failed / (cases_run + cases_failed)`, lower is better | `test_failed_case_rate_is_zero_with_no_failures`, `test_failed_case_rate_is_one_when_every_case_failed`, `test_failed_case_rate_is_the_share_of_attempts_that_failed[...]` | `tests/evals/test_live_run.py` | yes — no attribute |
| Not serialised (no wire-schema change); `cases_failed` defaults to `0` so old artifacts load | `test_failed_case_rate_is_computed_not_a_serialised_field` | `tests/evals/test_live_run.py` | yes — no attribute |
| `SCORER_VERSION` bumped to `1.1.0` and the value is pinned on result sets | `test_scorer_version_is_bumped_for_the_new_matching_rule`, `test_structural_result_set_pins_the_current_scorer_version` | `tests/evals/test_benchmark_gate_metrics.py` | yes |

### Maximum-cardinality matching (implementation EV2)

| Contract | Test(s) | File | RED today? |
| --- | --- | --- | --- |
| Part 1 counter-example (A@10, B@14, f0@12, f1@7, slack 3) scores 2/2 | `test_maximum_matching_recovers_the_later_issues_only_candidate` | `tests/evals/test_scoring.py` | yes — greedy yields 1 |
| Recall does not depend on baseline issue order | `test_matching_is_order_independent_for_the_counter_example` | `tests/evals/test_scoring.py` | yes |
| Deterministic assignment across repeated calls | `test_matching_is_deterministic_across_repeated_calls` | `tests/evals/test_scoring.py` | no (regression guard, already green) |
| One finding cannot satisfy two issues | `test_one_finding_cannot_satisfy_two_issues` | `tests/evals/test_scoring.py` | no — must stay green |
| Each issue claims its closest finding when there is no contention | `test_each_issue_claims_its_closest_finding` | `tests/evals/test_scoring.py` | no — must stay green |

### Local negation is never a verdict (implementation EV3)

> **EV3 remediation — 2026-09-25 (PR #894 self-review).** EV3 placed the
> negation guard *after* the hard-coded `"still visible"` / `"mismatch"`
> branches, so a criterion that was both negated and phrased with one of those
> phrases escaped the fail-closed rule (`"The image is not still visible"` →
> `pass` on `"Error shown"`; `"No mismatch is shown"` → `fail` on
> `"layout mismatch in footer"`). EV-D5 says a negated criterion is always
> `unverified`, so the guard must be consulted first; the special cases stay for
> non-negated criteria. The three rows below pin both sides of that ordering and
> are the RED evidence for the follow-up fix.

| Contract | Test(s) | File | RED today? |
| --- | --- | --- | --- |
| `"No error is shown"` / `"Error is not shown"` on `"Error shown"` → `unverified`, named reason, report not `pass` | `test_audited_negated_criteria_against_the_opposite_page_are_unverified` | `tests/verify/test_local_negation.py` (new) | yes — passes today |
| Every cue in the locked set (`no`, `not`, `never`, `none`, `nothing`, `without`, `cannot`, `n't`) is never a local `pass` | `test_every_negation_cue_is_never_a_local_pass[...]` | `tests/verify/test_local_negation.py` (new) | yes |
| A plain positive criterion still passes on a matching page | `test_plain_positive_criterion_still_passes_on_a_matching_page` | `tests/verify/test_local_negation.py` (new) | no — must stay green |
| Negated reproduce expectation is `partial`, never `reproduced` | `test_negated_reproduce_expectation_is_partial_never_reproduced` | `tests/verify/test_local_negation.py` (new) | yes — reports `reproduced` |
| `"still visible"` special case unchanged (fail when still visible, pass when gone) | `test_still_visible_special_case_is_unchanged_when_it_is_still_visible`, `test_still_visible_special_case_is_unchanged_when_it_is_gone` | `tests/verify/test_local_negation.py` (new) | no — must stay green |
| The negation guard outranks the special cases: a negated criterion combining a cue with `"still visible"` / `"mismatch"` is `unverified` (named reason) even when the page does not show the phrase | `test_negation_wins_over_a_special_case_phrase_on_the_opposite_page[...]` | `tests/verify/test_local_negation.py` | yes — guard at `runner.py:378` runs after the `:374-377` special cases |
| The same guard holds when the page *does* show the special-case phrase (the guard is not the old branch re-stated) | `test_negation_wins_over_a_special_case_phrase_when_the_page_shows_it[...]` | `tests/verify/test_local_negation.py` | yes — scores `fail` today |
| Non-negated `"mismatch"` criterion keeps the special-case verdict (fail when shown, pass when not) | `test_non_negated_mismatch_special_case_is_unchanged[...]` | `tests/verify/test_local_negation.py` | no — regression guard, must stay green |

### `--allow-stub` is a fallback; reports sign their driver (implementation EV3)

| Contract | Test(s) | File | RED today? |
| --- | --- | --- | --- |
| With the stack available, `_resolve_driver(allow_stub=True)` binds the live CDP driver (not the stub) | `test_resolve_driver_prefers_the_live_driver_when_the_stack_is_available` | `tests/verify/test_browser_stack.py` | yes — returns stub |
| With availability patched `False`, `allow_stub=True` returns the stub | `test_resolve_driver_uses_the_stub_only_when_the_stack_is_unavailable` | `tests/verify/test_browser_stack.py` | no — but now patches availability explicitly |
| Without `--allow-stub` and unavailable, still raises | `test_resolve_driver_raises_when_cdp_unreachable` | `tests/verify/test_browser_stack.py` | no — must stay green |
| Every `--allow-stub` CLI test patches availability off explicitly and `report.json` carries `driver == "stub"` | `test_cli_allow_stub_writes_a_report`, `test_cli_reproduce_mode_accepts_issue_file` | `tests/verify/test_cli.py` | yes — `KeyError: 'driver'` |
| A CDP-driven run stamps `"cdp"`; the value is a serialised field | `test_cdp_driven_run_stamps_the_cdp_driver` | `tests/verify/test_driver_provenance.py` (new) | yes — no `driver_kind` keyword, no field |
| A stub-driven run stamps `"stub"` | `test_stub_driven_run_stamps_the_stub_driver` | `tests/verify/test_driver_provenance.py` (new) | yes |
| A skipped report has `driver is None` | `test_skipped_report_has_no_driver` | `tests/verify/test_driver_provenance.py` (new) | yes — no attribute |
| A report JSON without `driver` still validates | `test_report_json_without_the_driver_key_still_validates` | `tests/verify/test_driver_provenance.py` (new) | yes — attribute missing |
| `driver` is optional, defaults to `None`, and is a closed literal (`cdp`/`stub`) | `test_driver_is_optional_and_rejects_unknown_kinds` | `tests/verify/test_driver_provenance.py` (new) | yes |
| The markdown view renders the driver line | `test_markdown_view_shows_the_driver_line` | `tests/verify/test_driver_provenance.py` (new) | yes |
| Report field-set pin tolerates exactly the documented additive `driver` field | `test_report_schema_version_is_pinned` | `tests/verify/test_report_schema.py` | no — stays green in both phases |

## Hard hazard: no ambient CDP endpoint

Fallback semantics mean an `--allow-stub` test that does not patch availability
probes `MERGECRAFT_CDP_URL` first and could bind an operator's real Chrome.
Mitigation, pinned by the suite:

- `tests/verify/test_cli.py` module fixture sets `MERGECRAFT_CDP_URL` to a
  closed port and patches both `mergecraft.browser.launch.browser_stack_available`
  and `mergecraft.browser.availability.browser_stack_available` off; each
  `--allow-stub` test additionally patches availability explicitly.
- `tests/verify/test_browser_stack.py` patches both probe symbols in every
  unavailable path, and the available path runs against `fake_cdp_endpoint`.

## Matrix coverage summary

| Layer | Coverage |
| --- | --- |
| Unit | `DetectionMetrics.failed_case_rate` arithmetic and non-serialisation; `SCORER_VERSION`; `driver` field optionality/literal; determinism of the matcher. |
| Integration | `eval_gate` over real `BenchmarkResultSet` fixtures (structural override + detection join); `run_verify_behavior` local heuristic with an injected fake driver; CLI `eval gate` through `load_result_set` + step summary. |
| Functional / E2E | `mergecraft eval gate --baseline --candidate` via `CliRunner` (exit code + `GITHUB_STEP_SUMMARY`); `mergecraft verify-behavior --allow-stub` via `CliRunner` (report.json `driver`). |

Each layer covers happy path, edge cases (all-failed fold, zero denominator,
empty detection, missing half, opposite-order baselines, every cue word), and
error handling (unknown driver literal, unknown `--require-halves` handling,
unreachable CDP refusal).

## Ambiguities flagged (not resolved by weakening a test)

1. **`_resolve_driver` return shape.** The wave prose (EV3.4) says the CLI
   returns "the driver kind with it", but the locked decision table only locks
   the report field. `tests/verify/test_browser_stack.py` unwraps a
   `(driver, kind)` tuple if present and otherwise accepts a bare driver, so
   the driver class is pinned either way. The provenance contract is pinned
   separately through `driver_kind` and the report field.
2. **`driver_kind` keyword name.** Threading the kind through
   `run_verify_behavior(..., driver_kind=…)` is named in wave prose (EV3.3),
   not in the decision table; `tests/verify/test_driver_provenance.py` pins
   that name. If the implementation chooses another, the orchestrator must
   re-dispatch the test-creator rather than the executor editing tests.
3. **Named unverified reason wording.** The reason string is asserted to be
   non-empty and to name the criterion or the word "negat" — not pinned to an
   exact template, because no decision row fixes one.
4. **Step-summary surface for the CLI gate test.** The gate's human output
   omits metric rows on the non-existent-bank branch, so the CLI test pins the
   `GITHUB_STEP_SUMMARY` file, which `append_step_summary` writes on every
   baseline/candidate run.
