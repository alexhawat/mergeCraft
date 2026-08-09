# Tracing — test plan (W1 RED)

Wave plan: `.ignorelocal/waves/issues-tracing-observability-wave-plan.md`
Worktree: `mergecraft-trc-a-sinks` @ `wave/trc-a-sinks`

## xfail schedule

All tests under `tests/tracing/` are W1 contracts implemented by W2. Every cross-wave marker uses `green after W2: …` and `strict=False`; W2 removes the markers after implementation.

## Contract matrix

| Contract | Unit | Integration | Functional / edge / error | Primary tests |
|----------|------|-------------|---------------------------|---------------|
| W1.1 config round-trip and default disabled | `RepoSettings` default and aliases | YAML load and model dump | absent `tracing` block | `tests/tracing/test_config.py` |
| W1.2 shorthand normalization (D9) | shorthand parser | canonical sink-list output | downstream has no `to` shape | `tests/tracing/test_config.py` |
| W1.3 `TraceEvent` shape | required fields and model round-trip | — | empty attrs; missing parent span | `tests/tracing/test_config.py` |
| W1.4 daily JSONL rotation | date-derived filenames | two writes across midnight | malformed JSONL line is skipped | `tests/tracing/test_sinks.py` |
| W1.5 multi-sink fan-out | `MultiSink.write` | every child receives the same event | — | `tests/tracing/test_sinks.py` |
| W1.6 redaction once before fan-out (D7) | wrapper types | `sink_factory` live tree | structural no-bypass assertion | `tests/tracing/test_redaction.py` |
| W1.7 secret redaction | deny-value and deny-key tables | redacting wrapper into recording sinks | `ghp_`, `sk-`, ten deny keys | `tests/tracing/test_redaction.py` |
| W1.8 64 KiB attrs cap (D8) | boundary table at cap and cap + 1 | event row identity survives | truncation marker replaces oversized attrs | `tests/tracing/test_redaction.py` |
| W1.9 retention purge (D8) | default `retentionDays=30` | local file lifecycle | expired removed, current retained | `tests/tracing/test_sinks.py` |
| W1.10 best-effort failure | sink exception boundary | failing child through `MultiSink` | warning logged; caller result unchanged | `tests/tracing/test_sinks.py` |
| W1.11 disabled true no-op | `NullSink` resolution | config to `sink_factory` | no attrs evaluation; no directory; disabled mid-run | `tests/tracing/test_sinks.py` |

## Shared fixtures

`tests/tracing/conftest.py` supplies an isolated trace directory, fake attrs independent of real agents, and canonical event data. Sink probes are in-memory test doubles so W1 performs no network calls.

## RED acceptance

The suite must collect without import errors, pass `make lint` and `make typecheck`, and remain non-strict xfail until W2 implements `mergecraft.tracing` and the `RepoSettings.tracing` block.

---

# Tracing — test plan (W3 RED, Batch B)

Wave plan: `.ignorelocal/waves/issues-tracing-observability-wave-plan.md`
Worktree: `mergecraft-trc-b-spans` @ `wave/trc-b-spans`
Branch base: `origin/pre-0.0.1` after PR #99 (`a6c4078`) — Batch A merged.

## xfail schedule

All tests under `tests/tracing/instrumentation/` are W3 contracts implemented by W4. Every cross-wave marker uses `green after W4: …` and `strict=False`; W4 removes the markers after implementation. The Batch A markers (`green after W2`) are already reconciled — they no longer appear in this directory.

## Contract matrix (W3 — span tree instrumentation)

