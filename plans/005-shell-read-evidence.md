# Plan 005: Record real shell read operands instead of command strings

- Status: TODO
- Issue: [#823](https://github.com/alexhawat/mergeCraft/issues/823)
- Priority: P2; effort: M; change risk: MED; confidence: HIGH.
- Planned against main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`, 2026-09-22.
- Dependencies: 001 (shared trajectory boundary). Finish before 012's labelled scoring baseline.

## Intent and current state

A successful `cat src/app.py` currently records `cat src/app.py` as the filename. The auditor compares it to src/app.py and reports a false Major unread-file finding.

`trajectory.py:375–386` walks arbitrary strings; :603–608 builds files_read. `trajectory_audit.py:167–181` correctly compares real filenames. The test at test_trajectory_read_coverage.py:61–73 checks only a boolean.

```python
if isinstance(node, str):
    if _looks_like_path(node):
        normalized = _normalize_git_object_spec(node)
        if normalized:
            found.append(normalized)
```

## Scope and conventions

Only these implementation paths, plus this plan's status and an appropriate changelog entry:
- `src/mergecraft/evidence/trajectory.py`
- `tests/evidence/test_trajectory_read_coverage.py`
- `tests/evidence/test_trajectory.py`

Follow record_tool_call/build_trajectory_record/audit_trajectory end-to-end tests. Real shell arguments use command; do not invent a separate path field to make the test pass.

Python 3.11+, uv, src layout, strict typing, loguru and existing camelCase configuration aliases apply. Read AGENTS.md, CONTRIBUTING.md and docs/REVIEW-DOCTRINE.md. Do not change trust-tier authority, approval policy or public schemas outside the listed scope. Do not write new material under evidence/. No generated file hand-edits.

## Start and verification commands

Start a clean branch `codex/005-shell-read-evidence` from updated main. This plan was written in a checkout on older pre-0.0.1: do not implement there blindly or carry the user's local config edit.

1. `git merge-base --is-ancestor be9993367386b03f982c795ceb1d80e4a0bfcf1d HEAD` must exit 0.
2. `git diff --stat be9993367386b03f982c795ceb1d80e4a0bfcf1d..HEAD -- src/mergecraft/evidence/trajectory.py tests/evidence/test_trajectory_read_coverage.py tests/evidence/test_trajectory.py`; compare changed files against the excerpts before proceeding.
3. If dependencies are absent, `make setup` in the implementation checkout only.
4. Focused gate: `make test MERGECRAFT_PYTEST_JOBS=0 PYTEST='uv run pytest -k "trajectory"'` → all selected tests pass. This Make override still collects the suite and selects by name.
5. Final gates: `make lint typecheck pyright`, then `make ci` → exit 0. Use `make coverage-gate` where coverage policy changes. Record actual results and skips.

## Implementation steps

### 1. Pin the behavior

Add failing cases using the actual shell schema (`command`, optional `working_directory`) and the dedicated git tool schema (`command`, `args`, `repo`). A successful `cat src/app.py` must yield exactly `src/app.py` and no unread finding for it. Include a second changed file that was not read and must still produce exactly one finding. Also prove a failed command (`ok=False` or `outcome_ok=False`) contributes no path.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 2. Implement the bounded change

Add a bounded tool-aware extractor in the trajectory layer for successful calls only (`call.ok` and `outcome_ok is not False`). Accept documented explicit path fields by exact field name and simple invocations of the allowlisted read commands. Parse with `shlex`, command-specific positional/option-value rules, and fixed operand/string caps. Unknown options, newlines, control operators, substitutions, backticks, environment expansion, globs, and tildes make the shell command unknown; never execute, expand, or partly guess it. Patterns and option values for grep/rg are not paths. A supported command establishes read coverage only when it yields at least one validated repository path; an unknown call neither adds paths nor masks the unread result established by another valid call.

Resolve `working_directory` and operands lexically against the primary repository, store normalized repo-relative paths, and drop absolute/outside/traversal paths; the working directory itself is context, not evidence of a read. Handle the dedicated git tool independently, including supported global options and unambiguous `revision:path` objects, while excluding revision ranges and shell text that merely begins with `git`. Reuse existing git argument normalization where it is safe; do not build a second permissive parser.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 3. Verify the complete contract

Cover failed reads, grep without file operands, regex-only input, quoted paths, working directories, compound/dynamic syntax, traversal/outside paths, long/many operands, revision ranges, git global options, non-file arguments, and redaction regressions from 001. Assert exact `files_read` values and the resulting audit finding set. Keep `files_modified` strictly from the run diff and run findings advisory. Run final gates.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

## Completion criteria

- [ ] Only successful, unambiguous repository reads contribute exact paths; unknown/failed inputs cannot suppress a finding established by valid coverage.
- [ ] #796 regressions and 001 secret-absence assertions remain green.
- [ ] Focused and final gates pass; results and any environment limitation recorded.
- [ ] `git diff --check` exits 0 and `git diff --name-only` stays in scope.
- [ ] Update this status and plans/README.md; use a Conventional Commit subject ≤72 characters. Do not use --no-verify.

## Stop conditions and maintenance

Stop if precise evidence requires executing shell commands or interpreting arbitrary scripts. Record unknown coverage instead; do not build a shell interpreter. Also stop and reconcile if source excerpts have drifted, a prerequisite is incomplete, two reasonable verification attempts fail, or an out-of-scope change is necessary. Never label skipped checks as passed.

New shell tools should supply structured read metadata when possible. Keep observation confidence separate from intent classification.
