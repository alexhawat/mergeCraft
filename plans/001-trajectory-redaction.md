# Plan 001: Close the trajectory redaction bypass

- Status: Integrated; independent focused verification passed; final combined-tree CI pending
- Issue: [#819](https://github.com/alexhawat/mergeCraft/issues/819)
- Priority: P1; effort: S–M; change risk: MED; confidence: HIGH.
- Planned against main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`, 2026-09-22.
- Dependencies: None; land before 005.

## Intent and current state

Raw tool arguments bypass command redaction through extracted path strings. Synthetic secret text survives trajectory serialization and can reach evidence artifacts. Remove the second persistence route without obscuring useful path evidence.

`trajectory.py:509–521` redacts command but stores `paths=_paths_in(arguments)`. `_paths_in:375–386` accepts whole strings. `run_packet.py:397` embeds `trajectory.model_dump(mode="json")`; `emit.py:36–37` serializes unchanged.

```text
command=_truncate(redact_secrets(command_raw), _MAX_COMMAND_CHARS) if command_raw else None,
paths=_paths_in(arguments),
```

## Scope and conventions

Only these implementation paths, plus this plan's status and an appropriate changelog entry:
- `src/mergecraft/evidence/trajectory.py`
- `tests/evidence/test_trajectory.py`
- `tests/evidence/test_trajectory_read_coverage.py`
- `tests/evidence/test_packet_round_trip.py`

Use the existing `mergecraft.analyzers.redact.redact_secrets`; match the real ToolState fixture in tests/evidence/test_trajectory_read_coverage.py. Do not add a competing credential regex.

Python 3.11+, uv, src layout, strict typing, loguru and existing camelCase configuration aliases apply. Read AGENTS.md, CONTRIBUTING.md and docs/REVIEW-DOCTRINE.md. Do not change trust-tier authority, approval policy or public schemas outside the listed scope. Do not write new material under evidence/. No generated file hand-edits.

## Start and verification commands

Start a clean branch `codex/001-trajectory-redaction` from updated main. This plan was written in a checkout on older pre-0.0.1: do not implement there blindly or carry the user's local config edit.

1. `git merge-base --is-ancestor be9993367386b03f982c795ceb1d80e4a0bfcf1d HEAD` must exit 0.
2. `git diff --stat be9993367386b03f982c795ceb1d80e4a0bfcf1d..HEAD -- src/mergecraft/evidence/trajectory.py tests/evidence/test_trajectory.py tests/evidence/test_trajectory_read_coverage.py tests/evidence/test_packet_round_trip.py`; compare changed files against the excerpts before proceeding.
3. If dependencies are absent, `make setup` in the implementation checkout only.
4. Focused gate: `make test MERGECRAFT_PYTEST_JOBS=0 PYTEST='uv run pytest -k "trajectory or packet_round_trip"'` → all selected tests pass. This Make override still collects the suite and selects by name.
5. Final gates: `make lint typecheck pyright`, then `make ci` → exit 0. Use `make coverage-gate` where coverage policy changes. Record actual results and skips.

## Implementation steps

### 1. Pin the behavior

Add failing regressions through `record_tool_call` → `build_trajectory_record` → final packet serialization. Use a fabricated credential-shaped canary that the existing `redact_secrets` recognizes, embedded in `grep <canary> src/app.py`, nested arguments, errors, and caller-supplied `ToolCallRecord` values. Cover both ToolState records and `external_trace.tool_calls`: the assembly currently duplicates external calls into the combined call list while retaining the nested external trace, so assert the plaintext canary is absent from the complete `model_dump(mode="json")`/packet JSON at both locations. Before the fix, show that command redaction succeeds while a retained path leaks the canary. Do not inspect a real credential.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 2. Implement the bounded change

Separate documented path fields from command/error/text fields. Redact before truncating, bound every retained string and path-list size, and never turn a redaction marker or whole command into a path. Apply the same copy-and-sanitize operation to direct records, ToolState records, and external records at the shared assembly boundary; do not mutate caller-owned models. Sanitize `command`, `error`, and `paths` on every retained copy. Keep uncertain operands out of read evidence. The richer command-operand parser belongs to 005.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 3. Verify the complete contract

Verify valid, bounded repo paths still reach read coverage and authoritative modified paths still come only from the run diff. Assert that sanitization cannot manufacture a path that suppresses a real unread-file finding. Verify the plaintext canary is absent from `ToolCallRecord.model_dump`, `files_read`, `commands_run`, `failures`, run-health evidence, the nested external trace, and final serialized packet. Run the selected suite and final gates.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

## Completion criteria

- [ ] The credential-shaped plaintext canary is absent from every persisted trajectory field and both copies of external calls in final packet JSON.
- [ ] Valid known path fields remain useful; run-diff authority and advisory-only scope are unchanged.
- [ ] Focused and final gates pass; results and any environment limitation recorded.
- [ ] `git diff --check` exits 0 and `git diff --name-only` stays in scope.
- [ ] Update this status and plans/README.md; use a Conventional Commit subject ≤72 characters. Do not use --no-verify.

## Stop conditions and maintenance

Stop if a required redactor is unavailable, or if fixing persistence requires granting tool access or changing artifact visibility. Do not inspect real secrets. Also stop and reconcile if source excerpts have drifted, a prerequisite is incomplete, two reasonable verification attempts fail, or an out-of-scope change is necessary. Never label skipped checks as passed.

Review every new trajectory ingestion source for the same pre-persistence sanitization contract. Coordinate shared trajectory.py changes with 005.
