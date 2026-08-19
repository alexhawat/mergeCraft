# Open issues sweep 2026-08-19d — Batch Q test plan (#292)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-19d-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-19d` @ `wave/open-issues-sweep-2026-08-19d`
Authoring wave: **W3** (Batch Q RED) · Implementation: **W4** (trace_id pin + Tracer reuse)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W4** | `test_get_tracer_from_settings_shares_trace_id_without_active_span` | `green after W4: #292 pin MERGECRAFT_TRACE_ID + reuse Tracer` | pending |
| **W4** | `test_first_get_tracer_from_settings_sets_mergecraft_trace_id_env` | `green after W4: #292 pin MERGECRAFT_TRACE_ID + reuse Tracer` | pending |

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| Q292a | MCP-style repeated ``get_tracer_from_settings`` shares ``trace_id`` | functional | no active span; N=2 | `tests/tracing/test_tracer_trace_id_pin.py::test_get_tracer_from_settings_shares_trace_id_without_active_span` |
| Q292b | First mint ``setdefault``\ ``MERGECRAFT_TRACE_ID`` | unit | env unset before first call | `test_first_get_tracer_from_settings_sets_mergecraft_trace_id_env` |

## W3.1 note

Deterministic RED via ``strict=False`` xfail. Live code calls ``resolve_trace_id()``
per ``get_tracer_from_settings`` construction and falls through to ``uuid4`` when
``MERGECRAFT_TRACE_ID`` is unset (`tracer.py:731-736, 763-785`). W4 implements D9
in ``tracing/tracer.py`` only.

## Acceptance (W3)

- New tests collect with zero import errors
- ``make lint`` + ``make typecheck`` clean on touched paths
- Both Batch Q tests xfail (not xpass)
- No ``src/`` edits; no D6 paths
