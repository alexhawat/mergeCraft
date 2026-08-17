# Eval benchmark B1 — F1, FP ledger, closed-world metrics test plan (RED)

Wave plan: `.ignorelocal/waves/issues-eval-benchmark-numbers-wave-plan.md` — PR B1
Worktree: `mergecraft-bench-b1-metrics` @ `wave/bench-b1-metrics`
Anchor: `src/mergecraft/evals/scoring.py`

## Design-gate findings (B1.0) — for the B1.2 implementer to confirm

### 1. Category vocabulary — two vocabularies, not one, and that's correct

B1.0's third bullet asks whether `review_taxonomy.py`'s category vocabulary
aligns with `evals/benchmark.py`'s four `corpus_class_for()` buckets
(`correctness` / `security` / `cross_file` / `adversarial_noop`).

**Verified: they are answering different questions and should stay separate.**

- `corpus_class_for()` classifies a **bank `Case`** (`evals/store.py::Case`,
  used for structural decision replay in `evals/benchmark.py`) by its id
  prefix / `case.category` field, whose values are things like
  `false_positive`, `missed_finding`, `rejected`, `reverted` — none of which
  come from `review_taxonomy.py` today. This is a **case-level** bucket: "what
  kind of regression scenario is this eval-bank entry."
- `review_taxonomy.FINDING_CATEGORIES` (`"Functional Correctness"`,
  `"Data Integrity & Atomicity"`, `"Security & Privacy"`,
  `"Stability & Availability"`, `"Performance & Scalability"`,
  `"Maintainability & Code Quality"`) is a **finding-level** taxonomy — what a
  single reported finding is *about*. `BaselineIssue.category` /
  `ReportedFinding.category` in `scoring.py` are free-text fields that already
  compare case-insensitively against each other, with no connection to
  `corpus_class_for()`.

B1's `by_category` breakdown (this test plan) buckets **findings**, so it
reuses `review_taxonomy.FINDING_CATEGORIES` — pinned by
`test_by_category_keys_use_the_review_taxonomy_vocabulary` in
`tests/evals/test_scoring_metrics.py`, which also asserts the four
`corpus_class_for()` bucket names never leak into `by_category`. B7's report
template confirms both axes coexist side by side (`Detection` section's
`by_category` breakdown vs. the separate `By class` line using the four
buckets) — this is not a naming collision to fix, it is two legitimately
different rollups. **No source change needed for this finding** — B1.2 should
just use `review_taxonomy.FINDING_CATEGORIES` for `by_category` keys and leave
`corpus_class_for()` untouched.

### 2. Where `closed_world` lives — a judgment call pinned by these tests

