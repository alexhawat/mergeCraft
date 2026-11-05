# Coverage floor baseline

This baseline is attributable to the complete coverage measurement on the
integrated tree at `157f57a3d49a662433f6a5f678025d6ec45a52e4` (2026-09-22).
It replaces the pre-rebaseline floors in
`scripts/check_coverage_floors.py`. The measurement exited successfully with
10,025 passed, 16 skipped, 22 deselected, 4 expected failures and 17 warnings.

## Provenance

| Field | Value |
| --- | --- |
| Full source HEAD | `157f57a3d49a662433f6a5f678025d6ec45a52e4` |
| Coverage JSON SHA-256 | `1f54f759d1f77d8f318268e6ee4afe46227703e19b77998a4ffcb47cb2cb5b2c` |
| Raw coverage data SHA-256 | `ebec0d5fc7b1f63df3978b3f97364c57062b17a1aeca8826beb95e29ccccef8d` |
| Python | `3.14.6` |
| Platform | `macOS-15.7.3-arm64-arm-64bit-Mach-O` |
| coverage | `7.15.2` |
| pytest / pytest-cov | `9.1.1` / `7.1.0` |
| pytest-split / pytest-xdist | `0.11.0` / `3.8.0` |
| logfire | `5.1.0` |
| Seed | `424242` |
| Selection | `not integration` |
| Measurement exit | `0` |

The retained artifacts are `measured-coverage.json`, `measured-coverage.raw`,
`measurement-head.txt`, `measurement-exit.txt` and `runtime.json` in the
validation bundle for this run. The JSON report contains 538 files.

This measurement predates the pending test-isolation and analyzer-cache fixes
on the integration branch. The final CI run must verify the critical counts on
the exact final tree; this report is attributable to the source HEAD recorded
above and is not a claim about that later tree.

The native global coverage.py combined metric is
`(47030 + 13477) / (54506 + 18148) = 83.2810306384%`. Its statement counts
are 47,030 covered of 54,506 and its branch counts are 13,477 covered of
18,148. The native global `fail_under = 82` remains unchanged.

Module floors use true line and branch counts with a two point buffer. Prefix
line floors use measured line coverage minus two points; prefix branch floors
use measured branch coverage minus three points. Values are rounded to one
decimal place after applying the buffer. The `combined` columns are recorded
for provenance and are coverage.py's combined metric; they do not substitute
for the line or branch floor inputs.

## Measured critical paths and resulting floors

| Module | Counts (covered / total) | Measured line | Measured branch | Combined | Floor line | Floor branch |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `utils/token.py` | lines 178 / 186; branches 41 / 44 | 95.6989% | 93.1818% | 95.2174% | 93.7% | 91.2% |
| `utils/git_setup.py` | lines 245 / 257; branches 55 / 62 | 95.3307% | 88.7097% | 94.0439% | 93.3% | 86.7% |
| `main.py` | lines 738 / 819; branches 124 / 156 | 90.1099% | 79.4872% | 88.4103% | 88.1% | 77.5% |

| Prefix | Files | Counts (covered / total) | Measured line | Measured branch | Combined | Floor line | Floor branch |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| `mcp/` | 46 | lines 4,215 / 5,000; branches 1,075 / 1,518 | 84.3000% | 70.8169% | 81.1599% | 82.3% | 67.8% |
| `action/` | 2 | lines 194 / 210; branches 92 / 106 | 92.3810% | 86.7925% | 90.5063% | 90.4% | 83.8% |
| `security/` | 4 | lines 499 / 564; branches 135 / 172 | 88.4752% | 78.4884% | 86.1413% | 86.5% | 75.5% |
| `analyzers/` | 74 | lines 6,585 / 7,679; branches 2,125 / 2,898 | 85.7534% | 73.3264% | 82.3485% | 83.8% | 70.3% |
| `agents/` | 30 | lines 3,531 / 4,022; branches 1,028 / 1,324 | 87.7921% | 77.6435% | 85.2787% | 85.8% | 74.6% |
| `review/` | 19 | lines 1,129 / 1,281; branches 331 / 464 | 88.1343% | 71.3362% | 83.6676% | 86.1% | 68.3% |

## Changes from the previous floors

Every value below is the resulting floor minus the previous declared floor.
Zero deltas are retained to show that no unchanged floor was silently omitted.

| Scope | Previous line / branch | New line / branch | Delta line / branch |
| --- | ---: | ---: | ---: |
| `utils/token.py` | 90.7% / 86.2% | 93.7% / 91.2% | **+3.0pp / +5.0pp** |
| `utils/git_setup.py` | 92.0% / 86.7% | 93.3% / 86.7% | **+1.3pp / +0.0pp** |
| `main.py` | 86.1% / 76.3% | 88.1% / 77.5% | **+2.0pp / +1.2pp** |
| `mcp/` | 82.1% / 67.5% | 82.3% / 67.8% | **+0.2pp / +0.3pp** |
| `action/` | 90.4% / 83.8% | 90.4% / 83.8% | **+0.0pp / +0.0pp** |
| `security/` | 86.5% / 75.5% | 86.5% / 75.5% | **+0.0pp / +0.0pp** |
| `analyzers/` | 83.3% / 70.2% | 83.8% / 70.3% | **+0.5pp / +0.1pp** |
| `agents/` | 85.8% / 74.6% | 85.8% / 74.6% | **+0.0pp / +0.0pp** |
| `review/` | 85.9% / 67.9% | 86.1% / 68.3% | **+0.2pp / +0.4pp** |

The increases and unchanged values follow directly from the complete report
and the stated buffers. No floor was lowered to make a gate pass. PR #817's
automatic closing reference is #771 only; #797 remains a separate manual
disposition after the corrected `utils/token.py` floors and its behavioral
tests are reviewed together.
