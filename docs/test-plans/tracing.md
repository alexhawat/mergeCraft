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
---

# Batch D — exporters, extra, CLI/action, docs (W7 RED)

Wave plan: `.ignorelocal/waves/issues-tracing-observability-wave-plan.md`
Worktree: `mergecraft-trc-d-exporters` @ `wave/trc-d-exporters`

## xfail schedule

All tests under `tests/tracing/exporters/` are W7 contracts implemented by W8. Every cross-wave marker uses `green after W8: …` and `strict=False`; W8 removes the markers after implementation. Tests that genuinely depend on `logfire` / `opentelemetry` use `pytest.importorskip(...)` so they return a skip (not a fail) when the extra is uninstalled — that satisfies W7.5 from the test side.

## Contract matrix

| Contract | Unit | Integration | Functional / edge / error | Primary tests |
|----------|------|-------------|---------------------------|---------------|
| W7.1 `logfire` and `otel` share one OTLP code path (D5) | same class for both `sink_factory` resolutions | endpoint + headers flow through the same module path | resolve to the same exporter module | `tests/tracing/exporters/test_otlp_pipeline.py::test_logfire_and_otel_share_one_code_path`, `..._share_endpoint_resolution` |
| W7.2 absent token = no export, no error | `tokenRef`/`MERGECRAFT_LOGFIRE_TOKEN` resolution | factory returns a sink with no network call | warning logged; factory does not raise | `tests/tracing/exporters/test_logfire_sink.py` |
| W7.3 OTLP exports to arbitrary endpoint + headers | endpoint + headers parser | sink exports spans to a self-hosted collector by IP | default endpoint when unset | `tests/tracing/exporters/test_otlp_pipeline.py::test_otel_sink_exports_to_arbitrary_endpoint_and_headers`, `..._uses_default_endpoint_when_unset` |
| W7.4 `tokenRef` is resolved, never inlined (D5) | `model_dump` does not contain the literal value | YAML round-trip preserves reference, drops value | logs do not contain value; `mergecraft config tracing` redacts value | `tests/tracing/exporters/test_token_resolution.py` |
| W7.5 extra uninstalled is a clean no-op (convention 5, D6) | `import mergecraft` succeeds without `logfire`/`opentelemetry` | factory degrades to a stub with a clear warning | optional extra declared in `pyproject.toml` | `tests/tracing/exporters/test_optional_extra.py` |
| W7.6 CLI flag > env > `.mergecraft/config.yaml` > default (off) | precedence arithmetic | `mergecraft diff-review --help` exposes new flags | `--no-tracing` wins over `MERGECRAFT_TRACING=true`; `--logfire-token` wins over env; `--trace-dir` wins over YAML | `tests/tracing/exporters/test_cli_precedence.py` |
| W7.7 `action.yml` inputs map to config | `INPUT_TRACING`, `INPUT_TRACING_TO`, `INPUT_LOGFIRE_TOKEN`, `INPUT_OTEL_ENDPOINT` resolution | `tracing` shorthand expands correctly | `INPUT_LOGFIRE_TOKEN` distinct from `INPUT_TOKEN`; `GITHUB_WORKSPACE` honoured for local sink path | `tests/tracing/exporters/test_action_inputs.py` |
| W7.8 remote sink failure never fails the run (convention 6) | unreachable endpoint swallows the error | caller result unchanged; warning logged | `flush()` is idempotent | `tests/tracing/exporters/test_otlp_pipeline.py::test_remote_sink_failure_never_fails_the_run`, `..._flush_is_idempotent_when_unreachable` |
| W8.4 surface (preview) | `mergecraft config tracing` and `mergecraft traces <run-id>` exist | `config tracing` shows redacted sinks; `traces` reads local JSONL | redaction applies to dump; missing run id is a clean exit | `tests/tracing/exporters/test_config_tracing_cmd.py` |
| Integration — `logfire` + `otel` + local fan-out (D7) | redacting wrapper outside the multi-sink | three sinks composed under one redaction boundary | redaction applies to remote transport; payload cap propagates | `tests/tracing/exporters/test_integration.py` |

## Shared fixtures

`tests/tracing/exporters/conftest.py` supplies an isolated env helper, a loopback-only fake OTLP endpoint, a free TCP port picker, and a canonical event payload. The exporter tests use `pytest.importorskip("logfire" / "opentelemetry")` to gate the installed path; uninstalled path tests inject a stub module into `sys.modules` to simulate the missing extra.

## RED acceptance

The suite must collect without import errors, pass `make lint` and `make typecheck`, and remain non-strict xfail until W8 ships the OTLP pipeline (`mergecraft.tracing.exporters`), the CLI precedence helper (`mergecraft.cli.tracing_precedence`), the action-input resolver (`mergecraft.action.inputs`), and the `mergecraft config tracing` / `mergecraft traces` commands. The W2.3 `NullSink` and the W2.1 `TraceSinkEntry.tokenRef` already satisfy four contracts (the corresponding tests will xpass rather than xfail when W7 lands — confirmed on the W7 RED sweep 2026-08-09).
