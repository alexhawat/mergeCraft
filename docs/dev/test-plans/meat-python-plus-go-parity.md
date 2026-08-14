# meat_python_plus Go parity — W1 RED test plan

Wave plan: `.ignorelocal/design/plan/meat-python-plus-go-parity-wave-plan.md`
Worktree: `mergecraft-meat-python-plus` @ `feat/meat-python-plus-tokenhub`
Upstream pin: `boldsoftware/meat` @ `f39f41dfe7b5b37a12b35fdfbaecc7e779855bd3`

W1 owns the **RED** suite for W2–W10. Tests collect with zero import/collection
errors; contract assertions are `@pytest.mark.xfail(..., strict=False)` until each
implementation wave lands. Only **test-creator** edits `meat_python_plus/tests/**`.

## xfail schedule

| Wave | Test file(s) | Marker reason prefix |
|------|----------------|----------------------|
| **W2** | `meat_python_plus/tests/test_imports.py` | `green after W2:` — **reconciled 2026-08-11** (xfail removed) |
| **W3** | `meat_python_plus/tests/test_moves.py` | `green after W3:` — **reconciled 2026-08-11** (xfail removed; `nonconstant indentation shift` fixture aligned to Go `moves_test.go` varying indents) |
| **W4** | `meat_python_plus/tests/test_python_suites.py` | `green after W4:` — **reconciled 2026-08-11** (xfail removed; `test_rejects_deleted_table_still_referenced` hunk header `+1,6`→`+1,7` so reference validation runs) |
| **W5** | `meat_python_plus/tests/test_chunk.py` | `green after W5:` — **reconciled 2026-08-11** (xfail removed; 6/6 chunk tests + 46/46 W2–W5 regression green) |
| **W6** | `meat_python_plus/tests/test_openai_responses.py`, `test_resolve_provider.py` (W6 cases) | `green after W6:` — **reconciled 2026-08-11** (xfail removed; 17/17 `test_openai_responses`+W6 resolve cases green) |
| **W7** | `meat_python_plus/tests/test_gateway.py` | `green after W7:` — **reconciled 2026-08-11** (xfail removed; 6/6 gateway + 18/18 with `test_resolve_provider` green) |
| **W8** | `meat_python_plus/tests/test_rubric_hash.py` | `green after W8:` — **reconciled 2026-08-11** (xfail removed; 7/7 `test_rubric_hash` green without `--runxfail`; pin `441f5e6e28ad3add`) |
| **W9** | `meat_python_plus/tests/test_render.py` | `green after W9:` — **reconciled 2026-08-11** (xfail removed; 9/9 `test_render` green without `--runxfail`) |
| **W10** | `meat_python_plus/tests/test_python_golden.py` | `green after W10:` — **reconciled 2026-08-11** (xfail removed; mustContain anchors use Go-indented `+    …` / `+            …` forms; 6/6 golden + 95/95 offline suite green) |

Existing baseline tests (`test_editplan.py`, `test_abridge_offline.py`, `test_numbered_diff.py`,
`test_resolve_provider.py` pre-W6 cases) remain **unmarked** — they pass on the v1 port.

## Contract → test matrix

