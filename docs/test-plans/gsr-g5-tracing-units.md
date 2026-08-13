# Tracing units + span-count cap — test plan (G5.1 RED)

Wave plan: `.ignorelocal/waves/issues-showcase-readiness-wave-plan.md` (PR **G5**)
Worktree: `mergecraft-gsr-g5-tracing-units` @ `wave/gsr-g5-tracing-units`

G-F10: `tests/tracing/` had 11 test modules exercising `tracer.py` / `exporters.py`
only transitively; none named `test_tracer.py` / `test_exporters.py` targeted
their public API directly, and no span-count cap existed at all. G5.1 adds
both new modules; G5.2 (a separate `wave-plan-executor` pass) implements the
cap.

## xfail schedule

| Wave | Test files | Marker reason |
|------|------------|----------------|
| **G5.2** | `tests/tracing/test_tracer.py::test_span_count_cap_stops_emission_at_limit`, `tests/tracing/test_tracer.py::test_span_cap_logs_once_and_does_not_raise` | `green after G5.2: span-count cap` |

Both markers use `strict=False` — an `XPASS` once G5.2 lands `MAX_SPANS_PER_RUN`
must not fail the suite. The reconciliation pass (test-creator, re-dispatched
after G5.2) removes both markers once the cap is real.

## Acceptance (per plan)

12 collected; 10 green today (characterising existing behaviour); 2 xfail
pending G5.2. None of the 10 require the optional `[tracing]` extra — see
"OTLP tests use a fake tracer" below — so this holds under the default
`make setup` (`--extra dev` only) with no skip risk:

```
$ uv run pytest -v tests/tracing/test_tracer.py tests/tracing/test_exporters.py
...
10 passed, 2 xfailed in 0.22s
```

Also verified: `make lint` and `make typecheck` clean; the full
`tests/tracing/` suite (193 passed, 12 xfailed, 0 failed) under the fixed
seed `make test` uses (`MERGECRAFT_PYTEST_RANDOM_SEED` default `424242`).

## Contract matrix

### `tests/tracing/test_tracer.py`

