# PR DG1 — finding precision — test plan (DG1.1)

Wave plan: `.ignorelocal/waves/05-review-depth-governance-wave-plan.md` (PR DG1)
Worktree: `../mergecraft-dg1-finding-precision` @ `wave/dg1-finding-precision`
Authoring wave: **DG1.1** (tests-first). Implementation: **DG1.2**.
xfail-reconciliation: **post-DG1.2** (complete).

Locked decisions: **D2** (causality field on blocking findings), **D3** (baseline
suppression via `baseComparison`), **D4** (classify generated/vendored, do not
drop from scope), **convention 7** (suppression audit trail).

## xfail schedule

Fourteen DG1.1 tests use `@pytest.mark.xfail(reason="green after DG1.2",
strict=False)`. One regression pin passes today.

| Test file | Tests | Marker | Status pre-DG1.2 |
|-----------|-------|--------|------------------|
| `tests/findings/test_dedup.py` | 3 | xfail | **RED** |
| `tests/findings/test_severity_rubric.py` | 2 + 1 pin | xfail / none | **1 PASS, 2 RED** |
| `tests/findings/test_causality.py` | 2 | xfail | **RED** |
| `tests/analyzers/test_baseline_suppression.py` | 4 | xfail | **RED** |
| `tests/classify/test_generated_files.py` | 2 | xfail | **RED** |
| `tests/findings/test_precision_corpus.py` | 1 | xfail | **RED** |

**Acceptance (DG1.1):** 15 collected; 1 pass; 14 xfail. `make lint` + `make typecheck`
clean.

## Target API DG1.2 must satisfy

### `src/mergecraft/findings/dedup.py` (new)

| Symbol | Contract |
|--------|----------|
| `dedupe_findings(findings)` | Collapse duplicate defects before the judge: normalized location + category + semantic body comparison. Two lenses / paraphrases → one finding. Distinct categories on one line → not merged. |

### `src/mergecraft/findings/severity_rubric.py` (new)

| Symbol | Contract |
|--------|----------|
| `SEVERITY_RUBRIC` | Code-defined tuple/dict of rubric rules — not prompt prose |
| `apply_severity_rubric(finding, *, model_assigned_severity)` | Normalize inflated model severity; style nits must not remain blocking |

Regression pin: `agents/gates.py::BLOCKING_SEVERITIES == frozenset({"Critical", "Major"})`.

### `src/mergecraft/findings/causality.py` (new)

| Symbol | Contract |
|--------|----------|
| `CausalityValidationError` | Raised when a blocking finding lacks causality (D2) |
| `validate_blocking_finding(finding)` | Require structured causality on `Critical`/`Major` |
| `apply_causality_policy(finding)` | Downgrade `introduced_by_pr="false"` findings below blocking |

### `src/mergecraft/analyzers/baseline_suppression.py` (new)

| Symbol | Contract |
|--------|----------|
| `should_run_baseline_suppression(diff_text, base_comparison)` | Skip when `baseComparison != "full"` or diff too small to pay for itself (D3) |
| `suppress_baseline_findings(...)` | Return `reported`, `suppressed`, and `audit_trail` (convention 7) |
| `SuppressionAuditEntry` | `fingerprint`, `decision`, `reason` per suppressed finding |

Wired through existing `AnalyzersSettings.base_comparison` / `baseComparison`.

### `src/mergecraft/classify/generated_files.py` (new)

| Symbol | Contract |
|--------|----------|
| `FileKind` | `SOURCE`, `GENERATED`, `MINIFIED`, `VENDORED` |
| `classify_path(path)` | Label path kind (D4) |
| `review_includes_path(path, *, change)` | Generated output stays in scope when generator config changed |

### `src/mergecraft/findings/precision_corpus.py` (new)

| Symbol | Contract |
|--------|----------|
| `PRE_DG1_BASELINE` | Frozen recall/precision on `origin/pre-0.0.1` @ `41fc2af` |
| `evaluate_dg1_precision_corpus()` | Run bench corpus through precision pipeline; return `ScoreReport`-like metrics |

Gate: `recall >= PRE_DG1_BASELINE.recall` and
`corpus_confirmed_precision > PRE_DG1_BASELINE.corpus_confirmed_precision`.

Pinned baseline constants in `test_precision_corpus.py`:
recall `1.0`, precision `0.64` (pre-DG1 structural replay corpus).

## Contract → coverage matrix

### Dedup — `tests/findings/test_dedup.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 1 | `test_two_lenses_reporting_one_defect_produce_one_finding` | integration | happy | Two lenses, one defect → one finding |
| 2 | `test_same_defect_different_wording_is_deduped` | unit | edge | Semantic paraphrase dedup |
| 3 | `test_distinct_defects_on_one_line_are_not_merged` | unit | false-merge guard | Different categories stay separate |

### Severity rubric — `tests/findings/test_severity_rubric.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 4 | `test_rubric_normalizes_model_assigned_severity` | unit | happy | Inflated severity normalized |
| 5 | `test_rubric_is_code_defined_not_model_defined` | unit | architecture | `SEVERITY_RUBRIC` is code data |
| 6 | `test_blocking_severities_unchanged` | regression | pin | `BLOCKING_SEVERITIES` unchanged |

### Causality — `tests/findings/test_causality.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 7 | `test_blocking_finding_requires_a_causality_field` | unit | error | D2 validation |
| 8 | `test_finding_not_introduced_by_the_diff_is_downgraded` | unit | edge | Pre-existing defect downgraded |

### Baseline suppression — `tests/analyzers/test_baseline_suppression.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 9 | `test_preexisting_analyzer_hit_is_suppressed` | integration | happy | D3 base hit suppressed |
| 10 | `test_new_hit_on_an_untouched_file_is_still_reported` | integration | edge | Novel hit on untouched file reported |
| 11 | `test_suppression_is_skipped_when_it_cannot_pay_for_itself` | unit | cost guard | Default `diff` skips base run |
| 12 | `test_suppression_decision_is_auditable` | integration | observability | Audit trail per suppression |

### Generated files — `tests/classify/test_generated_files.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 13 | `test_generated_minified_vendored_are_classified` | unit | happy | D4 path classification |
| 14 | `test_generator_config_change_is_still_reviewed` | functional | policy | Generator config change keeps scope |

### Precision corpus — `tests/findings/test_precision_corpus.py`

| # | Test | Layer | Scenario | Contract |
|---|------|-------|----------|----------|
| 15 | `test_precision_improves_without_recall_loss` | E2E gate | corpus | Precision up, recall flat |

## Imports of not-yet-existing symbols

All DG1.2 modules are imported **inside test bodies** so collection stays clean
before implementation lands.

## Status

DG1.1 RED suite authored 2026-08-18. Awaiting DG1.2 implementation and
xfail reconciliation.