| # | Contract | Primary tests | Layer | Happy | Edge | Error |
|---|----------|---------------|-------|-------|------|-------|
| **W2** | Mandatory import hide (multiline, embedded fixtures, both sides) | `test_imports.py` | unit | `test_mandatory_imports_by_language[*]` | `test_mandatory_imports_avoid_false_positives` | `test_fold_cannot_cross_mandatory_import_rows` |
| **W2** | Import-only file/hunk dropped | `test_imports.py` | unit | — | `test_mandatory_imports_remove_import_only_file` | — |
| **W3** | Exact move detection | `test_moves.py` | unit | `test_detect_exact_move_cross_file`, `test_detect_exact_move_same_file_cross_hunk` | `test_detect_exact_moves_ignores_ambiguous[*]` | — |
| **W3** | Move symmetry (fold/remove/replace) | `test_moves.py` | unit/integration | `test_move_symmetry_passing_plans[*]` | `test_move_replacement_symmetry_equivalent_elisions` | `test_move_symmetry_failing_plans[*]`, `test_move_replacement_symmetry_one_sided_elision` |
| **W3** | Move hints + abridge rejection | `test_moves.py` | functional | — | `test_plan_feedback_reports_symmetric_moves` | `test_abridge_rejects_asymmetric_move_then_accepts_correction` |
| **W4** | Decorator/owner atomicity | `test_python_suites.py` | unit | `test_allows_multiline_decorator_argument_fold` | — | `test_rejects_detached_decorator` |
| **W4** | Triple-quote / table retention | `test_python_suites.py` | unit | — | `test_preserves_triple_quote_balance` | `test_rejects_deleted_table_still_referenced`, `test_rejects_fold_that_hides_suite_owner` |
| **W5** | Rich splitter (file/hunk/mid-hunk) | `test_chunk.py` | unit | `test_split_diff_packs_whole_file_sections` | `test_split_diff_mid_hunk_preserves_changed_rows` | — |
| **W5** | Origin maps + move remap | `test_chunk.py` | integration | `test_split_diff_preserves_origin_line_maps` | `test_map_moves_to_chunk_includes_both_sides` | `test_abridge_chunked_enforces_whole_diff_moves` |
| **W6** | Responses API URL/defaults/stream | `test_openai_responses.py` | unit | `test_openai_responses_streaming_text` | `test_openai_defaults_match_go_pin` | `test_openai_responses_incomplete_is_error` |
| **W6** | `provider_state` replay E2E | `test_openai_responses.py` | functional | `test_openai_responses_provider_state_replay_round_trip` | — | — |
| **W6** | Resolve: OpenAI→Responses; gateways→chat | `test_resolve_provider.py` | unit | `test_native_openai_selects_responses_api` | — | `test_tokenhub_resolve_stays_chat_completions`, `test_nous_resolve_stays_chat_completions` |
| **W7** | exe.dev discovery | `test_gateway.py` | unit | `test_discover_exe_gateway_base` | `test_discover_exe_gateway_base_team` | `test_discover_exe_gateway_base_no_marker`, `test_discover_exe_gateway_base_no_llm_integration` |
| **W7** | Resolve gateway fallback | `test_gateway.py` | integration | `test_resolve_openai_prefers_explicit_key_over_gateway` | — | `test_resolve_openai_falls_back_to_gateway` |
| **W8** | Full `promptSurface()` RubricHash | `test_rubric_hash.py` | unit | `test_rubric_hash_format` | `test_surface_fixtures_cover_move_branches` | `test_prompt_surface_excludes_compiler_internal_vocabulary` |
| **W8** | Pinned hash + cache key | `test_rubric_hash.py` | unit/integration | `test_rubric_hash_pinned_go_surface` | `test_rubric_hash_changes_when_tool_schema_changes` | `test_cache_key_includes_full_rubric_surface` |
| **W9** | Plain vs color render | `test_render.py` | unit | `test_format_body_plain`, `test_palette_disabled_is_all_plain` | `test_colorize_diff_line_slots` | — |
| **W9** | TTY + pager + `-json` wire | `test_render.py` | functional | `test_render_json_wire` | `test_is_terminal_regular_file` | `test_render_invokes_pager_when_tty` |
| **W10** | Golden plan→diff parity | `test_python_golden.py` | integration | `test_python_golden_plan_matches_snapshot[*]` | `test_python_golden_pytest_move_and_anchors` | `test_python_golden_rejects_asymmetric_move_mutation` |

Shared fixtures: `meat_python_plus/tests/fixtures/go_parity.py` (`EXACT_MOVE_DIFF`, Go defaults, golden bases).

## Named deliverable symbol coverage

