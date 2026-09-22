# Plan 004: Clear unresolved publication failure after a confirmed retry

- Status: TODO
- Issue: [#822](https://github.com/alexhawat/mergeCraft/issues/822)
- Priority: P2; effort: S; change risk: LOW–MED; confidence: HIGH.
- Planned against main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`, 2026-09-22.
- Dependencies: None; coordinate with 002.

## Intent and current state

A transient publish exception followed by a successful retry leaves terminal_publication_failed true. The review exists but final classification says it never published and stays inconclusive.

`mcp/review.py:1159–1168` sets the flag; :1169–1187 stores a successful receipt without clearing it. `main_outcome.py:125–127` treats the retained flag as unresolved failure.

```python
except Exception:
    ctx.tool_state.terminal_publication_failed = True
    raise
review_id = int(result["id"])
ctx.tool_state.review = ReviewRecord(...)
```

## Scope and conventions

Only these implementation paths, plus this plan's status and an appropriate changelog entry:
- `src/mergecraft/mcp/review.py`
- `src/mergecraft/mcp/tool_state.py`
- `tests/review/test_terminal_publication_outcome_619.py`
- `tests/mcp/test_publication_anchor_recovery.py`
- `tests/mcp/test_review.py`

Use the fake SCM/tool context in `tests/mcp/test_review.py` and the final-outcome tests in `tests/review/test_terminal_publication_outcome_619.py`. `main_outcome.py` and `evidence/shadow.py` already consume the final boolean correctly and require regression coverage, not implementation changes. Keep attempt history in existing tool-call/trajectory diagnostics rather than overloading the unresolved-state flag.

Python 3.11+, uv, src layout, strict typing, loguru and existing camelCase configuration aliases apply. Read AGENTS.md, CONTRIBUTING.md and docs/REVIEW-DOCTRINE.md. Do not change trust-tier authority, approval policy or public schemas outside the listed scope. Do not write new material under evidence/. No generated file hand-edits.

## Start and verification commands

Start a clean branch `codex/004-publication-retry-state` from updated main. This plan was written in a checkout on older pre-0.0.1: do not implement there blindly or carry the user's local config edit.

1. `git merge-base --is-ancestor be9993367386b03f982c795ceb1d80e4a0bfcf1d HEAD` must exit 0.
2. `git diff --stat be9993367386b03f982c795ceb1d80e4a0bfcf1d..HEAD -- src/mergecraft/mcp/review.py src/mergecraft/mcp/tool_state.py tests/review/test_terminal_publication_outcome_619.py tests/mcp/test_publication_anchor_recovery.py tests/mcp/test_review.py`; compare changed files against the excerpts before proceeding.
3. If dependencies are absent, `make setup` in the implementation checkout only.
4. Focused gate: `make test MERGECRAFT_PYTEST_JOBS=0 PYTEST='uv run pytest -k "terminal_publication_outcome or publication_anchor_recovery or test_review"'` → all selected tests pass, including the MCP review tests in scope. This Make override still collects the suite and selects by name.
5. Final gates: `make lint typecheck pyright`, then `make ci` → exit 0. Use `make coverage-gate` where coverage policy changes. Record actual results and skips.

## Implementation steps

### 1. Pin the behavior

Add a failure→success reproduction through the real `create_pull_request_review` tool and fake SCM. Tool execution converts exceptions to an error `ToolResult`, so assert `first.is_error` rather than expecting an exception; the second result must succeed, store the review record, leave the final flag false, and allow a passed classifier when no unrelated blocker exists.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 2. Implement the bounded change

After the pre-existing publication-scope and terminal-submission checks pass, parse the GitHub result and record `ReviewRecord` before clearing `terminal_publication_failed`. The receipt model contains only review identifiers and `reviewed_sha`; do not claim it independently binds PR or submission. Clear the stale flag on a matching idempotent replay as well, because `_existing_publication_response` has already matched the locally recorded review to the currently bound head. Preserve prior failure diagnostics in the tool-call trajectory.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 3. Verify the complete contract

Test fail→fail remains inconclusive; failure→success clears only after a parseable record is stored; success→matching replay creates no duplicate and clears stale state; and a wrong-head/scope request is rejected before clearing. Verify existing main/shadow classifiers against constructed final ToolState values without editing those consumers. Run final gates.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

## Completion criteria

- [ ] A recovered publication no longer reports never-published.
- [ ] No successful matching receipt means failure remains; repeated requests do not duplicate reviews.
- [ ] Focused and final gates pass; results and any environment limitation recorded.
- [ ] `git diff --check` exits 0 and `git diff --name-only` stays in scope.
- [ ] Update this status and plans/README.md; use a Conventional Commit subject ≤72 characters. Do not use --no-verify.

## Stop conditions and maintenance

Stop if the existing local scope checks and reviewed SHA cannot establish the current request's identity; do not add an unsupported PR/submission claim to `ReviewRecord` or clear from HTTP success or agent prose alone. Also stop and reconcile if source excerpts have drifted, a prerequisite is incomplete, two reasonable verification attempts fail, or an out-of-scope change is necessary. Never label skipped checks as passed.

Keep final status distinct from attempt history in future retry/backoff changes.
