# T1 — `tool.call` attrs enriched for invoke / complete / verb sub-event info — test plan

Wave plan: `.ignorelocal/waves/issues-tracing-sevn-quality-wave-plan.md`
Worktree: `mergecraft-trq-t1-tool` @ `wave/trq-t1-tool`
Base: `origin/pre-0.0.1` @ `166c7c7` (post-T3.2 + post-T2.2 — `trace_id` plumbing
and `provider.call` parent have already landed)

This doc is the per-test traceability table for T1.1 (the `role: test-author`
wave). The implementation (T1.2) is owned by `wave-runner`; once that lands,
an xfail-reconciliation pass removes the satisfied markers.

## xfail schedule

| Wave    | Test files                                       | Marker reason prefix                                  | Tests xfailed |
|---------|--------------------------------------------------|-------------------------------------------------------|---------------|
| **T1.2** | `tests/tracing/test_tool_call_attrs.py`         | `green after T1.2: tool.complete / tool.browse …`     | 1             |

All cross-wave markers use `strict=False` (repo `xfail_strict = true`).
The single xfail is `test_known_verb_tool_emits_verb_sub_event` — it pins
the verb sub-event child span (`tool.browse` for `tool.name == "browser"`)
which is the differentiating T1.2 surface. The other 10 tests are split
between five RED tests that turn green the moment T1.2 ships file 1
(`mcp/server.py::tools/call` enrichment), files 2–3 (driver close-side
enrichment), file 4 (`_tool_attrs.py` shared helpers), and file 5
(`redact_tool_payload`), and five regression pins that already pass
against the post-T3 + post-T2 tree.

## Contract matrix — T1.1 (tests 1–11)