| Symbol (target module) | Test reference |
|------------------------|----------------|
| `imports.mandatory_import_removal_plan` | `test_imports.py` |
| `moves.detected_moves_in_diff` | `test_moves.py`, `test_rubric_hash.py`, `test_python_golden.py` |
| `editplan.detect_exact_moves` / symmetry via `compile_edit_plan` | `test_moves.py` |
| `chunk.split_diff_for_abridging` / `map_moves_to_chunk` / chunk origins | `test_chunk.py` |
| `providers.openai_responses.OpenAIResponsesModel` | `test_openai_responses.py` |
| `providers.openai_responses.openai_responses_url` | `test_openai_responses.py` |
| `providers.resolve.resolve_provider` (Responses vs chat) | `test_resolve_provider.py`, `test_gateway.py` |
| `providers.gateway.discover_exe_gateway_base` | `test_gateway.py` |
| `prompt_surface.prompt_surface` / pinned `rubric_hash` | `test_rubric_hash.py` |
| `render.format_body`, `render.render_json`, `tty.is_terminal` | `test_render.py` |
| Golden `testdata/python/*` | `test_python_golden.py` |

## Reconciliation plan

After each impl wave W2–W10:

1. Remove `pytest.mark.xfail(reason="green after W<N>: …", strict=False)` from tests that pass.
2. Record the reconciling wave in this file's xfail schedule.
3. Do **not** edit tests from `wave-plan-executor` — request test-creator if a contract looks wrong.

## Notes

- Lazy imports via `meat_python_plus/tests/_parity_helpers.py` (`import_or_fail`) keep collection clean before modules exist; `conftest.py` adds the tests dir to `sys.path`.
- Golden tests skip (not fail) until W10 copies upstream fixtures into `tests/testdata/python/`.
- Live LLM rubric smokes (`MEAT_E2E=1`) are out of scope for W1; port as `@pytest.mark.integration` in W10 optional track if needed.
- Harness `-json` wire (D11) remains covered by existing v1 tests + `test_render.py::test_render_json_wire` (W9).
- **W2 reconciliation:** `test_editplan.py::test_structure_retention_hunk_header` uses `DIFF_NO_MANDATORY_IMPORT` because Go `completeMandatoryImportFraming` collapses hunks whose only retained rows are mandatory-hidden imports (empty diff, not orphaned-header error).
- **W3 reconciliation:** `test_detect_exact_moves_ignores_ambiguous[nonconstant indentation shift]` fixture uses Go-varying added-line indents (`+    first…` / `+        second…` / `+    third…`); uniform `+ {row}` spacing incorrectly expected a move detection.
- **W4 reconciliation:** `test_rejects_deleted_table_still_referenced` hunk header was `+1,6` for seven added lines; compiler rejected before CASES reference guard — corrected to `+1,7`.
- **W5 reconciliation:** Removed all six `green after W5:` xfails from `test_chunk.py`; regression `test_chunk` + `test_imports` + `test_moves` + `test_python_suites` + `test_editplan` = 46 passed.
- **W6 reconciliation:** Removed five `green after W6:` xfails from `test_openai_responses.py` and three from `test_resolve_provider.py` (W6 cases only); 17/17 green without `--runxfail`.
- **W7 reconciliation:** Removed six `green after W7:` xfails from `test_gateway.py`; no W7 xfails remained in `test_resolve_provider.py` (W6 already reconciled); 18/18 green without `--runxfail`.
- **W8 reconciliation:** Removed seven `green after W8:` xfails from `test_rubric_hash.py`; 7/7 green without `--runxfail`; W9/W10 xfails untouched; commit deferred to Final.
- **W9 reconciliation:** Removed nine `green after W9:` xfails from `test_render.py`; 9/9 green without `--runxfail`; W10 xfails untouched; commit deferred to Final.
- **W10 reconciliation:** Removed four `green after W10:` xfails from `test_python_golden.py`; fixed `test_python_golden_pytest_move_and_anchors` mustContain literals to Go-indented golden forms (`+    @contextlib…`, `+            apply_warning_filters…`, `+    result.assert_outcomes…`); offline suite `95 passed` (0 xfail/xpass); commit deferred to Final.
- **Final / D3 polish:** `test_resolve_model_from_env` expects default `resolve_model_name("") == "gpt-5.6-sol"` (Go pin parity); explicit `resolve_provider("gpt-4.1-mini")` routing cases unchanged.
