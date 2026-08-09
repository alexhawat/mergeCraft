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
