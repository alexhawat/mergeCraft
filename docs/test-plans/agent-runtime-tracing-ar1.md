# Agent runtime & tracing — RED suite — test plan (AR1)

Wave plan: `.ignorelocal/waves/42-agent-runtime-tracing-wave-plan.md` (wave **AR1**)
Worktree/repo root: `/Users/alex/Documents/code/sevn.bot/mc-agents`
Authoring wave: **AR1** (tests-first). Implementation: **AR2–AR5**. Final: **AR7**.
Trace run: service `mergecraft-dev` · wave.plan=agent-runtime-tracing ·
run.id=`fb108bac-7527-41db-92be-3529ec8b4e40` · wave.id=**AR1**.

This is the RED suite for AR2–AR5. It collects, lints and typechecks clean; the
new assertions fail pending implementation. No productsource is edited here.

## Locked decisions applied

| Decision | Test consequence |
| --- | --- |
| AR-D2 | stderr drained concurrently from spawn into one `agents/shared.py` helper; stdout/stderr pipes stay separate |
| AR-D3 | the stderr buffer is bounded and tail-kept; **cap = 2,000 lines** (AR0) |
| AR-D4 | `_boot_opencode_server` keeps its sync signature; group registered at spawn; both drains from spawn; stdout drain signals a `threading.Event`; boot waits on it; cleanup on cancel |
| AR-D5 | N9 has its own RED test (stderr-full-before-URL) |
| AR-D6 | `/prompt` fallback only on 404/405; every other ≥400 returns the first response, names the first status, retryable marking unchanged |
| AR-D7 | Claude deny list adds the six write/web tools and each `Agent(<tool>)` form, unconditionally |
| AR-D9 | U7 fixed at the factory (disabled = no enterprise call; bound = unchanged; unbound = scoped bind + reset) |
| AR-D10 | recorder is opt-in from test fixtures only; module switch default off; `_RECORDING_PAYLOADS` bounded |
| AR-D11 | header global keeps names, masks sensitive values; `_RecordingTransport` deleted |
| AR-D13 | no `tests/conftest.py` edits — seam fixtures live in the package conftests |
| AR-D16 | Gemini built-ins `write_file`, `replace`, `run_shell_command`, `web_fetch`, `google_web_search` excluded via a top-level `excludeTools` in the written `settings.json`; `-y` stays |

## Target API AR2–AR5 must satisfy (pinned symbol names)

The wave plan leaves helper spellings to the implementation; this suite pins
these exact names. They are asserted with a clear message, not an import error.

| Symbol | Contract | Owner |
| --- | --- | --- |
| `mergecraft.agents.shared.start_stderr_drain(stream, *, max_lines=…)` | starts a daemon reader immediately, returns a drain handle; tolerates closed pipes and `read()`-only / `readline()` fakes | AR2 |
| `mergecraft.agents.shared.STDERR_DRAIN_MAX_LINES` | `== 2000` | AR2 |
| `<drain>.join(timeout=None)` / `<drain>.text() -> str` | join is bounded; text is the tail-kept buffer | AR2 |
| `mergecraft.tracing.exporters._RECORDING_SEAM_ENABLED` | module bool, default `False` | AR5 |
| `mergecraft.enterprise.runtime` scoped-bind context manager (name free) | used by the factory; the disabled path calls nothing | AR5 |

`_RecordingSpanProcessor` bounding is behavioural (the suite feeds 4,000 spans
and requires fewer than 4,000 recorded), so AR5 may pick any cap < 4,000.

## Contract → coverage matrix

### P4 — stderr drained from spawn (AR2)

`tests/agents/test_agent_stderr_drain.py`

| Test | Layer | Scenario | Contract |
| --- | --- | --- | --- |
| `test_driver_returns_when_stderr_is_filled_before_stdout[claude\|codex\|gemini\|opencode]` | functional | edge / deadlock | a real child floods ~4 MB stderr, then emits its stdout event; the driver returns within 8 s and the `STDERR-SENTINEL-TAIL` reaches `result.error` |
| `test_driver_timeout_path_still_returns_when_stderr_is_filled[…]` | functional | error / timeout | same flood, no stdout event, `wait_or_kill_process_group` raises; the driver returns each driver's timeout error |
| `test_stderr_drain_cap_is_the_recorded_two_thousand_lines` | unit | boundary | `STDERR_DRAIN_MAX_LINES == 2000` |
| `test_drain_collects_a_stringio_fake_process_stream` | unit | happy | helper drains an `io.StringIO`, ordered tail |
| `test_drain_keeps_the_tail_when_the_stream_exceeds_the_cap` | unit | edge | `len(lines) <= cap`; newest kept, oldest dropped |
| `test_drain_tolerates_a_stream_that_closes_mid_read` | unit | error | `ValueError` mid-read ends the reader without raising |
| `test_drain_accepts_a_read_only_fake_process_stream` | unit | compatibility | `test_cov_*_paths` `_Reader` fakes (`.read()` only) still drain (AR-D3) |

