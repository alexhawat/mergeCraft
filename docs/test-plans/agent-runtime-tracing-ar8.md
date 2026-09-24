# Agent runtime & tracing — AR8.3 regression pins — test plan

Wave plan: `.ignorelocal/waves/42-agent-runtime-tracing-wave-plan.md` (§AR8)
Worktree/repo root: `/Users/alex/Documents/code/sevn.bot/mc-agents`
Authoring wave: **AR8.3** (owner: `test-creator`). Product fixes: **AR8.1** / **AR8.2** (uncommitted in the tree; orchestrator commits).
Trace run: service `mergecraft-dev` · wave.plan=agent-runtime-tracing ·
run.id=`fb108bac-7527-41db-92be-3529ec8b4e40` · wave.id=**AR8**.

AR8.1/AR8.2 fixed two CI failures that only appeared when test order changed
(our added suites reshuffled the worker schedule). Both fixes were structural
and had **no product-visible behaviour**; these pins lock the invariant so it
cannot drift back. No product source is edited here.

## Fixed contract → coverage matrix

| Fix | Contract | Test | Layer | Scenario | Pre-fix |
| --- | --- | --- | --- | --- | --- |
| AR8.2 | `StderrDrain.text()` snapshots the buffer under the same lock the reader appends under, so a bounded `join` that returns with the reader still active cannot raise `RuntimeError: deque mutated during iteration` | `tests/agents/test_agent_stderr_drain.py::test_text_snapshot_is_taken_under_the_buffer_lock` | unit | error / concurrency | **FAILS** (`RuntimeError: deque mutated during iteration`) |
| AR8.2 | A live reader keeps appending after an early `join`; repeated `text()` returns the tail read so far with no torn lines and no exception | `tests/agents/test_agent_stderr_drain.py::test_text_returns_tail_while_the_reader_is_still_appending` | unit | edge / concurrency | passes (behavioural guard) |
| AR8.1 | A `sink_factory` `NullSink` outcome for `enabled=True` + `logfire`/`otel` while enterprise `telemetry: off` resets the exporter test seam, so `has_active_tracer_provider()` is `False` **after** a prior OTLP construction in the same worker | `tests/tracing/exporters/test_null_sink_seam_reset.py::test_null_sink_for_telemetry_off_clears_a_prior_otlp_provider[logfire\|otel]` | integration | error / ordering | **FAILS** (`assert True is False`) |
| AR8.1 | The `enabled=False` path still resets the seam after the `_null_sink` funnel refactor | `tests/tracing/exporters/test_null_sink_seam_reset.py::test_disabled_tracing_still_clears_a_prior_otlp_provider` | integration | guard-deletion | passes (regression guard) |

The two `NullSink`-reset params exercise both remote sink types the
"enabled but no remote children" branch can see.

## Pre-fix reproduction (how the pins were proven red)

HEAD `7453724f` predates the two uncommitted fixes. With the two source files
stashed (`git stash push -- src/mergecraft/agents/shared.py
src/mergecraft/tracing/sinks.py`), the new pins ran against the pre-fix code:

```
tests/agents/test_agent_stderr_drain.py::test_text_snapshot_is_taken_under_the_buffer_lock
    RuntimeError: deque mutated during iteration
tests/tracing/exporters/test_null_sink_seam_reset.py::test_null_sink_for_telemetry_off_clears_a_prior_otlp_provider[logfire]
    AssertionError: a NullSink outcome must reset the exporter seam …
    assert True is False
tests/tracing/exporters/test_null_sink_seam_reset.py::test_null_sink_for_telemetry_off_clears_a_prior_otlp_provider[otel]
    AssertionError: … assert True is False
3 failed, 2 passed
```

Restored with `git stash pop`; the fixed tree is green (below).

### Why AR8.2 has a deterministic half and a behavioural half

CPython snapshots the `deque` inside `"".join(...)` under the GIL, so a
pure-Python appender cannot be *forced* to interleave with it on every
platform — the real-stream case is therefore a behavioural guard that the
early-return path returns the tail and never raises. The deterministic half
(`test_text_snapshot_is_taken_under_the_buffer_lock`) drives a real
`start_stderr_drain` handle whose buffer raises exactly as a concurrently
mutated `deque` does unless the snapshot holds the buffer lock; it fails on the
pre-fix bare `"".join(self._lines)` and passes now. Neither half merely asserts
that the lock exists.

## Commands and results (fixed tree)

| Command | Result |
| --- | --- |
| `uv run --extra tracing pytest tests/agents/test_agent_stderr_drain.py tests/tracing/exporters/ -q` | `123 passed in 190.81s` |
| `uv run --extra tracing pytest tests/tracing/exporters/test_otlp_pipeline.py tests/enterprise/test_runtime_enforcement.py -q -p no:randomly` | `27 passed in 25.91s` |
| `make lint` | clean |
| `make typecheck` | clean |

`OTEL_*` / `LOGFIRE_*` were cleared before every pytest run.

## Files

| File | Change |
| --- | --- |
| `tests/agents/test_agent_stderr_drain.py` | extended — AR8.3(a) section: `_StayOpenStream`, `_LockGuardedBuffer`, 2 tests |
| `tests/tracing/exporters/test_null_sink_seam_reset.py` | added — AR8.3(b): 2 tests (parametrized + disabled-path guard), self-contained enterprise bind/reset |

No `tests/conftest.py` edit (AR-D13); no `src/` edit.

## Reconciliation log

- AR8.3 (2026-09-24): suite authored; 1 file extended + 1 file added; 3 of 5
  new cases fail against pre-fix source, all 5 green on the fixed tree.
