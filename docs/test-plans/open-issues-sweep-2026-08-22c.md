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

---

# Batch HD — #436 Gemini/Codex span token attrs

Authoring wave: **W7** (HD RED) · Implementation: **W8** (`fix(tracing): record Gemini and Codex span token usage`, D11)
GitHub issue: **#436** — Gemini and Codex `llm.call` spans always report zero tokens

Moved from `tests/agents/test_cov_gemini_paths.py` (strict xfail from #431)
into `tests/agents/test_provider_span_tokens_hd.py` with non-strict W8 markers.

## xfail schedule

| Wave | Test | Marker reason | Issue |
|------|------|---------------|-------|
| **W8** | `test_result_event_usage_reaches_the_llm_span_token_attrs` | `green after W8: fold Gemini result usage into open_pair_bookkeeping (#436)` | #436 |
| **W8** | `test_result_event_partial_usage_stamps_zero_for_missing_output_tokens` | same | #436 |
| **W8** | `test_turn_completed_usage_reaches_the_llm_span_token_attrs` | `green after W8: fold Codex turn.completed usage into open_pair_bookkeeping (#436)` | #436 |
| **W8** | `test_turn_completed_partial_usage_stamps_zero_for_missing_output_tokens` | same | #436 |

Never `strict=True` — impl wave drops each xfail in the tracing fix commit.

## Contract matrix (#436 / D11)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| HD436a | Gemini ``result`` usage reaches ``llm.call`` token attrs | unit | happy | `test_result_event_usage_reaches_the_llm_span_token_attrs` |
| HD436b | Gemini partial usage omits invented output counts | unit | edge | `test_result_event_partial_usage_stamps_zero_for_missing_output_tokens` |
| HD436c | Codex ``turn.completed`` usage reaches ``llm.call`` token attrs | unit | happy | `test_turn_completed_usage_reaches_the_llm_span_token_attrs` |
| HD436d | Codex partial usage omits invented output counts | unit | edge | `test_turn_completed_partial_usage_stamps_zero_for_missing_output_tokens` |
| HD436e | ``AgentUsage`` path already correct for Gemini | unit | regression | `test_gemini_result_usage_still_reaches_agent_usage_while_span_attrs_are_zero` |
| HD436f | ``AgentUsage`` path already correct for Codex | unit | regression | `test_codex_turn_completed_usage_still_reaches_agent_usage_while_span_attrs_are_zero` |

## Named symbols W8 must satisfy

| Symbol | Module | Test |
|--------|--------|------|
| `_gemini_stream_event_handler` ``result`` branch | `mergecraft.agents.gemini` | HD436a–b, HD436e |
| `_codex_stream_event_handler` ``turn.completed`` branch | `mergecraft.agents.codex` | HD436c–f |
| `open_pair_bookkeeping` fold-before-stamp | `mergecraft.agents.{gemini,codex}` | HD436a–d |

Claude path is the precedent (D11); do not rewrite the span stack.

## Collection target (W7)

`tests/agents/test_provider_span_tokens_hd.py` — **6 tests** (4 xfail, 2 pass).

## Acceptance (W7)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- HD436a–d xfail (non-strict); HD436e–f pass
- Strict xfail removed from `test_cov_gemini_paths.py`
- No `src/` edits

---

# Batch HE — #437 auth partial local write

Authoring wave: **W9** (HE RED) · Implementation: **W10** (`fix(cli): report partial local auth writes honestly`)
GitHub issue: **#437** — `auth --scope local` claims nothing was written after a partial write

Moved from `tests/cli/test_cov_auth_cmd_paths.py` (strict xfail from #431)
into `tests/cli/test_auth_partial_write_he.py` with non-strict W10 markers.

## xfail schedule

| Wave | Test | Marker reason | Issue |
|------|------|---------------|-------|
| **W10** | `test_partial_local_write_must_not_claim_that_nothing_was_written` | `green after W10: report partial local auth writes honestly (#437)` | #437 |
| **W10** | `test_partial_local_write_must_not_name_actions_secret_in_stderr` | same | #437 |
| **W10** | `test_partial_local_write_reports_which_local_keys_landed` | same | #437 |
| **W10** | `test_partial_local_write_token_landed_when_project_write_fails` | same | #437 |
| **W10** | `test_auth_logfire_scope_local_partial_write_is_honest` | same | #437 |

Never `strict=True` — impl wave drops each xfail in the auth fix commit.

## Contract matrix (#437)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| HE437a | Partial local write is not reported as "nothing was written" | unit | edge | `test_partial_local_write_must_not_claim_that_nothing_was_written` |
| HE437b | Local-only failure stderr must not name Actions secret `LOGFIRE_TOKEN` | unit | error | `test_partial_local_write_must_not_name_actions_secret_in_stderr` |
| HE437c | Mixed local result reports which env keys landed | unit | happy | `test_partial_local_write_reports_which_local_keys_landed` |
| HE437d | Reverse partial (token lands, project fails) is also honest | unit | edge | `test_partial_local_write_token_landed_when_project_write_fails` |
| HE437e | `auth logfire --scope local` CLI path matches unit contract | functional | integration | `test_auth_logfire_scope_local_partial_write_is_honest` |
| HE437f | Total local failure may still use "nothing was written" | unit | regression | `test_total_local_failure_may_still_report_nothing_was_written` |

## Named symbols W10 must satisfy

| Symbol | Module | Test |
|--------|--------|------|
| `_persist_credential` local branch | `mergecraft.cli.auth_cmd` | HE437a–f |
| `auth_logfire` → `_persist_credential` | `mergecraft.cli.auth_cmd` | HE437e |

`--scope both` already tolerates local-success/github-failure; local-only must be at least as honest (#437).

## Collection target (W9)

`tests/cli/test_auth_partial_write_he.py` — **6 tests** (5 xfail, 1 pass).

## Acceptance (W9)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- HE437a–e xfail (non-strict); HE437f pass
- Strict xfail removed from `test_cov_auth_cmd_paths.py`
- No `src/` edits

---

# Batch HF — #425 called-workflow permissions lint

Authoring wave: **W11** (HF RED) · Implementation: **W12** (`ci: lint called-workflow permissions on uses jobs`, D5)
GitHub issue: **#425** — nothing detects a workflow that fails at startup

Locked decision **D5** part 1: lint in `make lint` that every ``uses:`` job grants at
least the permissions its called workflow declares. Part 2 (branch-protection
operator note) is W12 docs only — not test-covered here. Do not re-fix
``ci-cd.yml`` ``e2e-gate`` permissions (shipped in #424).

## xfail schedule

| Wave | Test | Marker reason | Issue |
|------|------|---------------|-------|
| **W12** | `test_empty_job_permissions_fail_when_callee_needs_contents_read` | `green after W12: called-workflow permissions lint (#425)` | #425 |
| **W12** | `test_offense_names_caller_job_and_missing_scope` | same | #425 |
| **W12** | `test_sufficient_job_permissions_pass` | same | #425 |
| **W12** | `test_workflow_level_permissions_satisfy_callee` | same | #425 |
| **W12** | `test_partial_job_permissions_fail_when_callee_needs_more` | same | #425 |
| **W12** | `test_third_party_uses_are_out_of_scope` | same | #425 |
| **W12** | `test_main_fails_on_under_permissioned_uses_job` | same | #425 |
| **W12** | `test_main_passes_when_only_good_fixtures_remain` | same | #425 |
| **W12** | `test_repo_workflows_pass_called_workflow_permissions_lint` | same | #425 |
| **W12** | `test_makefile_lint_invokes_called_workflow_permissions_check` | same | #425 |

Never `strict=True` — impl wave drops each xfail in the hygiene-script commit.

`test_e2e_gate_job_grants_contents_read` is a **compatibility pin** (passes on baseline post-#424).

## Contract matrix (#425 / D5)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| HF425a | Empty job ``permissions: {}`` calling callee with ``contents: read`` fails lint | unit | error (#424) | `test_empty_job_permissions_fail_when_callee_needs_contents_read` |
| HF425b | Offense names workflow, job, and missing scope | unit | error | `test_offense_names_caller_job_and_missing_scope` |
| HF425c | Job granting callee's scopes passes | unit | happy | `test_sufficient_job_permissions_pass` |
| HF425d | Workflow-level permissions satisfy callee when job omits block | unit | happy | `test_workflow_level_permissions_satisfy_callee` |
| HF425e | Partial job permissions fail when callee needs more scopes | unit | edge | `test_partial_job_permissions_fail_when_callee_needs_more` |
| HF425f | Third-party ``uses:`` (``actions/*``) are not checked | unit | policy | `test_third_party_uses_are_out_of_scope` |
| HF425g | ``main()`` exits non-zero on offense / zero on clean tree | integration | happy/error | `test_main_fails_on_under_permissioned_uses_job`, `test_main_passes_when_only_good_fixtures_remain` |
| HF425h | Real ``.github/workflows/`` tree passes (post-#424) | integration | regression | `test_repo_workflows_pass_called_workflow_permissions_lint` |
| HF425i | ``e2e-gate`` still declares ``contents: read`` | integration | anchor | `test_e2e_gate_job_grants_contents_read` |
| HF425j | ``make lint`` invokes the new script | integration | policy | `test_makefile_lint_invokes_called_workflow_permissions_check` |

## Named symbols W12 must satisfy

| Symbol | Module | Test |
|--------|--------|------|
| `scan_workflows(root)` | `scripts/check_called_workflow_permissions.py` | HF425a–f, HF425h |
| `main()` | `scripts/check_called_workflow_permissions.py` | HF425g |
| offense record (`job`, `workflow`, `missing`) | `scripts/check_called_workflow_permissions.py` | HF425b |
| `make lint` wiring | `Makefile` | HF425j |

Fixture workflows live under ``tests/ci/fixtures/workflow_permissions_hf/``.

## Collection target (W11)

`tests/ci/test_called_workflow_permissions_hf.py` — **16 tests** (10 xfail, 6 pass).

## Acceptance (W11)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- HF425a–j xfail (non-strict); fixture anchor tests pass
- No `src/` or `scripts/` edits

---

# Batch HG — #433 review gate vs Codex fallback

Authoring wave: **W13** (HG RED) · Implementation: **W14** (`fix(ci): wait for Codex fallback before the approval gate`, D9)
GitHub issue: **#433** — review gate fails PRs that mergeCraft approved via fallback

Locked decision **D9**: gate step must not run until every review attempt in that
workflow (including Codex fallback) has finished. Fail-closed stays; do not weaken
the check.

## xfail schedule

| Wave | Test | Marker reason | Issue |
|------|------|---------------|-------|
| **W14** | `test_mergecraft_yml_gate_waits_for_every_review_attempt` | `green after W14: gate waits for Codex fallback (#433)` | #433 |
| **W14** | `test_mergecraft_yml_approval_gate_is_not_in_review_job` | same | #433 |
| **W14** | `test_repo_mergecraft_workflow_passes_gate_ordering_scan` | same | #433 |

Never `strict=True` — impl wave drops each xfail in the workflow ordering commit.

## Contract matrix (#433 / D9)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| HG433a | Same-job gate after Codex fallback is flagged | unit | error (#433) | `test_same_job_gate_is_flagged` |
| HG433b | Gate job missing ``needs: codex-fallback`` is flagged | unit | error | `test_split_jobs_missing_fallback_needs_is_flagged` |
| HG433c | Gate job ``needs:`` every attempt job passes | unit | happy | `test_gate_needs_all_attempt_jobs_passes` |
| HG433d | Gate job ``needs:`` combined attempts job passes | unit | happy | `test_combined_attempts_job_passes` |
| HG433e | Fixture scan flags racing workflows | integration | error | `test_scan_flags_racing_fixtures` |
| HG433f | Fixture scan passes correct ordering | integration | happy | `test_scan_passes_correct_ordering_fixtures` |
| HG433g | ``mergecraft.yml`` still declares Nous + Codex attempts | integration | anchor | `test_review_job_still_declares_nous_and_codex_attempts` |
| HG433h | Fail-closed gate step text preserved | integration | policy | `test_gate_step_still_fails_closed_on_missing_check` |
| HG433i | Real ``mergecraft.yml`` satisfies gate ordering | integration | regression | `test_mergecraft_yml_gate_waits_for_every_review_attempt` |
| HG433j | Approval gate is not colocated in ``review`` job | integration | regression | `test_mergecraft_yml_approval_gate_is_not_in_review_job` |
| HG433k | Repo scan passes for ``mergecraft.yml`` | integration | regression | `test_repo_mergecraft_workflow_passes_gate_ordering_scan` |

## Named symbols W14 must satisfy

| Symbol | Location | Test |
|--------|----------|------|
| Approval gate step | `.github/workflows/mergecraft.yml` | HG433h–k |
| Codex fallback step | `.github/workflows/mergecraft.yml` | HG433g |
| Gate job ``needs:`` review-attempts job(s) | `.github/workflows/mergecraft.yml` | HG433i–k |
| ``gate_job_needs_attempt_jobs`` | `tests/ci/review_gate_ordering.py` | HG433a–d |

Fixture workflows live under ``tests/ci/fixtures/workflow_review_gate_hg/``.

## Collection target (W13)

`tests/ci/test_review_gate_fallback_hg.py` — **16 tests** (3 xfail, 13 pass).

## Acceptance (W13)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- HG433i–k xfail (non-strict); HG433a–h pass
- No `src/` or `.github/workflows/` edits

---

# Batch HH — #431 coverage 82%

Authoring wave: **W15** (HH RED) · Implementation: **W16** (`test: raise coverage floor to 82%`, D7)
GitHub issue: **#431** — raise line coverage to 82% and gate it on PRs

Locked decision **D7**: floor becomes 82%; behaviour tests must catch real defects;
``harbor/agent.py`` import-only padding forbidden; no line-touching tests (D6).

## xfail schedule

| Wave | Test | Marker reason | Issue |
|------|------|---------------|-------|
| **W16** | `test_repo_coverage_report_passes_floor_check_at_target` | `green after W16: measured repo coverage ≥ 82% (#431)` | #431 |

Never `strict=True` — W16 drops the xfail when measured coverage and ``fail_under`` land.

## Contract matrix (#431 / D7)

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| HH431a | ``pyproject.toml`` ``fail_under`` is 82 | unit | policy | `test_pyproject_fail_under_is_eighty_two` |
| HH431b | ``coverage_config`` tracks the 82% floor | unit | policy | `test_coverage_config_fail_under_matches_target` |
| HH431c | ``check_coverage_floors`` rejects below live floor | unit | error | `test_check_coverage_floors_rejects_measured_below_target` |
| HH431d | ``check_coverage_floors`` accepts at contract floor | unit | happy | `test_check_coverage_floors_accepts_measured_at_target` |
| HH431e | Repo ``coverage.json`` passes floor at 82% | integration | regression | `test_repo_coverage_report_passes_floor_check_at_target` |
| HH431f | ``detect_codex_refresh`` classifies rotation shapes | unit | happy/edge | `test_detect_codex_refresh_*` |
| HH431g | ``action.post.main`` skips malformed / unchanged state | unit | edge | `test_main_skips_*` |
| HH431h | Rotated refresh persists via ``gh secret set`` | unit | happy | `test_main_persists_rotated_refresh_via_gh_secret_set` |
| HH431i | ``gh secret set`` failure is non-fatal | unit | error | `test_main_warns_when_gh_secret_set_fails` |
| HH431j | ``_resolve_patch_path`` resolves task patches | unit | happy/edge | `test_resolve_patch_path_prefers_known_candidates` |
| HH431k | Harbor agent parses version + ingests findings | unit | happy | `test_parse_version_*`, `test_populate_context_post_run_*` |
| HH431l | ``_build_run_env`` prefers explicit model name | unit | happy | `test_build_run_env_prefers_explicit_model_name` |

## Named symbols W16 must satisfy

| Symbol | Module | Test |
|--------|--------|------|
| ``fail_under = 82`` | `pyproject.toml` | HH431a–b |
| measured line coverage ≥ 82% | `make coverage-gate` | HH431e |
| Codex post-hook branches | `mergecraft.action.post` | HH431f–i |
| Harbor review agent helpers | `mergecraft.harbor.agent` | HH431j–l |

Harbor behaviour tests require ``uv sync --extra harbor``; skipped when the optional
extra is absent.

## Collection target (W15)

- `tests/ci/test_coverage_hh.py` — **6 tests** (1 xfail, 2 RED fail_under pins, 3 pass)
- `tests/action/test_post_hh.py` — **11 tests** (all pass)
- `tests/harbor/test_harbor_agent_hh.py` — **10 tests** (all pass when harbor extra present)

**25 tests** total.

## Acceptance (W15)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- HH431a–b RED (fail_under still 80); HH431e xfail; behaviour tests pass
- No `src/` edits