| #   | Test | File:line | xfail | T1.2 surface | Coverage |
|-----|------|-----------|-------|--------------|----------|
| 1   | `test_mcp_tool_call_span_has_request_attrs` | `tests/tracing/test_tool_call_attrs.py` | — | `mcp/server.py::tools/call` enriches `call_attrs` with `tool.arguments` / `tool.argument_count` / `tool.argument_bytes` / `tool.exit_code="ok"` / `tool.result_kind` / `tool.result_bytes` (file 1) | Integration: MCP `tools/call` HTTP endpoint spans |
| 2   | `test_mcp_tool_call_span_has_error_attrs` | `tests/tracing/test_tool_call_attrs.py` | — | `mcp/server.py::tools/call` exception path sets `tool.exit_code="error"` / `tool.error_class` / `tool.error_message` (redacted) and keeps `gen_ai.tool.output` set (file 1) | Integration: MCP `tools/call` failure path |
| 3   | `test_claude_tool_call_span_has_request_response_attrs` | `tests/tracing/test_tool_call_attrs.py` | — | `agents/claude.py::_claude_stream_event_handler` `tool_result` event sets `tool.exit_code="ok"` / `tool.output_bytes` / `tool.output_kind` (file 2) | Integration: Claude driver close-side attrs |
| 4   | `test_codex_tool_call_span_has_request_response_attrs` | `tests/tracing/test_tool_call_attrs.py` | — | `agents/codex.py::_codex_stream_event_handler` `item.completed` event sets `tool.exit_code="ok"` / `tool.output_bytes` / `tool.output_kind` (file 3) | Integration: Codex driver close-side attrs |
| 5   | `test_gemini_tool_call_span_has_request_response_attrs` | `tests/tracing/test_tool_call_attrs.py` | — | `agents/gemini.py::_gemini_stream_event_handler` `tool_result` event sets `tool.exit_code="ok"` / `tool.output_bytes` / `tool.output_kind` (file 3) | Integration: Gemini driver close-side attrs |
| 6   | `test_known_verb_tool_emits_verb_sub_event` | `tests/tracing/test_tool_call_attrs.py` | **Yes** (`strict=False`) | `agents/_tool_attrs.py::emit_verb_subevent` opens + immediately closes a `tool.browse` child span whose `parent_span_id` is the `tool.call` parent's `span_id` (file 4 + D5) | Integration: verb sub-event child span (T1.2-only surface) |
| 7   | `test_unknown_verb_tool_emits_no_verb_sub_event` | `tests/tracing/test_tool_call_attrs.py` | — | `agents/_tool_attrs.py::KNOWN_VERB_TOOLS` is a closed set; tools outside the set emit only the parent `tool.call` with no child (file 4) | Unit: verb sub-event gating |
| 8   | `test_tool_arguments_capped_at_64kb` | `tests/tracing/test_tool_call_attrs.py` | — | `tracing/cap.py::cap_event_attrs` fires on a 100 KB `tool.arguments` string value, replacing `attrs` with `{"truncated": True}` (D8 / convention 8) | Unit: 64 KiB cap on per-string-value attrs |
| 9   | `test_tool_arguments_redact_secrets` | `tests/tracing/test_tool_call_attrs.py` | — | `tracing/redaction.py::redact_attrs` scrubs `Authorization: Bearer ghp_…` substrings from any string value inside `attrs` (existing redaction boundary) | Unit: existing redaction boundary |
| 10  | `test_existing_tool_call_attrs_still_present` | `tests/tracing/test_tool_call_attrs.py` | — | T1.2 is additive (D5): the existing `tool.name` / `tool.id` / `tool.server` / `gen_ai.*` attrs remain on the span after enrichment | Unit: regression pin |
| 11  | `test_disabled_tracer_path_emits_no_tool_call_attrs` | `tests/tracing/test_tool_call_attrs.py` | — | `tracing/tracer.py::NullTracer.start_span` returns a `NullSpan` whose `set_attribute` is a no-op; no `AttributeError` when the new emit sites call `span.set_attribute("tool.exit_code", "ok")` (convention 9 / #56 D9) | Unit: disabled path |

**Acceptance:** 11 collected; 5 fail (RED pending T1.2); 5 pass (regression pins); 1 xfailed (test 6, strict=False).

After T1.2 ships, the 5 RED tests turn green (assuming the impl satisfies the
contract) and the xfail is reconciled to a real pass, yielding **11 pass**.

## Cross-test dependencies

- **Test 1, 2** use the live `mcp/server.py::create_mcp_app` FastAPI app via
  `fastapi.testclient.TestClient`. The MCP handler builds its tracer via a
  lazy `from mergecraft.tracing.tracer import get_tracer_from_settings` so
  the tests `monkeypatch.setattr("mergecraft.tracing.tracer.get_tracer_from_settings", lambda _settings: tracer)`
  to route the emitted spans onto a local `MemorySink`.
- **Test 2** uses `TestClient(..., raise_server_exceptions=False)` so the
  raising tool surfaces as a 500 response inside the test rather than
  bubbling through the harness; the span still emits on `__exit__` with the
  error attrs set.
- **Tests 3, 4, 5, 6, 7** drive the agent driver `_claude_stream_event_handler` /
  `_codex_stream_event_handler` / `_gemini_stream_event_handler` directly
  with a two-event sequence (`open tool.call` → `close tool.call`). The
  handlers were already wired in T2 (anthropic wrapping) and T6 (tool.call
  open) — T1.2 only adds the new attrs and the verb sub-event emission.
- **Test 8** sets a 100 KB string `tool.arguments` attribute on a
  `tool.call` span; the existing `MemorySink.write` calls `cap_event_attrs`
  which fires on string values > 64 KiB and replaces `attrs` with
  `{"truncated": True}`.
- **Test 9** relies on the existing `redact_attrs` boundary (T2 / D7) — the
  new `tool.arguments` attr inherits the same redaction automatically.
- **Test 11** uses `NullTracer` directly so the disabled path is exercised
  end-to-end without any settings plumbing.

## Deferred to T1.2 (impl wave)

- The new `tool.arguments` / `tool.argument_count` / `tool.argument_bytes`
  attrs on the MCP `tools/call` span (file 1).
- The new `tool.exit_code` / `tool.error_class` / `tool.error_message` attrs
  on the MCP failure path (file 1).
- The new `tool.exit_code` / `tool.output_bytes` / `tool.output_kind` attrs
  on the close-side of the three agent drivers (files 2 + 3).
- The new `tool.input_bytes` / `tool.input_keys` attrs on the open-side of
  the three agent drivers (file 2).
- The shared `agents/_tool_attrs.py` module with `KNOWN_VERB_TOOLS`,
  `enrich_tool_call_attrs`, `emit_verb_subevent`, and `_classify_tool_result`
  (file 4).
- The new `tracing/redaction.py::redact_tool_payload` helper (file 5).
- The verb sub-event child span emission (`tool.browse` for `tool.name ==
  "browser"`) — the single xfail surface (test 6).

## Deferred to xfail-reconciliation (post-T1.2)

- Remove the `@pytest.mark.xfail(reason="green after T1.2: …", strict=False)`
  marker from `test_known_verb_tool_emits_verb_sub_event` once T1.2 makes
  the verb sub-event emission deterministic.
