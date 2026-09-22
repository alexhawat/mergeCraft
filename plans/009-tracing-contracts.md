# Plan 009: Reconcile tracing contracts and root the complete review lifecycle

- Status: Integrated (`327a6d2c`); independent focused and real collector checks passed; final CI pending
- Issue: [#798](https://github.com/alexhawat/mergeCraft/issues/798)
- Priority: P2; effort: M–L; change risk: MED; confidence: HIGH.
- Planned against main `be9993367386b03f982c795ceb1d80e4a0bfcf1d`, 2026-09-22.
- Dependencies: None; coordinate main.py changes with 003.

## Intent and current state

The deleted xfails are not eight missing product features. Analyzer parent/child spans, lifecycle phase point spans, prep/publish spans, agent-attempt and llm-call spans, per-attempt usage stamping, and OTel trace/span/parent-ID forwarding already exist. The remaining product gap is ownership and propagation of one run root spanning the real Action/offline review lifecycle, including direct/chain dispatch, tool work, and publication. Several useful assertions also need valid replacement fixtures.

`analyzers/pipeline.py:281–390` emits parent/child spans. `utils/agent_resolve.py:974–979` intentionally visits configured entries; :1026 owns the root only inside the chain; :1120–1134 stamps llm.call. `main.py:560` publishes outside it, and :1504–1515 has a direct path. `tracing/exporters.py:668–685` already forwards real trace identity.

```python
with tracer.start_span("mergecraft.analyzers.pipeline", ...) as parent_span:
    ...
    with tracer.start_span("analyzer.run", parent_span_id=parent_id, ...):
        ...
# run_with_model_chain owns mergecraft.run; publication is later.
```

## Scope and conventions

Only these implementation paths, plus this plan's status and an appropriate changelog entry:
- `src/mergecraft/main.py`
- `src/mergecraft/offline_review.py`
- `src/mergecraft/utils/agent_resolve.py`
- `src/mergecraft/tracing/tracer.py`
- `src/mergecraft/mcp/context.py`
- `src/mergecraft/mcp/rpc.py`
- `tests/tracing/instrumentation/conftest.py`
- `tests/tracing/instrumentation/test_span_tree.py`
- `tests/tracing/instrumentation/test_agent_attempt.py`
- `tests/tracing/instrumentation/test_usage_entries.py`
- `tests/tracing/instrumentation/test_analyzer_run.py` (add a replacement test file)
- `tests/tracing/exporters/test_otlp_sink_parent_context.py`
- `tests/tracing/test_trace_id_bridge.py`
- `docs/TRACING.md`
- `llms-full.txt` (generated from the documentation source)

Use captured_sink in tests/tracing/instrumentation/conftest.py and trace_event_payload where its exporters/conftest.py is actually in fixture scope. Preserve disabled-tracing NullSink and nonthrowing exporters. Consult the repository Logfire instrumentation skill when implementing.

Python 3.11+, uv, src layout, strict typing, loguru and existing camelCase configuration aliases apply. Read AGENTS.md, CONTRIBUTING.md and docs/REVIEW-DOCTRINE.md. Do not change trust-tier authority, approval policy or public schemas outside the listed scope. Do not write new material under evidence/. No generated file hand-edits.

## Start and verification commands

Start a clean branch `codex/009-tracing-contracts` from updated main. This plan was written in a checkout on older pre-0.0.1: do not implement there blindly or carry the user's local config edit.

1. `git merge-base --is-ancestor be9993367386b03f982c795ceb1d80e4a0bfcf1d HEAD` must exit 0.
2. `git diff --stat be9993367386b03f982c795ceb1d80e4a0bfcf1d..HEAD -- src/mergecraft/main.py src/mergecraft/offline_review.py src/mergecraft/utils/agent_resolve.py src/mergecraft/tracing/tracer.py src/mergecraft/mcp/context.py src/mergecraft/mcp/rpc.py tests/tracing/instrumentation/conftest.py tests/tracing/instrumentation/test_span_tree.py tests/tracing/instrumentation/test_agent_attempt.py tests/tracing/instrumentation/test_usage_entries.py tests/tracing/instrumentation/test_analyzer_run.py tests/tracing/exporters/test_otlp_sink_parent_context.py tests/tracing/test_trace_id_bridge.py docs/TRACING.md llms-full.txt`; compare changed files against the excerpts before proceeding.
3. If dependencies are absent, `make setup` in the implementation checkout only.
4. Focused gate: `make test MERGECRAFT_PYTEST_JOBS=0 PYTEST='uv run pytest -k "tracing"'` → all selected tests pass. This Make override still collects the suite and selects by name.
5. Final gates: `make lint typecheck pyright`, then `make ci` → exit 0. Use `make coverage-gate` where coverage policy changes. Record actual results and skips.

## Implementation steps

### 1. Pin the behavior

Replace the issue's eight literal xfail requests with a contract matrix that marks each behavior as already instrumented, stale test, or missing root ownership. Add analyzer tests using the current synchronous `run_adapter`/detect-enabled seams and real `Finding` factories. Assert real finding counts, zero results, and adapter exceptions. `analyzer.exit_code` is the adapter invocation status (0 completed, 1 failed/unavailable), not an analyzer subprocess exit code. Do not change `analyzers/pipeline.py` merely to recreate deleted fixture assumptions.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 2. Implement the bounded change

Retire the old runnable-index expectation: configured indices are intentional and `run_once` owns credential availability. Replace the incorrect three-attempt assertion with separate one-success, retryable-failure-then-success, and nonretryable-failure cases using `AgentResult.metadata`; two successful chain entries must not both execute. Replace the no-op usage test with exact per-attempt usage assertions; `usage_entries` has a step-summary consumer and must not be deleted. Update the stale OTel parent-context test to assert the existing exporter behavior and keep the existing `tests/tracing/test_trace_id_bridge.py`; no exporter product change or nonexistent second bridge test is needed.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 3. Implement the bounded change

Move lifecycle root ownership to the first Action/offline orchestration seam where resolved tracing settings are available and keep it open through review publication. Change `run_with_model_chain` to reuse an active run and create a root only for standalone callers. Carry immutable trace/root-parent identity in `ToolContext` and use it as the fallback parent in the MCP RPC task so server task scheduling does not rely on ambient `ContextVar` inheritance; do not use mutable process-global parent state. Preserve the existing prep, analyzer, attempt, llm, tool, phase, and publication emitters rather than creating replacement phase spans.

Exercise real orchestration paths with fakes: one Action route and one offline route, direct and fallback dispatch where applicable, publication failure, and disabled tracing. Assert exactly one `mergecraft.run`, every emitted non-root parent resolves within the captured tree, and only phases actually reached are present. Include a real MCP tool span to prove the explicit boundary propagation.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

### 4. Verify the complete contract

Run the normal focused gate first. In the implementation checkout, install optional dependencies with `make setup MERGECRAFT_UV_EXTRAS=tracing`, rerun the focused gate, then run `make test-otlp-collector` only in a supported Docker/collector environment. After editing `docs/TRACING.md`, run `make llms`, require only the expected generated `llms-full.txt` change, and run `make docs-check`. Run final gates and record unavailable optional integration checks honestly.

Verification: run the focused gate above. A new regression should fail for the specified behavior before implementation; after the fix all selected cases must pass. Do not accept an import/fixture error as the expected failure.

## Completion criteria

- [ ] Full real lifecycle has one root and all emitted non-root parents resolve, without manufacturing phases that did not occur.
- [ ] Existing analyzer/phase/prep/publish/attempt/llm/exporter instrumentation is protected by valid behavioral tests; obsolete skip/two-success contracts are retired.
- [ ] Trace identity survives the exporter boundary and disabled tracing stays a no-op.
- [ ] `make llms` regenerates `llms-full.txt`, and `make docs-check` passes with no unrelated generated drift.
- [ ] Focused and final gates pass; results and any environment limitation recorded.
- [ ] `git diff --check` exits 0 and `git diff --name-only` stays in scope.
- [ ] Update this status and plans/README.md; use a Conventional Commit subject ≤72 characters. Do not use --no-verify.

## Stop conditions and maintenance

Stop if a proposed span contract requires inventing events or changing fallback dispatch semantics. Do not restore broken fixture constructors or xfail the real regression. Also stop and reconcile if source excerpts have drifted, a prerequisite is incomplete, two reasonable verification attempts fail, or an out-of-scope change is necessary. Never label skipped checks as passed.

Span lifecycle ownership must remain above all reached review phases. Any boundary that does not inherit Python task context uses explicit trace identity; do not assume ambient `ContextVar` inheritance.

## Implemented contract reconciliation

| Original concern | Verified contract and disposition |
|---|---|
| Analyzer spans | Existing synchronous adapter instrumentation is preserved; findings, empty results and failures have behavioral tests. |
| Attempt indices and stop behavior | Indices describe configured models. Execution stops after success/nonretryable failure; remaining configured entries may emit `not_visited` spans. Span count is not executed-attempt count. No fallback policy was changed. |
| Per-attempt usage | Existing usage stamping is retained and exact values are asserted for the attempts that execute. |
| Complete lifecycle root | Action and offline orchestration now own one context-local root through publication; standalone chains create a root only when necessary. |
| Detached MCP tasks | An immutable explicit trace parent bridges server task scheduling; all recorded child parents resolve within the run. |
| Exported trace identity | Existing OTel identity forwarding is retained and independently tested through the real Docker collector. |
| Setup timeout | Moving root ownership does not expand the existing setup budget: setup is bounded and remaining credential time is reduced by elapsed setup time. |

Independent verification is recorded in [IMPLEMENTATION.md](IMPLEMENTATION.md). The final full gate remains pending; no skipped check is counted as passed.
