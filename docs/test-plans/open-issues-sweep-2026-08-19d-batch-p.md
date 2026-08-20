# Open issues sweep 2026-08-19d — Batch P test plan (#293)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-19d-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-19d` @ `wave/open-issues-sweep-2026-08-19d`
Authoring wave: **W1** (Batch P RED) · Implementation: **W2** (singleton OTLP processor)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W2** | `test_setup_tracer_provider_stacks_at_most_one_batch_processor` | `green after W2: #293 singleton OTLP processor` | pending |
| **W2** | `test_n_otlp_sinks_export_one_payload_per_span` | `green after W2: #293 singleton OTLP processor` | pending |
| **W2** | `test_get_tracer_from_settings_does_not_multiply_otlp_exports` | `green after W2: #293 singleton OTLP processor` | pending |

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| P293a | Shared provider carries at most one OTLP ``BatchSpanProcessor`` | unit | N identical ``_setup_tracer_provider`` calls | `tests/tracing/exporters/test_otlp_singleton_processor.py::test_setup_tracer_provider_stacks_at_most_one_batch_processor` |
| P293b | Shared provider carries at most one ``_RecordingSpanProcessor`` | unit | same as P293a | same |
| P293c | One span → one ``captured_payload`` entry after N ``OTLPSink`` constructions | integration | happy — N=5, one write | `test_n_otlp_sinks_export_one_payload_per_span` |
| P293d | MCP-style N ``get_tracer_from_settings`` → one export per span | functional | happy — N=5, one ``tool.call`` | `test_get_tracer_from_settings_does_not_multiply_otlp_exports` |

## W1.1 note

Deterministic RED via ``strict=False`` xfail. Live code stacks processors on every
``_setup_tracer_provider`` call when a real provider already exists
(``exporters.py:317-331``). W2 must skip ``add_span_processor`` when endpoint+headers
already match (process-wide singleton sink).

## Acceptance (W1)

- New tests collect with zero import errors
- ``make lint`` + ``make typecheck`` clean on touched paths
- All three Batch P tests xfail (not xpass)
- No ``src/`` edits; no D6 paths