| Contract | Layer | Scenario class | Test |
|---|---|---|---|
| A nested span inherits the owning tracer's `session_id` / `trace_id` | Unit | Happy path | `test_start_span_propagates_session_and_trace_id` |
| Three nested spans form a strict parent chain (`parent_span_id` at each level) | Unit | Happy path | `test_nested_spans_form_a_parent_chain` |
| A second `close()` after a `with`-block exit is a no-op — no duplicate emit, no `ts_end_ns` restamp, active-span stays reset | Unit | Edge case (idempotency) — extends the W6 `_closed` coverage in `test_span_lifecycle.py`, which only covers the manually-built (no `__enter__`) path | `test_span_close_is_idempotent` |
| A raising span body still pops the `_ACTIVE_SPAN` frame; the aborted span is still emitted with `status="error"`; a span opened afterward is a fresh root, not chained onto the dead frame | Unit | Error handling (the W5 `_ACTIVE_SPAN` leak class) | `test_active_span_contextvar_restores_on_exception` |
| `NullTracer.start_span(...)` never evaluates `attrs_source` (#56 D9) | Unit | Edge case (disabled path) | `test_null_tracer_is_a_true_noop` |
| Opening `MAX_SPANS_PER_RUN + 10` spans emits exactly `MAX_SPANS_PER_RUN` events | Unit | Edge case (unbounded growth guard) — **RED, xfail non-strict pending G5.2** | `test_span_count_cap_stops_emission_at_limit` |
| Hitting the cap logs exactly one `warning` and never raises (#56 D6: tracing never fails the run) | Unit | Error handling — **RED, xfail non-strict pending G5.2** | `test_span_cap_logs_once_and_does_not_raise` |

### `tests/tracing/test_exporters.py`

| Contract | Layer | Scenario class | Test |
|---|---|---|---|
| Every `TraceEvent` field survives a `JSONLFileSink` write + `read_jsonl_events` read | Integration (sink + reader) | Happy path | `test_jsonl_sink_round_trips_every_field` |
| The redaction boundary holds on write (`RedactingSink` before the byte reaches disk) **and** on read (`redact_attrs` re-applied at render time, mirroring `cli/tracing_cmd.py:240`'s `mergecraft traces show`) | Integration | Error handling / defense-in-depth (D7 double-redaction) | `test_jsonl_sink_redacts_on_write_and_on_read` |
| `event.attrs`' `gen_ai.*` semantic-convention keys land unchanged on the call `OTLPSink.write` makes into the OTel tracer (PR #137) | Unit (`OTLPSink.write`, fake tracer injected) | Happy path | `test_otlp_sink_maps_attrs_to_genai_conventions` |
| A raising inner sink is swallowed by `RedactingSink` and logged at `warning`, never reaching the caller (convention 6) | Unit | Error handling | `test_sink_write_failure_never_propagates` |
| An `attrs` value over `TRACE_ATTRS_JSON_MAX_BYTES` (`tracing/cap.py:18`) becomes `{"truncated": True}` end to end — `RedactingSink`'s `cap_event_attrs` then `OTLPSink.write`'s marker forwarding | Integration (`RedactingSink` + `OTLPSink`, fake tracer injected) | Edge case (boundary / oversized payload) | `test_attrs_over_cap_are_truncated_not_dropped` |

## Notes

- `MAX_SPANS_PER_RUN` is imported **inside** the two cap test bodies, not at
  module scope — importing it at module level would raise `ImportError` at
  collection time and break collection for the other 10 tests in the file.
  The lazy import is itself the RED assertion; pytest reports the resulting
  `ImportError` as the expected (non-strict) failure.
- `test_span_close_is_idempotent` intentionally exercises the `with`-block
  exit path rather than the manually-built path `test_span_lifecycle.py`
  already covers — its own docstring says that path is "unchanged here",
  so this test extends the `_closed` coverage rather than duplicating it.
- **OTLP tests use a fake tracer, not `sink_factory` / the real SDK.** The
  first draft of `test_otlp_sink_maps_attrs_to_genai_conventions` and
  `test_attrs_over_cap_are_truncated_not_dropped` went through
  `sink_factory({"type": "otel", ...})`, matching the convention every test
  in `tests/tracing/exporters/` already uses. That surfaced a **pre-existing**
  test-isolation issue: `opentelemetry.trace.set_tracer_provider` can only
  run once per process, so once any test establishes the real global
  `TracerProvider`, every later `otel`/`logfire` sink construction hits
  `_setup_tracer_provider`'s "Overriding of current TracerProvider is not
  allowed" fallback (`exporters.py:333-345`) and **permanently stacks one
  more `_RecordingSpanProcessor` onto the one shared provider** for the rest
  of the pytest session — the reset at the top of `_setup_tracer_provider`
  only clears `_RECORDING_PAYLOADS`, it does not deduplicate processors
  already registered on the provider. A single span-end then fires every
  stacked processor, appending one payload per processor for one write.
  `tests/tracing/exporters/test_integration.py::test_payload_cap_applies_to_remote_sinks`
  assumes exactly one recorded payload per write
  (`json.loads(b"".join(captured_payloads_json()).decode() or "[]")` breaks
  the moment there are two) — **confirmed pre-existing and order-dependent**:
  it fails intermittently under random test ordering even with these two new
  tests reverted, just not under the fixed seed (`424242`) `make test` uses.
  Not fixed here — it is a structural property of `_setup_tracer_provider`'s
  fallback path, and this wave's mandate is the 12 tests named above, not an
  unrelated pre-existing flake in `tests/tracing/exporters/`. Flagging for
  whoever next touches `exporters.py`'s provider-reuse path (out of scope for
  G5.2, which only touches `tracer.py`).

  The final two tests sidestep the shared provider entirely: `OTLPSink` is
  constructed with `provider=object()` (a non-`None` sentinel that short-
  circuits `_ensure_provider()`) and `sink._tracer` is set directly to a
  small `_FakeOtelTracer` that records `start_span(name=..., attributes=...)`
  calls. This is a stricter unit test of `OTLPSink.write`'s own attribute
  mapping, needs no optional extra, and adds nothing to the shared global
  provider state.
