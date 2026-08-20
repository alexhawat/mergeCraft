# Open issues sweep 2026-08-20b — tracing batches test plan (#372–#375)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20b-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-2026-08-20b` @ `wave/open-issues-sweep-2026-08-20b`

## Batch BA (#372)

Authoring wave: **W1** (Batch BA RED) · Implementation: **W2** (#372 sink dedupe)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W2** | `test_logfire_and_otel_shared_endpoint_exports_one_span_per_event` | `green after W2: #372 OTLP sink dedupe by endpoint` | pending — **FAIL** (2 spans today) |
| **W2** | `test_otlp_sink_list_does_not_grow_across_writes` | `green after W2: #372 OTLP sink dedupe by endpoint` | pending — **FAIL** (2 OTLPSinks today) |

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| BA372a | logfire + otel (same endpoint + headers) → one OTLP span per ``TraceEvent`` | integration | happy — one ``llm.call`` write | `tests/tracing/exporters/test_otlp_sink_endpoint_dedupe.py::test_logfire_and_otel_shared_endpoint_exports_one_span_per_event` |
| BA372b | Resolved OTLP sink list is deduped and stable across N writes | integration | edge — N=5 writes, one process | `test_otlp_sink_list_does_not_grow_across_writes` |
| BA372c | Per-write export count stays at one after dedupe | integration | regression — no N× growth per turn | same (per-write span count assertion) |

## W1 notes

- **D11:** Dedupe key is resolved endpoint **and** headers. The RED fixture aligns otel ``headers`` with the logfire bearer token so both sinks target the same destination.
- **#293 boundary:** Processor singleton tests live in ``test_otlp_singleton_processor.py``. Batch BA pins duplicate **sinks** in ``MultiSink``, not duplicate ``BatchSpanProcessor`` stacking.
- **Recording seam:** Spans are counted by parsing every ``captured_payload()`` JSON-array chunk (one chunk per exported span).

## Acceptance (W1)

- New tests collect with zero import errors
- ``make lint`` + ``make typecheck`` clean on touched paths
- Both Batch BA tests xfail (**FAIL**, not XPASS)
- No ``src/`` edits; D6 honoured

---

## Batch BB (#373)

Authoring wave: **W3** (Batch BB RED) · Implementation: **W4** (#373 explicit start/end)

### xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W4** | `test_exported_span_duration_matches_trace_event_wall_time[1]` | `green after W4: #373 OTLP span start_time/end_time from TraceEvent` | pending — **FAIL** (~15µs today) |
| **W4** | `test_exported_span_duration_matches_trace_event_wall_time[3]` | same | pending — **FAIL** (~15µs today) |

### Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| BB373a | ``ts_end_ns - ts_start_ns`` wall time → OTel ``end_time - start_time`` | integration | happy — 1s and 3s ``llm.call`` | `tests/tracing/exporters/test_otlp_sink_span_duration.py::test_exported_span_duration_matches_trace_event_wall_time` |
| BB373b | Exported span is not zero-width (~15µs export artifact) | integration | regression — ceiling 100µs | same (first assertion) |
| BB373c | ``duration_ms`` attribute unchanged (D9) | unit | out of W3 scope — W4 keeps attribute | — |

### W3 notes

- **D9/D10:** W4 must pass ``start_time=event.ts_start_ns`` and ``end_time=event.ts_end_ns``; epoch nanoseconds assumed (W0 confirmed).
- **Recording seam:** Duration is read from ``start_time`` / ``end_time`` on ``_RecordingSpanProcessor`` payloads, not from ``duration_ms`` attrs alone.
- **Shared surface:** Batch BC (#374) also touches ``OTLPSink.write`` but gets its own RED file in W5.

### Acceptance (W3)

- New tests collect with zero import errors
- ``make lint`` + ``make typecheck`` clean on touched paths
- Both parametrized Batch BB cases xfail (**FAIL**, not XPASS)
- No ``src/`` edits; D6 honoured
