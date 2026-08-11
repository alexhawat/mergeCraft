# T2 — `provider.call` parent + outbound HTTP spans with URL redaction — test plan

Wave plan: `.ignorelocal/waves/issues-tracing-sevn-quality-wave-plan.md`
Worktree: `mergecraft-trq-t2-http` @ `wave/trq-t2-http`
Base: `origin/pre-0.0.1` @ `78db73b` (post-T3.2 — `trace_id` plumbing already landed)

This doc is the per-test traceability table for T2.1 (the `role: test-author`
wave). The implementation (T2.2) is owned by `wave-runner`; once that lands,
an xfail-reconciliation pass removes the satisfied markers.

## xfail schedule

| Wave  | Test files                          | Marker reason prefix        | Tests xfailed |
|-------|-------------------------------------|-----------------------------|---------------|
| **T2.2** | `tests/tracing/test_http_spans.py` | `green after T2.2: …`     | 1             |

All cross-wave markers use `strict=False` (repo `xfail_strict = true`).
The single xfail is `test_provider_call_span_wraps_llm_call_for_anthropic` —
it pins the new `provider.call` parent span wrapping the existing
`llm.call` for the Anthropic transport family. The other 11 tests turn
green the moment T2.2 ships `redact_url` (file 1), `instrument_httpx`
(file 2), the OpenAI-compatible gateway instrumentation (file 3), and the
chat-completions driver attribute widening (file 6).

## Contract matrix — T2.1 (tests 1–12)

| #  | Test | File:line | xfail | T2.2 surface | Coverage |
|----|------|-----------|-------|--------------|----------|
| 1  | `test_instrument_httpx_emits_one_span_per_send` | `test_http_spans.py` | — | `tracing/http.py::instrument_httpx` wraps `client.send` (sync) to emit one `http.client.request` span | Unit: per-send span emission |
| 2  | `test_http_span_attrs_have_method_status_duration` | `test_http_spans.py` | — | `tracing/http.py::instrument_httpx` writes `http.method` / `http.status_code` / `http.duration_ms` attrs | Integration: real local `HTTPServer` end-to-end |
| 3  | `test_redact_url_redacts_telegram_bot_token` | `test_http_spans.py` | — | `tracing/redaction.py::redact_url` pattern 1 (`api.telegram.org/bot<TOKEN>`) | Unit: URL redaction |
| 4  | `test_redact_url_redacts_basic_auth` | `test_http_spans.py` | — | `tracing/redaction.py::redact_url` pattern 2 (basic auth userinfo) | Unit: URL redaction |
| 5  | `test_redact_url_redacts_query_param_tokens` | `test_http_spans.py` | — | `tracing/redaction.py::redact_url` pattern 3 (query-param tokens) | Unit: URL redaction |
| 6  | `test_redact_url_preserves_path_shape` | `test_http_spans.py` | — | `tracing/redaction.py::redact_url` keeps scheme/host/port/path intact | Unit: redaction is inline not opaque (D9) |
| 7  | `test_instrument_httpx_idempotent` | `test_http_spans.py` | — | `tracing/http.py::instrument_httpx` sentinel `_mergecraft_instrumented` guard (D8) | Unit: idempotency |
| 8  | `test_provider_call_span_wraps_llm_call_for_anthropic` | `test_http_spans.py` | **Yes** (`strict=False`) | `agents/claude.py::_claude_stream_event_handler` opens `provider.call` (`provider.transport_family="anthropic"`) on `message_start`, closes on `message_stop`; `llm.call` becomes a child | Integration: Anthropic provider/llm span tree (D10) |
| 9  | `test_provider_call_span_wraps_llm_call_for_chat_completions` | `test_http_spans.py` | — | `agents/openai_compatible_gateways.py` (and the opencode/Nous/MiniMax driver) wraps `llm.call` inside `provider.call` (`provider.transport_family="chat_completions"`); `http.client.request` is a grandchild | Integration: OpenAI-compatible provider/HTTP span tree (D8/D10) |
| 10 | `test_http_failure_emits_span_with_status_code_0` | `test_http_spans.py` | — | `tracing/http.py::instrument_httpx` records `http.status_code=0` and `http.error_class=type(exc).__name__` on connection failure | Unit: error path attrs |
| 11 | `test_http_span_inherits_trace_id_from_mergecraft_run` | `test_http_spans.py` | — | `OTLPSink._override_span_trace_id` rewrites the OTel `trace_id` on the produced span; relies on T3.2 `trace_id` plumbing (`Tracer.trace_id` / `Span.trace_id` / `TraceEvent.trace_id`) | Integration: cross-wave bridge with T3 |
| 12 | `test_disabled_tracer_path_emits_no_http_span` | `test_http_spans.py` | — | `tracing/http.py::instrument_httpx` no-ops when the resolved tracer is a `NullTracer` (convention 9 / D9) | Unit: disabled path |

