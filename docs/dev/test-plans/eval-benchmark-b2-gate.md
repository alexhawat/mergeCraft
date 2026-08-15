# Eval benchmark B2 — directional gate metrics and version pins test plan (RED)

Wave plan: `.ignorelocal/waves/issues-eval-benchmark-numbers-wave-plan.md` — PR B2
Worktree: `mergecraft-bench-b2-gate` @ `wave/bench-b2-gate` (parent: `wave/bench-b1-metrics`)
Anchors: `src/mergecraft/evals/benchmark.py` (`BenchmarkMetrics.decision_replay_pass_rate`,
`VersionPins`, `run_structural_replay`, `CaseReplayRow`, `corpus_class_for()`) ·
`src/mergecraft/agents/gates.py` `decide_approval` · `src/mergecraft/run_outcome.py:22` `RunOutcome`.

## Design-gate findings (B2.0) — for the B2.2 implementer to confirm

### 1. Expected/current decision pair — confirmed, no new field needed

`CaseReplayRow.expected_decision` / `.current_decision` (both already on the model, populated
by `run_structural_replay()`'s existing loop from `ReplayDiff`) are sufficient to derive
approve-vs-block direction. No new field is needed on `CaseReplayRow` for this half of the
matrix.

### 2. Buggy vs clean classification — `corpus_class_for()`, per the plan's stated default

`adversarial_noop` → **clean**; `{correctness, security, cross_file}` → **buggy**. This is
exactly the four-bucket vocabulary `corpus_class_for()` already returns — reused, not
reinvented (per B1's precedent reconciliation in
`docs/dev/test-plans/eval-benchmark-b1-metrics.md`, which is about the *finding-level*
`review_taxonomy` vocabulary and explicitly does not apply to this axis — this really is the
`corpus_class_for()` axis, confirmed by reading the plan's own footnote).

### 3. Inconclusive — the load-bearing design call this PR makes

**This is not derivable from `current_decision` alone**, and that is the subtlety B2.0's third
bullet is actually flagging. `decide_approval()` returns the literal string `"neutral"` for two
semantically different reasons:

- **A crashed run** (`run_succeeded=False` — the `RunOutcome.infra_error` / `.timed_out` /
  every non-`passed` outcome path, per `run_outcome.run_succeeded_for_outcome()` and
  `decide_approval`'s own docstring in `agents/gates.py`): the review never actually looked at
  the diff. This case must **not** be credited as a correct block.
- **A genuinely clean run with zero findings** (`run_succeeded=True`, trusted, no findings):
  the review looked, found nothing to flag, and correctly declined to auto-merge on absence of
  evidence alone (`agents/gates.py`'s "#41 hard rule"). This is the *expected steady-state
  outcome for a clean/no-op case* — it must **not** be treated as inconclusive; it is the
  correct "waved through" outcome for a clean case.

Both produce `current_decision == "neutral"`. **`Case.run_succeeded: bool` is therefore the
signal that decides inconclusive, not the decision string** — and `run_structural_replay()`'s
existing per-case loop already has `case` (not just the `CaseReplayRow` it builds) in scope, so
the gate-matrix aggregation must read `case.run_succeeded` directly in that same loop. No new
field on `CaseReplayRow` is required for this either, since the aggregation can happen inline
where `case` is already available — but the implementer must not try to derive inconclusive
purely from `row.current_decision` once rows are the only thing in scope, because that
conflates the two "neutral" cases above.

**Locked rule (pinned by tests in this plan):**

- `inconclusive` iff `case.run_succeeded is False`, **or** `current_decision in {None,
  "unavailable"}` (the replay-engine-could-not-decide / closed-lane-vocabulary "no answer"
  cases — includes every non-replayable case, i.e. `recorded_findings is None`).
- Otherwise, classify the decision by direction:
  - **block-like** (counts as "caught"/"correct block" for buggy, "unsafe block" for clean):
    `{"failure", "block", "request_changes", "require_human_review", "require_more_tests",
    "quarantine", "escalate"}`.
  - **wave-through-like** (counts as "unsafe approval" for buggy, "correct approval" for
    clean): `{"success", "auto_merge", "neutral"}` — note `"neutral"` is in this bucket, not
    the inconclusive one, when `run_succeeded=True` (see the clean-zero-findings case above).

This is confirmed against `evals/cases/issue-75-crashed-run-not-permissive.md`: `run_succeeded:
false`, `recorded_findings: []`, `expected_decision: neutral`. Replay recomputes
`current_decision = "neutral"` and `status = "passed"` (expected matches current — the existing
structural-replay contract is unaffected). Under the locked rule, this row is `inconclusive`
(via `run_succeeded is False`), **not** counted as a correct block, matching the plan's
checklist bullet exactly. `test_crashed_run_on_a_buggy_case_is_inconclusive_not_a_correct_block`
pins this with a synthetic case built from the same front-matter shape (`run_succeeded=False`,
`recorded_findings=[]`), and `test_non_replayable_buggy_case_is_inconclusive_not_silently_
dropped` extends the same rule to `recorded_findings=None`.

### Rate formulas (test-creator design decision, not stated by the plan)

The plan names the fields (`unsafe_approval_rate`, `clean_block_rate`, `inconclusive_rate`) but
not their exact denominators. Pinned here:

- `unsafe_approval_rate = buggy_unsafe_approval / (buggy_total - buggy_inconclusive)`, `0.0`
  when the denominator is `0`.
- `clean_block_rate = clean_unsafe_block / (clean_total - clean_inconclusive)`, `0.0` when the
  denominator is `0`.
- `inconclusive_rate = (buggy_inconclusive + clean_inconclusive) / cases_total`, `0.0` when
  `cases_total` is `0`.

Rationale: excluding inconclusive cases from the direction-rate denominators means a spike in
infra failures cannot silently *improve* the reported unsafe-approval or clean-block rate by
diluting it — the directional rates measure "of the cases that produced a real signal, how many
went the wrong way," and `inconclusive_rate` separately tracks how often the harness failed to
produce a signal at all. If the B2.2 implementer finds a different formula better matches an
existing consumer's expectations, the tests only assert on the numeric *value* for specific
worked inputs (never on the literal existence of a denominator-computation helper), so an
equivalent alternative formula that produces the same worked-example numbers is a valid
substitution — but it must still satisfy
`test_crashed_run_on_a_buggy_case_is_inconclusive_not_a_correct_block`'s non-dilution assertion
(`1/3`, not `1/4`).

## Locked decisions exercised

| ID | Decision | Tests |
|----|----------|-------|
| **D3** | `BenchmarkMetrics` extended, never replaced; `extra="forbid"` preserved; `decision_replay_pass_rate` unaffected | `test_benchmark_metrics_accepts_the_full_gate_shape_and_still_forbids_extras`, `test_decision_replay_pass_rate_is_unchanged_by_the_new_gate_fields` |
| **D9** | Every published number carries the full pin block; a missing pin is a hard failure | `test_version_pins_n6_fields_are_required_not_optional` (parametrized over all four N6 fields), `test_version_pins_round_trips_with_every_n6_field` |
| **D12** | ≥2 providers, each pinned by model id + `model_pin`, reported per provider | `test_version_pins_round_trips_with_every_n6_field` (two providers), `test_version_pins_reviewing_model_rejects_an_empty_pin_set` |
| B2.0 bullet 2 | Buggy/clean from `corpus_class_for()`, not a new field | `test_gate_matrix_rollup_by_corpus_class` |
| B2.0 bullet 3 / issue-75 | Crashed run is inconclusive, never a correct block | `test_crashed_run_on_a_buggy_case_is_inconclusive_not_a_correct_block` |

## xfail schedule

None. As with B1, every new-contract test fails via `AttributeError` (reading a field that does
not exist yet on an already-existing `BenchmarkMetrics`/`VersionPins` instance) or
`ValidationError`/`AssertionError` at call time, never at collection — every symbol imported by
name in `tests/evals/test_benchmark_gate_metrics.py` (`BenchmarkMetrics`, `VersionPins`,
`RESULT_SET_SCHEMA_VERSION`, `run_structural_replay`) already exists today, so no deferred-import
treatment is needed (matches B1's "Deferred imports" note).

**Two tests are expected to already be green** and are not part of the RED count:

- `test_decision_replay_pass_rate_is_unchanged_by_the_new_gate_fields` — a pure D3 regression
  guard; it only exercises pre-existing `BenchmarkMetrics` fields.
- `test_version_pins_reviewing_model_rejects_an_empty_pin_set` — currently passes for an
  incidental reason (constructing `VersionPins` with any of the four N6 kwargs already raises
  `ValidationError` via `extra="forbid"`, regardless of `reviewing_model`'s content). Once N6
  lands and the other three fields are recognized, this test starts exercising the intended
  `min_length=1`-style constraint on `reviewing_model` for the right reason. If the B2.2
  implementer omits that constraint, this test will start failing with "DID NOT RAISE" instead
  of continuing to pass — that is the intended discriminator.

## Contract matrix

| Contract | Layer | Scenario | Primary test |
|----------|-------|----------|--------------|
| Gate matrix worked example (21/2 buggy, 24/3 clean → 8.7% / 11.1%) | Integration | Happy | `test_gate_matrix_matches_the_worked_example` |
| Crashed run on a buggy case → inconclusive, not a correct block | Integration | Edge | `test_crashed_run_on_a_buggy_case_is_inconclusive_not_a_correct_block` |
| Non-replayable case (`recorded_findings=None`) → inconclusive, not dropped | Integration | Edge | `test_non_replayable_buggy_case_is_inconclusive_not_silently_dropped` |
| Per-`corpus_class` rollup reuses `corpus_class_for()`'s four buckets | Integration | Happy | `test_gate_matrix_rollup_by_corpus_class` |
| All-buggy or all-clean bank does not divide by zero | Integration | Edge | `test_zero_buggy_or_zero_clean_cases_does_not_divide_by_zero` |
| `BenchmarkMetrics` accepts the full gate shape; still forbids unknown fields (D3) | Unit | Happy / Error (regression) | `test_benchmark_metrics_accepts_the_full_gate_shape_and_still_forbids_extras` |
| `decision_replay_pass_rate` unchanged by the new fields (D3) | Integration | Happy (regression) | `test_decision_replay_pass_rate_is_unchanged_by_the_new_gate_fields` |
| `RESULT_SET_SCHEMA_VERSION` bumped to `1.1.0` | Unit | Happy | `test_result_set_schema_version_bumped_to_1_1_0` |
| `VersionPins` round-trips every N6 field | Unit | Happy | `test_version_pins_round_trips_with_every_n6_field` |
| Each N6 field is required, not optional (D9) | Unit | Error | `test_version_pins_n6_fields_are_required_not_optional[...]` (×4) |
| `reviewing_model` rejects an empty pin set (D12) | Unit | Error | `test_version_pins_reviewing_model_rejects_an_empty_pin_set` |

## Implementation notes for B2.2

- Extend `BenchmarkMetrics` (never replace, keep `extra="forbid"`) with: `unsafe_approval_rate:
  float`, `clean_block_rate: float`, `inconclusive_rate: float`, `gate_matrix` (a nested model
  or dict with `buggy_total`, `buggy_correct_block`, `buggy_unsafe_approval`,
  `buggy_inconclusive`, `clean_total`, `clean_correct_approval`, `clean_unsafe_block`,
  `clean_inconclusive`), `by_corpus_class: dict[str, ...]` keyed by the four
  `corpus_class_for()` buckets, each with `total` / `correct` / `incorrect` / `inconclusive`.
  The tests never import a nested model class by name — they pass and read plain dicts, so any
  concrete pydantic submodel shape with those field names satisfies them.
- Extend `VersionPins` with `mergecraft_commit: str` (promote `_git_head_sha()` from
  fallback-only to a first-class required field — call it unconditionally rather than only on
  `_git_corpus_commit()`'s except path), `reviewing_model: dict[str, ...]` (per-provider
  `model_id` + `model_pin`, non-empty), `scorer_version: str`, `line_slack: int`. All four are
  **required** fields (no default), per D9.
- Bump `RESULT_SET_SCHEMA_VERSION` to `"1.1.0"` and refresh the committed
  `evals/results/latest.json` (not touched by this test-authoring pass — B2.2's job).
- The gate-matrix and `by_corpus_class` aggregation must happen where `case.run_succeeded` is in
  scope (`run_structural_replay()`'s existing per-case loop), not purely from
  `CaseReplayRow.current_decision` — see design-gate finding 3 above.
- `mergecraft eval replay-bank --gate` surfacing the matrix in human output and the accompanying
  `make reference-docs` run (D14) are B2.2 CLI/doc work, out of scope for this RED pass — no
  CLI-level test is included here; `src/mergecraft/cli/eval_cmd.py` was read only to confirm
  `replay_bank_cmd` consumes `result.metrics.*` by attribute (not by hand-building
  `BenchmarkMetrics`/`VersionPins`), so no existing CLI test needs updating for the new required
  `VersionPins` fields.

## Verification

- `MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/evals/test_benchmark_gate_metrics.py -q` —
  collects cleanly today (0 collection errors); 12 failed / 2 passed, all failures via
  `AttributeError` / `ValidationError` / `AssertionError` at call/assertion time (not
  collection).
- `MERGECRAFT_PYTEST_JOBS=0 uv run pytest tests/evals --collect-only -q` — 143 tests collected,
  confirming the new file does not break collection of the rest of `tests/evals/`.
- `make lint` — clean (ruff check + format + loguru-only + action-yml hygiene, repo-wide).
- `make typecheck` — clean; mypy strict is scoped to `src/mergecraft` only (`Makefile:67`), so
  this test file is not mypy-checked, consistent with B1's note.
