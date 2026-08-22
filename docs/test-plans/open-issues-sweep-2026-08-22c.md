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

---

# Batch HB — #434 #435 #438 antislop matcher

Authoring wave: **W3** (HB RED) · Implementation: **W4** (three commits, D2)
GitHub issues: **#434**, **#435**, **#438** — `src/mergecraft/analyzers/antislop/matcher.py`

Moved from `tests/analyzers/test_cov_antislop_matcher_paths.py` (strict xfails from #431)
into `tests/analyzers/test_antislop_matcher_hb.py` with non-strict W4 markers.

## xfail schedule

| Wave | Test | Marker reason | Issue |
|------|------|---------------|-------|
| **W4** | `test_python_except_block_that_only_passes_is_reported` | `green after W4: walk unnamed except_clause children (#434)` | #434 |
| **W4** | `test_python_except_block_returning_none_is_reported` | same | #434 |
| **W4** | `test_non_ascii_above_an_import_must_not_make_a_used_import_phantom` | `green after W4: decode node text like _node_text_from_node (#435)` | #435 |
| **W4** | `test_snippet_after_non_ascii_quotes_real_source_text` | same | #435 |
| **W4** | `test_wrapper_that_binds_a_literal_argument_is_not_a_pass_through` | `green after W4: abort pass-through check on literal positionals (#438)` | #438 |

Never `strict=True` — impl wave drops each xfail in the commit that fixes its issue.

## Contract matrix (#434 / #435 / #438)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| HB434a | `except …: pass` reported on Python | unit | happy | `test_python_except_block_that_only_passes_is_reported` |
| HB434b | `except …: return None` reported on Python | unit | happy | `test_python_except_block_returning_none_is_reported` |
| HB435a | Non-ASCII above import does not phantom a used import | unit | edge | `test_non_ascii_above_an_import_must_not_make_a_used_import_phantom` |
| HB435b | Snippet after non-ASCII is a real source substring | unit | edge | `test_snippet_after_non_ascii_quotes_real_source_text` |
| HB438a | Wrapper binding a literal positional is not pass-through | unit | happy | `test_wrapper_that_binds_a_literal_argument_is_not_a_pass_through` |

## Named symbols W4 must satisfy

| Symbol | Module | Issue | Test |
|--------|--------|-------|------|
| `_python_empty_error_handler_matches` | `mergecraft.analyzers.antislop.matcher` | #434 | HB434a |
| `_python_error_obscuring_catch_matches` | `mergecraft.analyzers.antislop.matcher` | #434 | HB434b |
| `_node_text` | `mergecraft.analyzers.antislop.matcher` | #435 | HB435a, HB435b |
| `_call_positional_argument_names` | `mergecraft.analyzers.antislop.matcher` | #438 | HB438a |

## Collection target (W3)

`tests/analyzers/test_antislop_matcher_hb.py` — **5 tests**, all xfail `strict=False`.

## Acceptance (W3)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- HB434a–HB438a xfail (non-strict)
- No `src/` edits
- Strict xfails removed from `test_cov_antislop_matcher_paths.py`

---

# Batch HC — #423 antislop scopes wiring

Authoring wave: **W5** (HC RED) · Implementation: **W6** (`refactor(analyzers): use antislop.scopes as the shared suffixes`, D3)
GitHub issue: **#423** — `antislop/scopes.py` constants unused

## xfail schedule

| Wave | Test | Marker reason | Issue |
|------|------|---------------|-------|
| **W6** | `test_init_imports_antislop_scoped_suffixes_from_scopes` | `green after W6: import ANTISLOP_SCOPED_SUFFIXES from scopes (#423)` | #423 |
| **W6** | `test_init_does_not_define_local_scoped_suffixes` | `green after W6: delete local _SCOPED_SUFFIXES duplicate (#423)` | #423 |
| **W6** | `test_matcher_imports_antislop_js_suffixes_from_scopes` | `green after W6: import ANTISLOP_JS_SUFFIXES from scopes (#423)` | #423 |
| **W6** | `test_matcher_does_not_define_local_js_suffixes` | `green after W6: delete local _JS_SUFFIXES duplicate (#423)` | #423 |

Never `strict=True` — impl wave drops each xfail in the scopes refactor commit.

## Contract matrix (#423 / D3)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| HC423a | `__init__.py` imports `ANTISLOP_SCOPED_SUFFIXES` from `scopes` | unit | happy | `test_init_imports_antislop_scoped_suffixes_from_scopes` |
| HC423b | `__init__.py` has no local `_SCOPED_SUFFIXES` tuple | unit | policy | `test_init_does_not_define_local_scoped_suffixes` |
| HC423c | `matcher.py` imports `ANTISLOP_JS_SUFFIXES` from `scopes` | unit | happy | `test_matcher_imports_antislop_js_suffixes_from_scopes` |
| HC423d | `matcher.py` has no local `_JS_SUFFIXES` frozenset | unit | policy | `test_matcher_does_not_define_local_js_suffixes` |
| HC423e | `scopes.py` exports canonical suffix constants | unit | happy | `test_scopes_module_exports_shared_suffix_constants` |
| HC423f | Every scoped suffix still reaches `scan_changed_files` | integration | regression | `test_every_scoped_suffix_is_scanned` |
| HC423g | Every JS suffix still classifies for matcher rules | integration | regression | `test_every_js_suffix_reaches_matcher` |

## Named symbols W6 must satisfy

| Symbol | Module | Test |
|--------|--------|------|
| `ANTISLOP_SCOPED_SUFFIXES` | `mergecraft.analyzers.antislop.scopes` | HC423a, HC423e, HC423f |
| `ANTISLOP_JS_SUFFIXES` | `mergecraft.analyzers.antislop.scopes` | HC423c, HC423e, HC423g |
| `_is_scoped_path` consumer | `mergecraft.analyzers.antislop.__init__` | HC423a–b, HC423f |
| `_language_for_path` consumer | `mergecraft.analyzers.antislop.matcher` | HC423c–d, HC423g |

`scopes.py` must **not** be deleted (D3).

## Collection target (W5)

`tests/analyzers/test_antislop_scopes_hc.py` — **18 tests** (4 xfail, 14 pass).

## Acceptance (W5)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- HC423a–d xfail (non-strict); HC423e–g pass
- No `src/` edits