### P5 + N9 — OpenCode boot bounds and drain (AR3)

`tests/agents/test_opencode_boot_bounds.py`

| Test | Layer | Scenario | Contract |
| --- | --- | --- | --- |
| `test_boot_registers_the_group_before_the_first_stdout_read` | unit | guard-deletion | `register_process_group` is recorded before the first stdout read; later `handle.close()` unregisters and reaps |
| `test_boot_failure_path_unregisters_and_reaps` | unit | error | a boot that never prints a URL kills, **unregisters** and reaps |
| `test_boot_keeps_its_synchronous_signature` | unit | compatibility | `_boot_opencode_server` returns a `_ServerHandle`, not a coroutine (AR-D4) |
| `test_boot_succeeds_when_stderr_fills_the_pipe_before_the_url` | functional | N9 edge | real child floods stderr then prints its URL; boot returns the handle |
| `test_run_keeps_the_event_loop_alive_during_boot` | integration | P5 hang | a concurrent asyncio task ticks *between* boot start and end |
| `test_cancelling_run_mid_boot_kills_and_reaps_the_child` | integration | P5 cancel | cancel reaches boot before its deadline; no live/uneaped child pid |

### P12 — OpenCode prompt fallback (AR3)

`tests/agents/test_opencode_prompt_fallback.py`

| Test | Layer | Scenario | Contract |
| --- | --- | --- | --- |
| `test_missing_endpoint_falls_back_to_prompt[404\|405]` | unit | happy | `/message` 404/405 → one `/prompt` call, success |
| `test_live_request_is_not_reposted[400\|422\|429\|500\|502\|503]` | unit | error | exactly one call; error names the first status; no second turn; retryable iff 429/5xx |
| `test_first_status_is_named_not_the_second` | unit | error | a 503 on `/message` is reported as `(503)`, never `(404)` from a would-be repost |

### S7 — Claude review tool boundary (AR4)

`tests/agents/test_claude_review_tool_boundary.py`