|| Contract | Unit | Integration | Functional / edge / error | Primary tests |
||----------|------|-------------|---------------------------|---------------|
|| **W3.1** issue §3 span tree | `TraceEvent.kind` set membership | full lifecycle through `run_with_model_chain` + `run_analyzer_pipeline` | exactly one root span; every non-root parent reachable; all eight kinds present | `tests/tracing/instrumentation/test_span_tree.py` |
|| **W3.2** one `agent.attempt` per fallback entry (issue §3 motivation) | `model.fallback_index` math | chain driven by fake `run_once` | 3-entry happy; 1-entry edge; skipped-entry shape; retryable-then-success; per-attempt attributes (`agent.provider`, `agent.mode`, `cli_argv` redacted) | `tests/tracing/instrumentation/test_agent_attempt.py` |
|| **W3.3** `analyzer.run` carries id / exit_code / findings_count / duration | adapter result → attrs | `run_analyzer_pipeline` end-to-end | zero findings still emits a span; non-zero exit recorded; parent `mergecraft.analyzers.pipeline` span present | `tests/tracing/instrumentation/test_analyzer_run.py` |
|| **W3.4** correlation attributes on root span | attr assembly | run lifecycle | `run_id`, `repo`, `pr_number`, `commit_sha`, `workflow_run_id`, `job_id` | `tests/tracing/instrumentation/test_span_tree.py` |
|| **W3.5** `usage_entries` consumed (D11) | `cost.*` attr set on `llm.call` | chain with `AgentUsage` | per-attempt attribution across multi-attempt chains; D11 alternative: field may be deleted | `tests/tracing/instrumentation/test_usage_entries.py` |
|| **W3.6** disabled no-op (convention 9) | `NullSink.emit` | full run lifecycle with tracing off | no filesystem; no span emission; `attrs_source` never invoked | `tests/tracing/instrumentation/test_span_tree.py` |
|| **W3.7** redaction at emit sites (D7) | deny-value / deny-key / cli_argv redacted | run lifecycle through `run_with_model_chain` | `ghp_` / `sk-` substrings cannot escape; `agent.cli_argv` redacted; deny-key attributes replaced | `tests/tracing/instrumentation/test_secrets_at_emit_sites.py` |
|| **W3.8** emit failure never fails the run (convention 6) | raising sink through `MultiSink` | chain driven by fake `run_once` with raising sink | no exception propagates; agent result unchanged; warning logged | `tests/tracing/instrumentation/test_emit_failure.py` |

## W3 fixtures

`tests/tracing/instrumentation/conftest.py` adds (additive, parallel to Batch A's `tests/tracing/conftest.py`):

- `captured_sink` — resolves `RepoSettings.tracing` to a live `MemorySink` via `sink_factory`, wraps it in a `CapturedSink` helper that exposes `events` and `by_kind`. W4 must route production emit sites through `sink_factory` so this fixture observes them.
- `disabled_tracing` — the resolved `NullSink` from `sink_factory` for the convention-9 path.
- `correlation_fields` — the canonical attribute set W3.4 pins.
- `make_agent_result` / `make_agent_usage` — dataclass factories used to drive `run_with_model_chain` without real CLI invocations.

## W3 driving strategy

- The suite drives `run_with_model_chain` with a fake `run_once` callable that returns canned `AgentResult`s per fallback entry — no live CLI invocation, no subprocess.
- The suite drives `run_analyzer_pipeline` with an in-tree demo analyzer registered via `register_manifest`. The adapter returns canned `Finding`s.
- The suite asserts **observable** outcomes on the `MemorySink` (events by `kind`, attributes by name). It does not lock W4's internal tracer implementation.

## W3 RED acceptance

The suite must collect without import errors, pass `make lint` and `make typecheck`, and remain non-strict xfail until W4 instruments the span tree. The one contract already satisfied today (`test_instrumentation_is_noop_when_disabled`) is an XPASS — non-strict xfail, marker removed by W4 reconciliation.

## W3 RED coverage matrix

| Layer | Tests |
|-------|-------|
| **Unit** | `_build_settings`, `_drive_chain`, `make_agent_result`, `make_agent_usage`, `CapturedSink.by_kind` |
| **Integration** | `run_with_model_chain` → `MemorySink`; `run_analyzer_pipeline` → `MemorySink`; `RedactingSink.write` round-trip |
| **Functional / scenario classes** | happy path (full tree); edge cases (single-entry chain, zero findings, mid-run disable); error handling (raising sink, retryable failure, non-zero analyzer exit, malformed argv) |

## W3 / W4 reconciliation

When W4 lands:

1. W4 removes all `green after W4: …` xfail markers from this directory.
2. The full test run for `tests/tracing/instrumentation/` becomes a clean pass.
3. Any test that flips from xfail to fail on W4 lands is a W4 bug, not a test bug.
