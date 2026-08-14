# T3 — one ``trace_id`` per run + OTel context bridge — test plan

Wave plan: `.ignorelocal/waves/issues-tracing-sevn-quality-wave-plan.md`
Worktree: `mergecraft-trq-t3-traceid` @ `wave/trq-t3-traceid`
Base: `origin/pre-0.0.1` @ `10049a3`

This doc is the per-test traceability table for T3.1 (the `role: test-author` wave).
The implementation (T3.2) is owned by `wave-runner`; once that lands, an
xfail-reconciliation pass removes the satisfied markers.

## xfail schedule

| Wave | Test files | Marker reason prefix | Tests xfailed |
|------|------------|----------------------|---------------|
| **T3.2** | `tests/tracing/test_trace_id_bridge.py` | `green after T3.2: …` | 1 |

All cross-wave markers use `strict=False` (repo `xfail_strict = true`).
The single xfail is `test_otel_sink_forwards_real_trace_id` — it pins both
the `OTLPSink.write` trace_id setter AND the `_RecordingSpanProcessor`
trace_id capture; both surface in T3.2 file 4. The other 10 tests turn
green the moment T3.2 adds `trace_id` to `Tracer`/`Span`/`TraceEvent`/
`NullTracer` and ships `attach_trace_context` in `otel_bridge.py`.

## Contract matrix — T3.1 (test 1–11)

| # | Test | File:line | xfail | T3.2 surface | Coverage |
|---|------|-----------|-------|--------------|----------|
| 1 | `test_trace_id_resolves_to_session_id_when_set` | `test_trace_id_bridge.py` | — | `tracer.py::resolve_trace_id` env precedence step 2 (`MERGECRAFT_TRACE_SESSION_ID`) | Unit: env precedence |
| 2 | `test_trace_id_falls_back_to_github_run_id` | `test_trace_id_bridge.py` | — | `tracer.py::resolve_trace_id` env precedence step 3 (`GITHUB_RUN_ID`) | Unit: env precedence |
| 3 | `test_trace_id_is_uuid4_when_no_env` | `test_trace_id_bridge.py` | — | `tracer.py::resolve_trace_id` uuid4 fallback | Unit: env precedence |
| 4 | `test_all_spans_in_one_run_share_trace_id` | `test_trace_id_bridge.py` | — | `tracer.py::Tracer.start_span` propagates `trace_id=self.trace_id` onto `Span` | Integration: span lifecycle |
| 5 | `test_two_separate_runs_get_different_trace_ids` | `test_trace_id_bridge.py` | — | `tracer.py::Tracer.__init__` resolves uuid4 when env unset | Unit: per-process distinctness |
| 6 | `test_attach_trace_context_makes_nested_otel_span_share_trace_id` | `test_trace_id_bridge.py` | — (RED via missing `otel_bridge` module) | `tracing/otel_bridge.py::attach_trace_context` body | Integration: OTel context bridge |
| 7 | `test_disabled_path_emits_no_trace_id` | `test_trace_id_bridge.py` | — | `tracer.py::NullTracer.trace_id = ""` | Unit: disabled path |
| 8 | `test_jsonl_sink_includes_trace_id` | `test_trace_id_bridge.py` | — | `event.py::TraceEvent.trace_id` field added | Integration: JSONL sink round-trip |
| 9 | `test_otel_sink_forwards_real_trace_id` | `test_trace_id_bridge.py` | **Yes** (`strict=False`) | `exporters.py::OTLPSink.write` OTel trace_id setter + `_RecordingSpanProcessor.on_end` `trace_id` capture | Integration: OTel span trace_id |
| 10 | `test_trace_id_field_added_to_trace_event_data_fixture` | `test_trace_id_bridge.py` | — | `tests/tracing/conftest.py::trace_event_data` fixture update + `TraceEvent.trace_id` | Unit: fixture round-trip |
| 11 | `test_existing_fixtures_remain_green` | `test_trace_id_bridge.py` | — | `TraceEvent.trace_id` field round-trips through every fixture that uses `trace_event_data` | Regression: fixture seam |

**Acceptance:** 11 collected; 10 fail (RED pending T3.2); 1 xfailed (test 9, strict=False).

## Cross-test dependencies

- **Test 6** depends on the **opentelemetry** package being installed. The
  worktree runs `uv sync --extra dev --extra tracing` to satisfy this. In
  environments without `[tracing]` the test surfaces as SKIPPED, not FAILED.
- **Test 9** depends on both opentelemetry (for `OTLPSink`) and the T3.2
  `_RecordingSpanProcessor` `trace_id` capture (the `_RecordingSpanProcessor`
  does not currently capture `trace_id` — T3.2 file 4 adds it).
- **Tests 10–11** depend on `tests/tracing/conftest.py::trace_event_data`
  having a `trace_id` field. The T3.1 fixture edit (committed in this wave)
  adds the field; the `TraceEvent.trace_id` field lands in T3.2 file 1.
- **Tests 1–5** depend on `Tracer(sink, session_id, run_id)` resolving
  `trace_id` from the env precedence (or uuid4 fallback) — T3.2 file 2.

## Known RED cross-effects

The `trace_event_data` conftest fixture edit also affects two existing tests
that depend on round-trip equality through the fixture. Both fail RED right
now and turn GREEN in T3.2:

- `tests/tracing/test_sinks.py::test_jsonl_sink_writes_rotating_daily_files`
- `tests/tracing/test_config.py::test_trace_event_shape`

These are the intended cross-wave RED behavior — `TraceEvent.trace_id`
exists post-T3.2, so the round-trip `event.model_dump() == trace_event_data`
holds.

## Verification

- **Collection:** `uv run pytest --collect-only -q tests/tracing/test_trace_id_bridge.py` → 11 collected, 0 errors.
- **RED pytest:** `uv run pytest tests/tracing/test_trace_id_bridge.py` → `10 failed, 1 xfailed`.
- **Lint:** `make lint` → clean.
- **Typecheck:** `make typecheck` → clean (mypy is targeted at `src/mergecraft`; the test file references forward-only attributes, which mypy flags only when run against `tests/` directly — out of scope for the repo gate).

## xfail-reconciliation

When T3.2 lands and `test_otel_sink_forwards_real_trace_id` turns GREEN, the
orchestrator dispatches `test-creator` again to remove the `@pytest.mark.xfail`
marker on test 9. The other 10 tests require no marker removal (they were
never xfailed).
