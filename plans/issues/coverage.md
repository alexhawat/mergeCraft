## Verified defect
Audited main `be9993367386b03f982c795ceb1d80e4a0bfcf1d` and PR #817 head `d72b4e77dd47d7937527837b3f653a858804cf4e` on 2026-09-22.

[`check_coverage_floors.py:116`](https://github.com/alexhawat/mergeCraft/blob/be9993367386b03f982c795ceb1d80e4a0bfcf1d/scripts/check_coverage_floors.py#L116) treats coverage JSON `summary.percent_covered` as line coverage. Under branch coverage (enabled by Make), coverage.py calculates that field as `(covered_lines + covered_branches)/(num_statements + num_branches)`. Prefix floors in the same script correctly use line counts, so module and prefix floors enforce different metrics.

## Reproduced false pass
An unchanged script run against a synthetic coverage-format report, with all unrelated required entries at 100%:
```
utils/git_setup.py: covered_lines=90, num_statements=100,
                   covered_branches=100, num_branches=100,
                   percent_covered=95
actual line coverage=90%
current line floor=91.5%; PR #817 floor=92.0%
actual script result: exit 0, coverage floor check OK
expected: exit 1, git_setup line coverage below floor
```
Coverage.py's installed JSON reporter and Numbers.pc_covered implementation were inspected to confirm the schema semantics. Conversely, weaker branch coverage can fail the mislabeled line check even if both actual line and branch floors pass.

#817 changes thresholds and baseline metadata but retains this algorithm; its measurement table labels combined module/global numbers as line percentages.

## Acceptance
- Calculate module line percentage from covered_lines/num_statements, using the prefix path's zero-statement convention.
- Preserve the native global fail_under=82 combined-coverage policy unless separately and explicitly changing policy; fix misleading labels rather than weakening the global gate.
- Test false-pass and false-fail examples, branchless modules, missing modules/prefixes, and below-threshold failure.
- Remeasure actual module line and branch floors from one complete report; preserve baseline SHA, Python/version/seed and report provenance. Do not silently reuse a combined threshold as a line threshold.
- Coordinate with #817/#771/#797; fix semantics before relying on the rebaseline as proof of line protection. #785 sharding remains separate.

Priority P1; effort S/M; fix risk medium. Implementation plan: `plans/006-coverage-metric-contract.md`.
