# Plan 002: Derive enforced verdicts from final normalized findings

- Status: Integrated; independent focused verification passed; final combined-tree CI pending
- Issue: [#820](https://github.com/alexhawat/mergeCraft/issues/820)
- Priority: P1; effort: M; change risk: MED; confidence: HIGH.
- Planned against main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`, 2026-09-22.
- Dependencies: None; coordinate with 004 in the MCP publication area.

## Intent and current state

An approve request plus an inflated Major README typo becomes request_changes before normalization. The finding subsequently becomes Trivial, yet the persisted verdict causes GitHub REQUEST_CHANGES. Final findings and the review event must agree.

`terminal_submission.py:88–95` grades raw severities. `mcp/verdict.py:943–981` prepares the verdict before normalize_agent_findings_via_pipeline. `mcp/review.py:989–1006` chooses the GitHub event from that verdict.

```python
merged_raw, enforced_verdict = prepare_terminal_submission(...)
# later:
normalized_findings = normalize_agent_findings_via_pipeline(...)
submission_dict = {"verdict": validated.verdict, ...}
```

## Scope and conventions

Only these implementation paths, plus this plan's status and an appropriate changelog entry:
- `src/mergecraft/mcp/verdict.py`
- `src/mergecraft/review/terminal_submission.py`
- `src/mergecraft/findings/agent_adapter.py`
- `tests/review/test_terminal_submission.py`
- `tests/review/test_terminal_verdict_policy.py`
- `tests/review/test_terminal_verdict_harness.py`
- `tests/mcp/test_publication_body_integrity.py`

Reuse `agents/gates.py::blocking_findings` and existing normalization/adaptation helpers. The harness fixture is useful for policy replay, but it does not submit or publish through MCP; use the real `submit_review_verdict` tool path and a fake SCM for the end-to-end assertion.

Python 3.11+, uv, src layout, strict typing, loguru and existing camelCase configuration aliases apply. Read AGENTS.md, CONTRIBUTING.md and docs/REVIEW-DOCTRINE.md. Do not change trust-tier authority, approval policy or public schemas outside the listed scope. Do not write new material under evidence/. No generated file hand-edits.

## Start and verification commands

Start a clean branch `codex/002-normalized-terminal-verdict` from updated main. This plan was written in a checkout on older pre-0.0.1: do not implement there blindly or carry the user's local config edit.

1. `git merge-base --is-ancestor be9993367386b03f982c795ceb1d80e4a0bfcf1d HEAD` must exit 0.
2. `git diff --stat be9993367386b03f982c795ceb1d80e4a0bfcf1d..HEAD -- src/mergecraft/mcp/verdict.py src/mergecraft/review/terminal_submission.py src/mergecraft/findings/agent_adapter.py tests/review/test_terminal_submission.py tests/review/test_terminal_verdict_policy.py tests/review/test_terminal_verdict_harness.py tests/mcp/test_publication_body_integrity.py`; compare changed files against the excerpts before proceeding.
3. If dependencies are absent, `make setup` in the implementation checkout only.
4. Focused gate: `make test MERGECRAFT_PYTEST_JOBS=0 PYTEST='uv run pytest -k "terminal_submission or terminal_verdict or publication_body_integrity"'` → all selected tests pass. This Make override still collects the suite and selects by name.
5. Final gates: `make lint typecheck pyright`, then `make ci` → exit 0. Use `make coverage-gate` where coverage policy changes. Record actual results and skips.

## Implementation steps

### 1. Pin the behavior

Add a failing MCP-flow test: submit requested `approve` with path `README.md`, body `README spelling typo`, and raw severity Major. Exercise the real verdict tool and publication with a fake SCM. Require the normalizer's actual finalized severity, the stored terminal verdict derived from it, and the matching GitHub event; do not hard-code Trivial unless the current precision rubric produces it for this fixture. Add a genuine finalized blocker control that publishes REQUEST_CHANGES.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 2. Implement the bounded change

Preserve the caller's requested verdict separately. Merge/dedupe findings and provenance, adapt and normalize them, then derive automatic escalation from the finalized typed findings through the central blocker predicate. Combine that result with the original request: an explicit valid `request_changes` stays strict, while a requested `approve` is escalated only by finalized blockers. Keep `ValidationState` as the separate fail-closed authority for asserted/analyzer/verifier/static-check blockers; do not convert it into another severity calculation or bypass its approval rejection. If normalization removes every finding from an explicit `request_changes`, retain the existing `request_changes_without_findings` rejection instead of inventing an approval.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 3. Verify the complete contract

Exercise downgraded findings, normalization removing all rows, explicit request_changes, multi-reviewer duplicates, genuine blockers, failed static checks, conflicting submissions, and idempotent replay. Confirm one real submitted record and its publication event use the same finalized evidence and verdict. Run final gates.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

## Completion criteria

- [ ] An automatically escalated raw Major typo no longer publishes REQUEST_CHANGES after becoming Trivial.
- [ ] Genuine blockers, explicit valid requests, `ValidationState` gate failures, scope/trust checks and conflicting-submission rejection remain enforced.
- [ ] Focused and final gates pass; results and any environment limitation recorded.
- [ ] `git diff --check` exits 0 and `git diff --name-only` stays in scope.
- [ ] Update this status and plans/README.md; use a Conventional Commit subject ≤72 characters. Do not use --no-verify.

## Stop conditions and maintenance

Stop if preserving authoritative verifier findings requires changing their schema or dropping fail-closed validation; report the required design change. Also stop and reconcile if source excerpts have drifted, a prerequisite is incomplete, two reasonable verification attempts fail, or an out-of-scope change is necessary. Never label skipped checks as passed.

Any future precision transform must run before the verdict it informs. Compare structured approval and GitHub event in review tests.