B1.0's first bullet locks "closed-world flag lives on the case, not the
report." But `scoring.py` has no `Case` wrapper — `score_findings()` takes
flat `list[BaselineIssue]` / `list[ReportedFinding]`, and a **clean**
closed-world case (the exact scenario the checklist names: "0 findings ->
`strict_precision == 1.0`") has **zero** `BaselineIssue` rows, so the flag
cannot live on a per-issue field — there is no issue instance to carry it.

**Pinned here:** `closed_world` is a keyword-only parameter on
`score_findings()` (mirroring the existing `slack` parameter), and
`ScoreReport` gains a `closed_world: bool = False` field that echoes the
call-time input — not as a new independently-computed metric, but as the
minimum state needed for `.strict_precision` to know whether it is allowed to
answer. `AggregateScoreReport.fold_score_reports()` then reads this field off
each per-case report to decide the closed-world subset for
`false_positives_per_case` / `clean_case_fp_rate`. If the implementer finds a
cleaner way to satisfy the same test assertions without a `ScoreReport.
closed_world` field, that's a valid alternative — the tests only assert on
`strict_precision`, `false_positives`, and `unadjudicated` values, never on
the literal existence of a `closed_world` attribute.

### 3. `false_positives_per_case` / `clean_case_fp_rate` — closed-world subset only

Per D4, an open-world case can never confirm a false positive, so both
aggregate rates are computed **only over `closed_world=True` reports** in the
folded set. Including open-world reports (whose `false_positives` is always
0) would dilute the rate as a function of how many open-world cases happen to
be in the corpus, which measures corpus composition, not FP behaviour. Pinned
by `test_fold_false_positives_per_case_averages_over_closed_world_cases_only`
and `test_fold_clean_case_fp_rate_is_the_fraction_of_closed_cases_with_a_false_finding`
in `tests/evals/test_scoring_aggregate.py`.

## Locked decisions exercised

| ID | Decision | Tests |
|----|----------|-------|
| **D3** | `ScoreReport` extended, never replaced; `extra="forbid"` preserved; `precision` kept as a deprecated alias | `test_score_report_still_forbids_unknown_fields`, `test_existing_precision_alias_matches_corpus_confirmed_precision`, all of `tests/cli/test_eval_score_cmd.py` |
| **D4** | Two precision metrics — `corpus_confirmed_precision` (open-world) and `strict_precision` (closed-world only, raises otherwise) | `test_strict_precision_raises_on_an_open_world_report`, `test_clean_case_zero_findings_has_strict_precision_one`, `test_clean_case_with_false_findings_scores_strict_precision_zero` |
| **D5** | Unmatched findings are `unadjudicated`, not `false_positive`, until judged (both reported) | `test_open_world_unmatched_findings_are_unadjudicated_not_false_positive`, `test_clean_case_with_false_findings_scores_strict_precision_zero` |
| B1.0 bullet 2 | `f1` is `0.0`, never `NaN`, when precision and recall are both 0 | `test_f1_is_zero_not_nan_when_precision_and_recall_are_both_zero` |

## xfail schedule

None. Every new-contract test in this plan fails via `AttributeError` /
`TypeError` at assertion or call time (not at collection) — see "Deferred
imports" below — so no `xfail` marker is needed; the suite is red by ordinary
test failure, which is the cleanest signal for the B1.2 implementer.

## Deferred imports (why collection stays green)

`fold_score_reports` does not exist anywhere in `scoring.py` yet. Importing it
by name (`from mergecraft.evals.scoring import fold_score_reports`) would
raise `ImportError` at **collection** time and fail the whole test file, not
just the tests that use it. `tests/evals/test_scoring_aggregate.py` instead
imports the module (`from mergecraft.evals import scoring`) and calls
`scoring.fold_score_reports(...)` inside each test body, so the
`AttributeError` surfaces as an ordinary per-test failure. Every other new
symbol referenced in this plan (`ScoreReport.f1`, `.strict_precision`,
`.by_category`, ..., `score_findings(..., closed_world=...)`) is an attribute
or keyword access on an object/function that already exists today, so it
naturally fails at call/assertion time without needing this treatment.

## Contract matrix

| Contract | Layer | Scenario | Primary test |
|----------|-------|----------|--------------|
| F1 worked example (32 TP / 18 unadjudicated / 8 FN -> P 64.0% / R 80.0% / F1 71.1%) | Unit | Happy | `test_f1_matches_the_worked_example` |
| F1 degenerate zeros | Unit | Edge | `test_f1_is_zero_not_nan_when_precision_and_recall_are_both_zero` |
| Empty corpus | Unit | Edge | `test_empty_corpus_is_vacuously_complete` |
| Closed-world clean case, 0 findings | Unit | Happy | `test_clean_case_zero_findings_has_strict_precision_one` |
| Closed-world clean case, 2 false findings | Unit | Edge | `test_clean_case_with_false_findings_scores_strict_precision_zero` |
| `strict_precision` on open-world raises | Unit | Error | `test_strict_precision_raises_on_an_open_world_report` |
| Open-world unmatched -> `unadjudicated`, not `false_positives` | Unit | Happy | `test_open_world_unmatched_findings_are_unadjudicated_not_false_positive` |
| `by_category` / `by_severity` sum to totals | Unit | Happy | `test_by_category_and_by_severity_sum_back_to_the_totals` |
| `by_category` keys use `review_taxonomy`, not `corpus_class_for()` | Unit | Happy | `test_by_category_keys_use_the_review_taxonomy_vocabulary` |
| `by_severity` keys cover `FINDING_SEVERITIES` | Unit | Happy | `test_by_severity_keys_use_the_normalized_finding_severities` |
| `precision` deprecated alias == `corpus_confirmed_precision` | Unit | Happy | `test_existing_precision_alias_matches_corpus_confirmed_precision` |
| `ScoreReport` still forbids unknown fields (regression) | Unit | Error | `test_score_report_still_forbids_unknown_fields` |
| `AggregateScoreReport` folds case count | Integration | Happy | `test_fold_counts_every_report_as_one_case` |
| `AggregateScoreReport` sums totals | Integration | Happy | `test_fold_sums_totals_across_cases` |
| `false_positives_per_case` — closed-world subset only | Integration | Happy | `test_fold_false_positives_per_case_averages_over_closed_world_cases_only` |
| `clean_case_fp_rate` — closed-world subset only | Integration | Happy | `test_fold_clean_case_fp_rate_is_the_fraction_of_closed_cases_with_a_false_finding` |
| Folding zero reports doesn't divide by zero | Integration | Edge | `test_fold_of_zero_reports_does_not_divide_by_zero` |
| Aggregate `by_category` / `by_severity` sum to totals | Integration | Happy | `test_fold_by_category_sums_back_to_the_aggregate_totals`, `test_fold_by_severity_sums_back_to_the_aggregate_totals` |
| `mergecraft eval score --json` key set unchanged (D3) | Functional | Happy (regression) | `test_eval_score_json_output_keeps_its_existing_key_set` |
| `mergecraft eval score --json` values unchanged (D3) | Functional | Happy (regression) | `test_eval_score_json_output_values_are_unchanged` |
| `mergecraft eval score` human output unchanged (D3) | Functional | Happy (regression) | `test_eval_score_human_output_keeps_its_existing_lines` |
| `--min-recall` gate unchanged (D3) | Functional | Error (regression) | `test_eval_score_min_recall_gate_is_unchanged` |

## Implementation notes for B1.2

- Add `closed_world: bool = False` keyword-only parameter to `score_findings()`.
- Extend `ScoreReport` (never replace, keep `extra="forbid"`) with: `closed_world`,
  `f1`, `corpus_confirmed_precision`, `strict_precision`, `false_positives`,
  `unadjudicated`, `false_negatives`, `by_category`, `by_severity`. Keep
  `precision` as a property/alias returning the same value as
  `corpus_confirmed_precision`.
- New small breakdown model (e.g. `CategoryBreakdown`, `extra="forbid"`) with
  at least `total_issues: int` and `found: int` — tests only read these two
  attributes off `by_category` / `by_severity` dict values, so additional
  fields (e.g. per-category recall) are free to add.
- New `AggregateScoreReport` model + `fold_score_reports(reports: list[ScoreReport]) -> AggregateScoreReport`
  free function in `scoring.py`, exported from `evals/scoring.py` and (per the
  existing `evals/__init__.py` re-export pattern) from `mergecraft.evals`.
- `cli/eval_cmd.py::score` is intentionally **not** touched by B1 — its
  `--json` dict stays hand-built from the eight existing keys. B3 is the PR
  that will decide whether/how the new fields reach the CLI.
- Docstrings should carry the D4/D5 tone already set by the existing
  `precision` property docstring in `scoring.py`.

## Verification

- `MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/evals/test_scoring_metrics.py tests/evals/test_scoring_aggregate.py tests/cli/test_eval_score_cmd.py -q`
  — collects cleanly today; all new-contract tests fail with `AttributeError`
  / `TypeError` (not collection errors); the D3 regression-guard tests already
  pass.
- `make lint` — ruff check/format clean on the three new files.
- `make typecheck` — scoped to `src/mergecraft` only (`Makefile:67`), so these
  test files are not mypy-checked; no action needed here.
