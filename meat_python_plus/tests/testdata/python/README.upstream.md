# Python abridging goldens

These fixtures are unified diffs for the Python files changed by three real
upstream commits that exposed different abridging failures. They are not claimed
to include unrelated non-Python files from those commits. Each `.plan.json` is
the model-authored source-coordinate portion of the plan; the compiler merges
its deterministic mandatory import-removal plan before rendering. Golden plans
must not target compiler-owned import rows themselves. Each `.golden.diff` is
the exact machine-rendered reading diff.

- Django `526b1b414d8e215bf627b5722df12a09346dbf6b` (June 8, 2026), “Refs CVE-2026-48587 -- Added helper to properly split header values.” Protects the token-list contract and quoted-value caveat, stripping transformation, representative call-site behavior, distinctive whitespace/wildcard/separator stimuli, required setup, and outcomes.
- Flask `c17f379390731543eea33a570a47bd4ef76a54fa` (February 18, 2026), “request context tracks session access.” Protects the property contract, backing-session lifecycle, save-path bypass, public type narrowing, proxy effect, and accessed/modified/Vary outcomes while collapsing repeated backing-field churn and assertion batches.
- pytest `b4e846616cbb0ba74dc548f7066b09d820f5dc05` (July 22, 2026), “Apply warning filters to `pytest_configure` (#14760).” Protects symmetric evidence for the exact warning-filter move, plugin/lifecycle conditions, `filterwarnings` and hook-order stimulus, required pytester setup, and pass/no-warning outcomes.

The deterministic quality gates are absolute, so a snapshot cannot be made
more verbose merely by claiming that it still compresses something:

| fixture | raw changed | max changed | raw physical rows | max physical rows | raw bytes | max bytes |
|---|---:|---:|---:|---:|---:|---:|
| Django | 178 | 89 | 329 | 155 | 14,468 | 6,685 |
| Flask | 124 | 63 | 234 | 120 | 8,803 | 5,037 |
| pytest | 109 | 42 | 159 | 65 | 6,468 | 2,615 |
| **Corpus** | **411** | **194** | **722** | **340** | **29,739** | **14,337** |

When revising a plan:

- retain contracts, security/compatibility caveats, behavior-changing
  conditions, transformations, effects, distinctive stimuli, outcomes, and any
  setup required to understand or execute the retained test scenario;
- after one representative anchor, remove purely mechanical rename/call-site
  hunks; remove default context, changelog prose, repeated fixtures/cases, and
  duplicate assertion spellings that add no new outcome;
- fold repetitive interiors only when the fixed `...` preserves useful suite
  shape; never hide the owner, table/configuration referenced by surviving
  code, delimiter boundary, or lifecycle edge;
- leave import hiding to the compiler and preserve identical treatment for both
  sides of every detected exact move.

Regenerate snapshots only after reviewing the semantic assertions and budgets:

```sh
UPDATE_GOLDEN=1 go test ./meat -run TestPythonGoldenCommits
```

Do not raise a budget just to bless a larger snapshot; document the semantic
anchor that requires the extra rows first. These compiler goldens should only
be regenerated as part of deliberate corpus tuning, not routine rubric edits.

`TestPythonGoldenCommits` is the hard gate: it is hermetic and locks exact
snapshot bytes, semantic anchors, move behavior, and the absolute budgets above.
The opt-in `TestRubric_PythonGoldenCommits` is instead a costed, stochastic smoke
test of the configured model. It requires unconditional import absence, a small
set of stable semantic minima, and broad retention ceilings calibrated from
recorded and review runs; it deliberately does not demand the hand-authored
plan's exact folds, removals, or retention.
