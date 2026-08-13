# Open issues sweep — Batch B test plan (W5 RED)

Wave plan: `.ignorelocal/waves/open-issues-sweep-wave-plan.md`
Worktree: `mergecraft-issues-b-review-signal` @ `wave/issues-b-review-signal`

## xfail schedule

| Wave | Test | Marker reason |
|------|------|---------------|
| **W6** | `tests/utils/test_learnings_persist.py::test_persist_learnings_warns_ephemeral_and_surfaces_delta` | `green after W6: ephemeral learnings warning + review delta (#7)` |
| **W7** | `tests/mcp/test_check_runs.py::test_list_check_runs_returns_check_suite_data_for_ref` | `green after W7: list_check_runs MCP tool (#8)` |
| **W7** | `tests/mcp/test_check_runs.py::test_get_check_suite_tool_returns_suite_detail` | `green after W7: get_check_suite MCP tool detail path (#8)` |
| **W7** | `tests/mcp/test_static_checks.py::test_static_checks_declared_but_cannot_run_when_shell_disabled` | `green after W7: declared-but-cannot-run when shell disabled (#8)` |

All cross-wave markers use `strict=False`.

## Contract matrix

| Issue | Decision | Layer | Scenario | Primary test |
|-------|----------|-------|----------|--------------|
| **#7** | D7 — warn loudly + PR-comment delta; no Contents-API auto-commit | Unit | Happy path N/A (ephemeral runner is the defect path) | — |
| **#7** | D7 | Unit | Edge — `GITHUB_WORKSPACE` temp dir, learnings changed from seed | `test_learnings_persist.py::test_persist_learnings_warns_ephemeral_and_surfaces_delta` |
| **#7** | D7 | Unit | Error — no `logger.info` success for ephemeral write | same |
| **#7** | D7 | Integration | Functional — `tool_state.learnings_review_delta` carries before→after delta for review/PR comment path | same |
| **#8** | D8 — affordable substitute only | Integration | Happy path — `list_check_runs` for a ref returns suite rows via `list_check_suites_for_ref` | `test_check_runs.py::test_list_check_runs_returns_check_suite_data_for_ref` |
| **#8** | D8 | Integration | Happy path — optional `get_check_suite` detail by id | `test_check_runs.py::test_get_check_suite_tool_returns_suite_detail` |
| **#8** | D8 | Integration | Error — `staticChecks` configured, `shell == "disabled"` → explicit `"declared but cannot run"` (not silent omission) | `test_static_checks.py::test_static_checks_declared_but_cannot_run_when_shell_disabled` |

## Implementation notes for impl waves

- **W6:** Replace info-level persist success with warning about ephemeral runner; set `tool_state.learnings_review_delta` (or equivalent) when only workspace-local path exists; un-xfail `test_learnings_persist.py` only.
- **W7:** Add `mergecraft.mcp.check_runs` with `list_check_runs_tool` (and `get_check_suite_tool` if split); wire into `build_common_tools`; teach `run_static_checks` / `plan_checks` to emit explicit declared-but-cannot-run rows when shell is disabled; un-xfail all `#8` tests only.
