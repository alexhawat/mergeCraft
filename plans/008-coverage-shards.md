# Plan 008: Measure isolated raw coverage shards and gate only a complete set

- Status: Integrated (`b2a899ee`); 33 independent focused tests passed; final whole-tree parity and CI pending
- Issue: [#785](https://github.com/alexhawat/mergeCraft/issues/785)
- Priority: P2; effort: M; change risk: MED; confidence: HIGH.
- Planned against main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`, 2026-09-22.
- Dependencies: 006, so aggregation preserves the corrected metric contract.

## Intent and current state

`coverage-measure` ignores the existing split and worker knobs and deletes shared root coverage databases. Passing split flags naively would make each group produce a partial JSON report and could let that partial report reach global/module floors. Concurrent groups could also erase or overwrite one another.

`Makefile:162–165` applies pytest-split and xdist only to `make test`; :193–202 runs one coverage invocation and immediately gates its JSON report. No coverage-combine target exists. `scripts/ci_resume.sh` deliberately runs `CI_STEPS` serially and checkpoints only a complete Make target. Preserve that contract: sharding may happen inside the single `coverage-gate` stage, but target ordering, stop-at-first-failure behavior and checkpoint granularity must remain unchanged.

```python
coverage-measure:
    rm -f coverage.json .coverage .coverage.*
    $(PYTEST) tests ... --cov=mergecraft --cov-branch --cov-report=json:coverage.json
```

## Scope and conventions

Only these implementation paths, plus this plan's status and an appropriate changelog entry:
- `Makefile`
- `scripts/coverage_shards.py` (new orchestrator, manifest validator and pytest collection recorder)
- `.gitignore` (ignore isolated `.coverage-shards/` runtime outputs)
- `tests/ci/test_coverage_shards.py` (new)
- `tests/ci/test_coverage_ratchet.py` (CI graph assertion only if needed)
- `CONTRIBUTING.md`
- `CHANGELOG.md`

Do not change `scripts/ci_resume.sh` unless a demonstrated incompatibility requires it. Use pytest-split's existing `least_duration` scheme, pytest-cov/coverage.py raw databases, and the exact current coverage selection `tests -m "not integration"`, including tests marked `coverage`. Keep every recurring entry point behind Make and preserve serial `ci-resume` stage semantics.

Python 3.11+, uv, src layout, strict typing, loguru and existing camelCase configuration aliases apply. Read AGENTS.md, CONTRIBUTING.md, `docs/_standards/coding-standards.md`, and `docs/REVIEW-DOCTRINE.md`. Do not change trust-tier authority, approval policy, coverage floors, or public schemas outside the listed scope. Do not write new material under `evidence/`. No generated file hand-edits.

## Command contract to implement

| Mode | Command shape | Required behavior |
|---|---|---|
| Complete unsharded measurement | `make coverage-measure` | Preserve today's one-run `coverage.json` behavior. |
| One isolated shard | `MERGECRAFT_TEST_SPLITS=2 MERGECRAFT_TEST_GROUP=1 make coverage-measure` | Run a strict subset, write a uniquely isolated raw database and manifest, print its artifact directory, and run no floors. |
| Combine an explicit collection | `MERGECRAFT_TEST_SPLITS=2 MERGECRAFT_COVERAGE_RUN_DIR=<dir> make coverage-combine-gate` | Require groups 1 and 2 exactly once, validate compatibility/completeness, combine raw data, emit one JSON report, then run both gates. |
| One resumable CI stage with internal shards | `MERGECRAFT_TEST_SPLITS=2 make coverage-gate` | Create one run directory, execute groups concurrently, combine and gate, and return one final status to `ci-resume`. |

`MERGECRAFT_TEST_SPLITS=N make coverage-measure` without a group is invalid. A group without a split count is invalid. `coverage-gate` with both a split count and one group must reject the partial gate and direct the caller to measurement plus combine. A standalone shard without an explicit run directory may allocate a unique directory, but must print it; internally orchestrated groups share one explicit run directory and use distinct group subdirectories.

## Start and verification commands

Start a clean branch `codex/008-coverage-shards` from updated main. Preserve the user's original checkout and its local config edit.

1. `git merge-base --is-ancestor be9993367386b03f982c795ceb1d80e4a0bfcf1d HEAD` must exit 0.
2. `git diff --stat be9993367386b03f982c795ceb1d80e4a0bfcf1d..HEAD -- Makefile scripts/coverage_shards.py tests/ci/test_coverage_shards.py tests/ci/test_coverage_ratchet.py CONTRIBUTING.md CHANGELOG.md`; reconcile drift before editing.
3. If dependencies are absent, `make setup` in the implementation checkout only.
4. Focused gate: `make test MERGECRAFT_PYTEST_JOBS=0 PYTEST='uv run pytest -k "coverage_shards or coverage_ratchet"'`.
5. Static gates: `make lint typecheck pyright`.
6. Whole-suite parity is an explicit two-measurement acceptance check. After it passes, run one final `make ci` on the exact final tree; do not repeat unchanged full coverage runs.

## Implementation steps

### 1. Pin the behavior

Add failing tests for positive integers `N`/`G`, `1 <= G <= N`, missing values, duplicate/missing/extra groups, and mismatched metadata. Exercise concurrent shard writers and assert that no shard deletes or replaces a sibling database. Assert a partial shard never invokes either coverage gate.

Pin the Make graph: `CI_STEPS` still contains one `coverage-gate` step in the same order, `make ci` still reaches it, and default no-split behavior remains complete and unsharded. In orchestrated split mode, simulate a child failure and require the enclosing gate to return non-zero without reporting a pass.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 2. Implement the bounded change

Make split measurements select the same tests and seed as the unsharded path, adding `--splits N --group G --splitting-algorithm least_duration` and the existing xdist setting when requested. Give every child a group-specific `COVERAGE_FILE` under the shared run directory and request raw data only. Do not write per-shard JSON, delete root/sibling `.coverage*`, or run floors.

Use `scripts/coverage_shards.py` as a pytest plugin/helper to record the node IDs selected by the actual shard after pytest-split has partitioned collection. Pass `--cov-fail-under=0` only to isolated shard measurements so pytest-cov does not apply the project-wide 82 floor to partial data; the complete combined gate remains the sole enforcement point for 82 and all critical floors. Atomically write a versioned manifest only after a successful run.

Include source HEAD plus a deterministic source fingerprint covering staged and unstaged changes and relevant untracked source/test/config inputs (or reject those untracked inputs); coverage-config hash; Python, coverage, pytest, pytest-cov and pytest-split versions; marker/root/seed/splitting/xdist settings; `N`/`G`; raw path/hash; and selected node IDs/hash. Failed or interrupted runs must not leave an acceptable manifest.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 3. Implement the bounded change

Add `coverage-combine-gate`. It first requires manifests for exactly `{1..N}` from one explicit run directory. Reject duplicate group identities, duplicate raw paths, missing data, source/config/version/selection mismatches, overlapping node IDs, and a node-ID union that differs from an unsharded collect-only run with the same selection and seed. Verify every raw-file hash for integrity, but do not require hashes to be unique: distinct test groups can legitimately execute identical covered code. Empty groups are allowed only when the complete eligible collection has fewer items than `N`; they still need a valid manifest.

Only after validation, combine raw databases with retention enabled, generate one `coverage.json`, and invoke the ratchet followed by the floors script. Any validation, combine, JSON, or gate failure returns non-zero. Do not infer completeness from file count alone.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 4. Verify the complete contract

Keep default `make coverage-gate` complete and unsharded. When a split count is set without a group, allocate one run directory, launch exactly groups `1..N` with bounded concurrent `make coverage-measure` subprocesses, preserve per-group logs, handle child failure safely, then call the combine-and-gate target. The outer target returns only after the complete gate succeeds or fails.

This leaves `ci-resume` serial: one coverage step runs after earlier steps, and `.ci-progress` records it only after all groups, validation, combine, JSON, ratchet and floors pass. Do not add groups to `CI_STEPS` or parallelize unrelated stages.

Test two-shard vs unsharded equivalence on a bounded deterministic fixture with real branch data, comparing totals, per-file data and decisions. Exercise rejection controls by altering one manifest field at a time. Then perform one complete unsharded and one complete two-shard measurement on the same source/config/seed and compare totals/decisions. Document focused diagnosis, manual shard collection, combined gating, and `MERGECRAFT_TEST_SPLITS=N make ci-resume`; final integration still needs one clean default `make ci`.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

## Completion criteria

- [ ] N=2/G=1 is a strict subset; incomplete or incompatible shard collections fail closed.
- [ ] Complete combined and unsharded fixture and whole-suite reports have equal line/branch totals and gate decisions.
- [ ] No shard can erase another's data or let a partial report pass the global gate.
- [ ] `CI_STEPS` and `ci-resume` remain serial; optional internal sharding is one atomic gate result.
- [ ] Focused and final gates pass; results and any environment limitation recorded.
- [ ] `git diff --check` exits 0 and `git diff --name-only` stays in scope.
- [ ] Update this status and plans/README.md; use a Conventional Commit subject ≤72 characters. Do not use --no-verify.

## Stop conditions and maintenance

Stop if actual executed node IDs cannot be recorded, their union cannot be compared with the complete eligible collection, or coverage.py cannot combine isolated raw databases without path/config drift. Do not weaken floors, accept manifests by count alone, or parallelize `ci-resume` stages as a workaround. Also stop and reconcile if source excerpts have drifted, a prerequisite is incomplete, two reasonable verification attempts fail, or an out-of-scope change is necessary. Never label skipped checks as passed.

Refresh the manifest schema deliberately when collection inputs or tool versions change. Cleanup may remove only the exact completed run directory it created, never a broad `.coverage.*` glob shared with another run.

Implementation reconciliation: snapshot compatibility metadata before the test process and reject changed inputs afterward. Include test-selection/configuration and fixture inputs in the dirty fingerprint. Under xdist, record actual post-filter worker collections on the controller and write one node-ID receipt only after successful completion. Combine only the validated raw files, never all files found in their directories. The default serial gate must propagate failures from measurement and each subsequent policy check.
