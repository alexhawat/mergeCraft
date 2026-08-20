# Open issues sweep 2026-08-20b — Batch BA test plan (#372)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20b-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-2026-08-20b` @ `wave/open-issues-sweep-2026-08-20b`
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