**Acceptance:** 12 collected; 11 fail (RED pending T2.2); 1 xfailed (test 8, strict=False).

## Cross-test dependencies

- **Test 2** spins a real `http.server.HTTPServer` on an ephemeral loopback
  port (`unused_tcp_port` fixture) and asserts on the produced
  `http.client.request` span attrs. No live network call; the port is
  bound by a thread-local server that is shut down on teardown.
- **Tests 1, 9, 10, 11, 12** use a deliberately-unreachable loopback URL
  (`http://127.0.0.1:0/` or `http://127.0.0.1:1/`) to trigger the
  connection-refused path without making a network call. The instrumentation
  must still emit a span (test 1 / 10), must still propagate the mergeCraft
  `trace_id` onto the produced span (test 11), and must remain a no-op when
  the tracer is `NullTracer` (test 12).
- **Test 8** exercises the production
  `agents/claude.py::_claude_stream_event_handler` with the recorded
  Anthropic stream-json event sequence (message_start → message_delta →
  message_stop → result). The driver must wrap the existing `llm.call`
  span inside a new `provider.call` parent span (D10).
- **Test 11** depends on T3.2's `trace_id` plumbing (`Tracer.trace_id`,
  `Span.trace_id`, `TraceEvent.trace_id`) landing first — the rebased
  T2 worktree already includes T3.2 (commit `78db73b`), so the
  RED→GREEN transition is purely about T2.2 wiring `instrument_httpx`
  to write the `trace_id` onto the produced span.
- **Test 7** asserts that `instrument_httpx` is idempotent via a sentinel
  attribute on the wrapped client. The sentinel name is
  `_mergecraft_instrumented` (D8 — narrow instrumentation scope; the
  sentinel lives on the constructed client, never on a shared `httpx`
  module attribute).

## Known RED cross-effects

T2.1 adds a new file `tests/tracing/test_http_spans.py`. There are no
existing tests in the `tests/tracing/` tree that depend on `redact_url`,
`instrument_httpx`, or `provider.call` directly, so the cross-wave RED
behaviour is localised to the 11 failing tests + 1 xfailed test inside this
file. The T2.2 impl wave turns all 12 green.

The `test_tracing_resolution.py`, `test_sinks.py`, and
`test_trace_id_bridge.py` files are unaffected by the T2 contract surface.

## Verification

- **Collection:** `uv run pytest --collect-only -q tests/tracing/test_http_spans.py` → 12 collected, 0 errors.
- **RED pytest:** `uv run pytest tests/tracing/test_http_spans.py` → `11 failed, 1 xfailed`.
- **Lint:** `make lint` → clean (ruff check + format check + loguru-only on `src tests scripts`).
- **Typecheck:** `make typecheck` → clean (mypy is targeted at `src/mergecraft`; the test file references forward-only attributes like `redact_url` and the missing `mergecraft.tracing.http` module, which mypy flags only when run against `tests/` directly — out of scope for the repo gate).

## xfail-reconciliation

When T2.2 lands and `test_provider_call_span_wraps_llm_call_for_anthropic`
turns GREEN, the orchestrator dispatches `test-creator` again to remove the
`@pytest.mark.xfail` marker on test 8. The other 11 tests require no marker
removal (they were RED, not xfail).

The wave plan's contract surfaces that the reconciliation pass must verify
before declaring T2 done:

- `tests/tracing/test_http_spans.py` → 12 collected, 12 green (or
  11 green + 1 xfail if the impl wave chose a different xfail surface, which
  the wave-plan-author can re-pin if needed).
- `make ci-resume` clean (full T2 final gate, run by `wave-runner`).
- `mergecraft diff-review --tracing --tracing-to logfire --base origin/pre-0.0.1 --cwd /tmp/empty-repo`
  produces a Logfire trace with the new rows (one `provider.call` per
  upstream API call, one `http.client.request` per outbound httpx call
  with redacted URL).
