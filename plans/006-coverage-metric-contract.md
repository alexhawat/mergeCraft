# Plan 006: Enforce actual module line coverage and name combined coverage honestly

- Status: ATTRIBUTABLE REBASELINE RECORDED — focused checks pass; final CI on the integrated tree pending
- Issue: [#824](https://github.com/alexhawat/mergeCraft/issues/824)
- Priority: P1; effort: S–M; change risk: MED; confidence: HIGH.
- Planned against main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`, 2026-09-22.
- Dependencies: Coordinate with open PR #817 before accepting its baseline; implement before 008.

## Intent and current state

The critical-module line gate reads coverage.py's combined line+branch percentage. With branch coverage enabled, `summary.percent_covered` is `(covered_lines + covered_branches) / (num_statements + num_branches)`, not a line percentage. A module with 90% lines and 100% branches reports 95% combined and incorrectly passes a 91.5% or 92% line floor. The converse false failure is possible when true line coverage passes but weaker branch coverage pulls the combined value below the line floor. PR #817 changes thresholds but leaves this defect.

`scripts/check_coverage_floors.py:116` uses `summary.percent_covered`; `_aggregate_prefix:68–78` correctly uses `covered_lines/num_statements`. Branch instrumentation is enabled in Makefile:196. The global `[tool.coverage.report] fail_under = 82` is coverage.py's native combined metric and must retain that exact policy. The floors, ratchet and delta scripts currently label that global combined value as line coverage; correct the names and messages without changing the calculation or floor.

```python
line_pct = float(summary["percent_covered"])
# prefix path instead:
return _pct(covered, stmts), _pct(covered_b, branches), matched_any
```

PR #817 is open at audited head `d72b4e77dd47d7937527837b3f653a858804cf4e`. Its only automatic closing reference is #771. Its module “line” measurements came from the same combined field, so they are not valid line baselines until remeasured from counts. #797 remains a separate manual close after the final true `utils/token.py` line/branch floors are verified. Do not imply that #817 auto-closes it or that a numeric threshold alone proves behavioral completeness.

## Scope and conventions

Only these implementation paths, plus this plan's status and an appropriate changelog entry:
- `scripts/check_coverage_floors.py`
- `scripts/check_coverage_ratchet.py`
- `scripts/check_coverage_delta.py`
- `tests/ci/test_coverage_ratchet.py`
- `tests/ci/test_coverage_floors.py (new)`
- `tests/ci/test_coverage_inherited_drift_485.py`
- `docs/_standards/coding-standards.md`
- `CONTRIBUTING.md`
- `CHANGELOG.md`

Use the existing `_pct` zero-total convention and script subprocess tests. Keep the native combined global 82 threshold. The arithmetic fix itself must leave every numeric module/prefix floor unchanged. A later attributable rebaseline from the complete report may change a number only through the documented buffer formula and a recorded measurement rationale, never merely to make a gate pass. Prefix line calculations already have the right semantics, so do not rewrite them unnecessarily.

Python 3.11+, uv, src layout, strict typing, loguru and existing camelCase configuration aliases apply. Read AGENTS.md, CONTRIBUTING.md, `docs/_standards/coding-standards.md`, and `docs/REVIEW-DOCTRINE.md`. Do not change trust-tier authority, approval policy or public schemas outside the listed scope. Do not write new material under `evidence/`. No generated file hand-edits.

## Start and verification commands

Start a clean branch `codex/006-coverage-metric-contract` from updated main. Preserve the user's original checkout and its local config edit.

1. `git merge-base --is-ancestor be9993367386b03f982c795ceb1d80e4a0bfcf1d HEAD` must exit 0.
2. `git diff --stat be9993367386b03f982c795ceb1d80e4a0bfcf1d..HEAD -- scripts/check_coverage_floors.py scripts/check_coverage_ratchet.py scripts/check_coverage_delta.py tests/ci docs/_standards/coding-standards.md CONTRIBUTING.md CHANGELOG.md`; reconcile drift, especially PR #817, before editing.
3. If dependencies are absent, `make setup` in the implementation checkout only.
4. Focused gate: `make test MERGECRAFT_PYTEST_JOBS=0 PYTEST='uv run pytest -k "coverage_floors or coverage_ratchet or coverage_delta or coverage_inherited"'`. `make test` still supplies the repository marker selection and seed; the override adds only the focused name filter.
5. Static gates: `make lint typecheck pyright`.
6. After final thresholds are committed, run `make ci` once on the exact final tree. Do not add a redundant unchanged `make coverage-gate` run; `make ci` already contains it.

## Implementation steps

### 1. Pin the behavior

Add complete coverage-format fixtures that exercise the script entry point:

- 90/100 lines and 100/100 branches with `percent_covered=95` must fail the `utils/git_setup.py` line floor and name the actual 90% result.
- True line and branch percentages at their floors must not fail merely because the supplied combined percentage is lower.
- Branchless and zero-statement modules follow `_pct`'s existing 100% zero-total convention.
- Missing required modules and prefixes still fail closed.
- A global report whose native combined `totals.percent_covered` is below 82 still fails even if pure line coverage would pass, proving that the global policy was not converted or weakened.

Update ratchet/delta assertions so their output says combined coverage while their numeric decisions remain unchanged.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 2. Implement the bounded change

Compute module line percentages with `_pct(int(summary["covered_lines"]), int(summary["num_statements"]))`; continue computing branch coverage from branch counts. Retain native combined `fail_under` enforcement and label it accurately in all three scripts and relevant docs. Do not alter ratchet margin, delta attribution, or merge-base policy.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 3. Implement the bounded change

After deciding whether #817 is amended before merge or followed immediately by this correction, run one attributable `make coverage-measure` on the resulting integrated tree. The completed measurement is recorded in [COVERAGE-BASELINE.md](COVERAGE-BASELINE.md), including the source SHA, report hashes, Python and coverage versions, seed, selection and full counts. This target includes tests marked `coverage` because it selects `not integration`; do not compare it to `make test`, which excludes that marker.

Derive module line percentages from line counts and branch percentages from branch counts. Validate the already-count-based prefixes from the same report. Apply module measured-minus-2 and prefix line-minus-2/branch-minus-3. Preserve the numbers while fixing arithmetic; then, in the attributable rebaseline, explain every increase or decrease directly from the complete report and buffer convention. Never lower a floor simply to turn a failure green. Run the ratchet and floors scripts directly against the saved report instead of repeating the full suite. Update the baseline table with explicit line/branch/combined labels. Record that #817 closes only #771 automatically; close #797 manually only after the corrected token floors and existing behavioral tests are reviewed together.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 4. Verify the complete contract

Run the focused/static checks, synthetic failure controls, and one final `make ci`. Keep global combined `fail_under=82`; require every module/prefix floor change to match the recorded complete measurement and buffer formula rather than weakening a gate to obtain green. A green numeric gate is evidence that the declared thresholds hold; it is not proof that every critical behavior is tested.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

## Completion criteria

- [ ] Branch percentage cannot conceal a module line-floor failure.
- [x] All reported baseline columns have explicit line/branch/combined meaning and come from one attributable measurement.
- [x] Global native combined `fail_under` remains 82; arithmetic changes do not alter floors, and every later rebaseline change has measured/buffer provenance.
- [ ] #817 coordination records only #771 as auto-closing; #797's manual disposition is accurate.
- [ ] Focused and final gates pass; results and any environment limitation recorded.
- [x] `git diff --check` exits 0 and `git diff --name-only` stays in scope.
- [ ] Update this status and plans/README.md; use a Conventional Commit subject ≤72 characters. Do not use --no-verify.

## Stop conditions and maintenance

Stop if measurement cannot be reproduced, a proposed floor change lacks the complete measurement/buffer rationale, or #817 drift makes its provenance unusable. Report missing measurement or branch drift rather than inventing thresholds. Also stop and reconcile if source excerpts have drifted, a prerequisite is incomplete, two reasonable verification attempts fail, or an out-of-scope change is necessary. Never label skipped checks as passed.

Any JSON-report consumer must distinguish percent_covered from pure line coverage. Sharding in 008 must combine raw data before these calculations.