| Test | Layer | Scenario | Contract |
| --- | --- | --- | --- |
| `test_reviewer_denies_write_and_web_tools[no-ci\|ci]` | unit | happy / guard | `--disallowedTools` carries `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, `WebFetch`, `WebSearch` and each `Agent(<tool>)` |
| `test_execution_tools_stay_denied[no-ci\|ci]` | unit | guard-deletion | the four exec tools and their `Agent(…)` forms remain |
| `test_deny_list_constant_carries_the_review_tools` | unit | happy | `CLAUDE_DISALLOWED_TOOLS` exposes the same set |
| `test_ci_still_skips_permissions` | unit | edge | `--dangerously-skip-permissions` stays under `CI=true` (AR4.3) |
| `test_agent_definitions_do_not_regrant_denied_tools` | unit | guard (AR4.2) | no agent definition carries an allow-list re-granting a denied tool |

### S7 Gemini sibling — review tool boundary (AR4.4)

`tests/agents/test_gemini_review_tool_boundary.py`

| Test | Layer | Scenario | Contract |
| --- | --- | --- | --- |
| `test_settings_exclude_builtin_write_shell_and_web_tools[no-ci\|ci]` | unit | happy | top-level `excludeTools` names the five AR0-recorded built-ins |
| `test_per_server_mcp_exclusions_are_unchanged` | unit | compatibility | `mcpServers.mergecraft.excludeTools` keeps its contents |
| `test_auto_approve_flag_follows_ci[ci-adds-y\|no-ci-omits-y]` | unit | edge | `-y` is still appended iff `CI=true` |

### U7 — tracer factory reads, never rebinds (AR5)

`tests/tracing/test_tracer_enterprise_binding.py`

| Test | Layer | Scenario | Contract |
| --- | --- | --- | --- |
| `test_disabled_path_leaves_a_bound_enterprise_block_unchanged` | unit | edge | disabled `get_tracer_from_settings(RepoSettings())` leaves `allowed_regions=("eu",)` and `enforce_routed_model_residency` refusing a us model |
| `test_disabled_path_makes_no_enterprise_call` | unit | guard-deletion | the binder is never called on the disabled path |
| `test_first_construction_leaves_a_bound_enterprise_block_unchanged` | integration | happy | first enabled construction leaves the binding intact |
| `test_cached_path_leaves_a_bound_enterprise_block_unchanged` | integration | edge | the cached-tracer branch leaves it intact |
| `test_active_span_path_leaves_a_bound_enterprise_block_unchanged` | integration | edge | the active-span branch leaves it intact |
| `test_unbound_telemetry_off_builds_no_remote_sink_and_stays_unbound` | integration | error / error path | `telemetry: off` scopes to sink construction only; on return the block is unbound, telemetry restored, no provider |

### U8 — recorder and header copy are test-only (AR5)

`tests/tracing/exporters/test_recording_seam_test_only.py`
(module opts out of the enabling fixture by overriding `_enable_recording_seam`)

| Test | Layer | Scenario | Contract |
| --- | --- | --- | --- |
| `test_seam_off_adds_no_recording_processor_to_a_new_provider` | unit | guard-deletion | the fresh-provider branch never constructs `_RecordingSpanProcessor` |
| `test_seam_off_adds_no_recording_processor_to_an_existing_provider` | unit | guard-deletion | the reuse-provider branch never constructs it |
| `test_header_seam_masks_sensitive_values_and_keeps_names` | unit | error / privacy | `last_otel_headers()` keeps `authorization` but masks its value |
| `test_exporter_still_holds_the_real_authorization_header` | integration | happy | the configured OTLP exporter still carries the bearer value |
| `test_recording_payload_list_is_bounded` | unit | edge / resource | fewer than 4,000 records after 4,000 spans |
| `test_recording_transport_is_deleted` | unit | guard-deletion | `_RecordingTransport` does not exist |

`tests/tracing/exporters/test_otlp_pipeline.py::test_otel_sink_exports_to_arbitrary_endpoint_and_headers`
is **edited** to assert the masked module global and the exporter's real header
instead of pinning the bearer value in the global.

### Seam fixtures (AR-D10 / AR-D13)

| File | Fixture | Effect |
| --- | --- | --- |
| `tests/tracing/conftest.py` | `_enable_recording_seam` (autouse) | sets `_RECORDING_SEAM_ENABLED = True`; module-overridable to opt out |
| `tests/enterprise/conftest.py` | `_enable_recording_seam` (autouse) | same |

No `tests/conftest.py` edit.

## xfail schedule

**None.** Every new test is a real assertion against a locked contract; none is
marked `xfail`. `pytest.importorskip("opentelemetry")` guards the tests that
need the optional `[tracing]` extra (U7 enabled paths, U8 provider paths), per
existing convention.

## RED status at AR1 (post-#836 tree, baseline `1295 passed`)

| File | Red | Green pins (must stay green) |
| --- | --- | --- |
| `tests/agents/test_agent_stderr_drain.py` | 13 | — |
| `tests/agents/test_opencode_boot_bounds.py` | 5 | `test_boot_keeps_its_synchronous_signature` |
| `tests/agents/test_opencode_prompt_fallback.py` | 7 | 404/405 fallback ×2 |
| `tests/agents/test_claude_review_tool_boundary.py` | 4 | exec-tools ×2, agent-definitions |
| `tests/agents/test_gemini_review_tool_boundary.py` | 2 | MCP exclusions, `-y` ×2 |
| `tests/tracing/test_tracer_enterprise_binding.py` | 6 | — |
| `tests/tracing/exporters/test_recording_seam_test_only.py` | 5 | exporter real-header |
| `tests/tracing/exporters/test_otlp_pipeline.py` | 1 (edited) | the rest of the file |

Each RED is an assertion/fixture failure on the stated contract, never a
collection or import error.

## Verification

- `make lint` — clean (ruff check + format, loguru-only, cheat-signatures, type-ignore reasons).
- `make typecheck` — clean.
- `uv run --extra tracing pytest --collect-only -q <new files>` — collects with no errors.
- New tests run RED for the reasons above; existing pins stay green.

## Reconciliation log

- AR1 (2026-09-24): suite authored; no xfails; 7 files added + 2 conftests edited + 1 pin edited.
