# Open issues sweep 2026-08-22c — test plan (Batch HA / #421)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-22c-wave-plan.md`
Worktree: `.ignorelocal/worktrees/open-issues-sweep-2026-08-22c` @ `wave/open-issues-sweep-2026-08-22c`
Authoring wave: **W1** (HA RED) · Implementation: **W2** (`fix(tests): isolate MCP server state under xdist`)

GitHub issue: **#421** — flaky MCP tests under parallel `make test`.
Locked decision: **D4** — own server + OS-assigned port per test; reset module-level
registry/token cache; prefer that over `MERGECRAFT_PYTEST_JOBS=0`; `xdist_group`
only if isolation is impossible.

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W2** | `test_reset_mcp_process_state_is_public_api` | `green after W2: MCP xdist isolation (#421)` | pending |
| **W2** | `test_mcp_conftest_autouse_resets_process_state` | same | pending |
| **W2** | `test_start_mcp_http_server_avoids_select_port_release_window` | same | pending |
| **W2** | `test_reset_mcp_process_state_clears_shell_detection_cache` | same | pending |

Never `strict=True` — `xfail_strict = true` in `pyproject.toml`.

### Compatibility pins (pass on baseline `948f26e8`)

| Test | Why it is green today |
|------|------------------------|
| `test_parallel_server_starts_have_unique_ports_and_tokens` | Single-process threaded starts already get distinct ctx tokens; regression guard for W2 |
| `test_flaky_mcp_live_tests_are_not_serialized_with_xdist_group` | D4 policy — flaky surfaces are not yet grouped |
| `test_pair_of_flaky_mcp_tests_survive_repeated_xdist_runs` | Minimal `-n 2` pair often passes; full-suite flake is documented in #421 |

## Contract matrix (#421 / D4)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| HA421a | `reset_mcp_process_state()` is a public reset hook | unit | happy | `test_reset_mcp_process_state_is_public_api` |
| HA421b | `tests/mcp/conftest.py` autouse-calls the reset hook | integration | happy | `test_mcp_conftest_autouse_resets_process_state` |
| HA421c | Port bind avoids `select_port()` release-before-uvicorn TOCTOU | unit | error (today) | `test_start_mcp_http_server_avoids_select_port_release_window` |
| HA421d | Reset clears `mcp.shell` detection caches | unit | edge | `test_reset_mcp_process_state_clears_shell_detection_cache` |
| HA421e | Concurrent starts never share port or bearer secrets | integration | happy | `test_parallel_server_starts_have_unique_ports_and_tokens` |
| HA421f | Flaky live tests are not serialized via `xdist_group` | unit | policy | `test_flaky_mcp_live_tests_are_not_serialized_with_xdist_group` |
| HA421g | #421 reproduction pair survives repeated `-n 2` runs | functional | flake | `test_pair_of_flaky_mcp_tests_survive_repeated_xdist_runs` |

## Named symbols W2 must satisfy

| Symbol | Module | Test |
|--------|--------|------|
| `reset_mcp_process_state()` | `mergecraft.mcp.{process_state,isolation,server}` | HA421a, HA421d |
| autouse MCP reset fixture | `tests/mcp/conftest.py` | HA421b |
| OS-assigned bind without TOCTOU | `mergecraft.mcp.server.start_mcp_http_server` | HA421c |
| Shell cache fields | `mergecraft.mcp.shell._detected_sandbox`, `_detected_netns` | HA421d |

Historically flaky surfaces (issue evidence, not xdist_group):

- `tests/mcp/test_tool_classes.py::test_live_verifier_mcp_lists_class_filtered_tools`
- `tests/mcp/test_mcp_auth_and_port.py::test_orchestrator_and_role_routes_use_distinct_bearer_tokens`

## Collection target (W1)

`tests/mcp/test_xdist_isolation.py` — **7 tests** (4 xfail, 3 pass).

## Acceptance (W1)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- HA421a–d xfail; HA421e–g pass
- No `src/` edits
