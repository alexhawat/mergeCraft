# Public MCP product — MP1 test plan

Maps **MP1 RED** contracts for the public MCP product wave to the test suite.
Source plan: `.ignorelocal/waves/09-public-mcp-product-wave-plan.md`.

## Locked public surface (W0 / D-table)

| Decision | Contract pinned by MP1 |
| --- | --- |
| D2 | Runtime roles unchanged; new `ServeRole` `"public"` at `/mcp/public` |
| D3 | Exactly six tools: `review_change`, `get_review`, `inspect_finding`, `explain_finding`, `get_capabilities`, `get_policy` |
| D5 | Dedicated `build_public_tools(ctx)` — not a filtered orchestrator list |
| D6 | Default `mcp serve` remains `reviewer`; public is `--role public` |
| D7 | HTTP Bearer required; stdio public has no Bearer |
| D8–D11 | Tool I/O contracts over `CompletedReview` + `capabilities_manifest()` + read-only `get_policy` |
| D12 | `--transport stdio` requires `--role public`; non-public stdio exits 2 |
| D13–D15 | Generated repo-root `server.json`; `make mcp-server-json-check` in `CI_STEPS` |
| D16 | In-process HTTP `TestClient`; stdio subprocess fixture — no vendor CLIs |
| D17 | Offline eval corpus under `evals/mcp-public/` |
| D18–D19 | Generated `docs/mcp-tools.md`; consumer `docs/mcp.md` install copy |
| D22 | `mcp list --role public` prints six sorted names only |

## MP1.1 — public role (MP2)

| Contract | Tests | Layer |
| --- | --- | --- |
| Public list is D3 closed set, sorted | `tests/cli/test_mcp_public_role.py::test_list_role_public_prints_exactly_six_names` | CLI / functional |
| Reviewer still exposes runtime primitives (A3) | `…::test_list_role_reviewer_still_includes_runtime_primitives` | guard |
| `public` accepted; typo `pubic` rejected | `…::test_unknown_role_rejected` | CLI / error |
| Public mount rejects `push_branch` | `tests/mcp/test_public_profile.py::test_public_mount_does_not_expose_push_branch` | HTTP integration |
| Reviewer mount unchanged | `…::test_reviewer_mount_still_has_create_pull_request_review` | guard |
| Unknown agents never route to `/mcp/public` | `…::test_mcp_role_url_does_not_route_unknown_agents_to_public` | unit |

## MP1.2 — six tools (MP2)

| Contract | Tests | Layer |
| --- | --- | --- |
| `review_change` persists `CompletedReview` | `tests/mcp/test_public_tools.py::test_review_change_persists_completed_review` | integration |
| Findings carry `MC-` short ids | `…::test_review_change_returns_short_ids` | integration |
| `get_review` round-trips store | `…::test_get_review_round_trips_completed_store` | integration |
| `inspect_finding` accepts short id | `…::test_inspect_finding_accepts_short_id` | integration |
| `explain_finding` keys match CLI explain | `…::test_explain_finding_matches_cli_explain_payload_keys` | integration |
| `get_capabilities` matches manifest | `…::test_get_capabilities_matches_capabilities_manifest` | integration |
| `get_policy` read-only + trust/policy ids | `…::test_get_policy_is_read_only` | schema + integration |
| Dedicated builder, not orchestrator filter | `…::test_public_tools_are_not_filtered_orchestrator_tools` | unit |

### Pinned public API (MP2)

New module `src/mergecraft/mcp/public.py`:

- `PUBLIC_TOOL_NAMES` — frozenset of D3 names
- `build_public_tools(ctx: ToolContext) -> list[ToolSpec]`
- Six tool executors wired through existing review/completed/capabilities modules

Additive `MCP_PUBLIC_ENDPOINT = "/mcp/public"` in `src/mergecraft/mcp/endpoints.py`.

## MP1.3 — stdio (MP3)

| Contract | Tests | Layer |
| --- | --- | --- |
| stdio public answers `tools/list` | `tests/mcp/test_public_stdio.py::test_stdio_public_lists_six_tools` | subprocess E2E |
| stdio needs no Bearer | `…::test_stdio_does_not_require_bearer` | subprocess E2E |
| stdio + non-public role exits 2 | `…::test_stdio_non_public_role_is_usage_error` | CLI / error |
| HTTP public still requires Bearer | `…::test_http_public_still_requires_bearer` | HTTP regression |

## MP1.4 — server.json (MP4)

| Contract | Tests | Layer |
| --- | --- | --- |
| `server.json` exists + schema-valid | `tests/mcp/test_server_json.py::test_server_json_exists_and_matches_schema` | functional |
| Registry name | `…::test_server_json_name_is_io_github_alexhawat_mergecraft` | unit |
| PyPI `merge-craft` stdio public command | `…::test_server_json_package_is_pypi_merge_craft_stdio_public` | unit |
| No runtime tool advertisement | `…::test_server_json_does_not_advertise_runtime_tool_names` | unit |
| `mcp-server-json-check` in `CI_STEPS` | `…::test_make_mcp_server_json_check_in_ci_steps` | policy |
| Generator `--check` catches drift | `…::test_generator_check_detects_drift` | functional |

Schema snapshot: `tests/fixtures/mcp/server.schema.2025-12-11.json` (offline CI).

## MP1.5 — protocol (MP5)

| Contract | Tests | Layer |
| --- | --- | --- |
| initialize → tools/list | `tests/mcp/test_public_protocol.py::test_initialize_then_tools_list` | HTTP integration |
| Unauthenticated tools/list rejected | `…::test_unauthenticated_http_tools_list_rejected` | HTTP / auth |
| Authenticated `get_capabilities` call | `…::test_authenticated_tools_call_get_capabilities` | HTTP integration |
| Unknown tool → JSON-RPC error | `…::test_unknown_tool_jsonrpc_error` | error |
| Missing `inspect_finding` id → schema error | `…::test_schema_error_on_inspect_finding_missing_id` | error |
| Large findings payload stays JSON | `…::test_large_findings_result_is_json` | edge |

## MP1.6 — evals (MP6)

| Contract | Tests | Layer |
| --- | --- | --- |
| Review prompt → `review_change` | `tests/evals/test_mcp_public_tool_selection.py::test_review_this_change_selects_review_change` | offline eval |
| MC- prompt → inspect/explain | `…::test_what_does_mc_abc_mean_selects_inspect_or_explain` | offline eval |
| Reload prompt → `get_review` | `…::test_reload_review_selects_get_review` | offline eval |
| Commit prompt must not pick write tool | `…::test_commit_this_fix_does_not_select_a_write_tool` | jailbreak |
| Forbidden capabilities stay forbidden | `…::test_forbidden_capabilities_remain_forbidden_in_get_capabilities_payload` | jailbreak |

Corpus: `evals/mcp-public/cases.json`. Scorer module: `mergecraft.evals.mcp_public`.

## MP1.7 — docs (MP7)

| Contract | Tests | Layer |
| --- | --- | --- |
| `docs/mcp.md` exists + manifest row | `tests/docs/test_mcp_docs.py::test_mcp_page_exists_and_is_manifested` | docs gate |
| what / connect / never sections | `…::test_mcp_page_answers_three_questions` | docs |
| Separate OpenAI vs Anthropic copy | `…::test_mcp_page_has_separate_openai_and_anthropic_sections` | docs |
| README agent section links `docs/mcp.md` | `…::test_readme_agent_section_links_docs_mcp` | docs |
| Skill documents stdio public + HTTP bearer | `…::test_skill_mentions_stdio_public_and_keeps_runtime_http_bearer` | docs |
| Generated `docs/mcp-tools.md` matches tool names | `…::test_generated_mcp_tools_page_matches_public_tool_names` | docs gate |
| README registry ownership string (D14) | `…::test_readme_has_mcp_name_ownership_string` | docs |

## xfail reconciliation

| Wave greens | Remove xfail from |
| --- | --- |
| MP2 | MP1.1 + MP1.2 tests (except guard tests that never had xfail) |
| MP3 | MP1.3 stdio cases + `test_http_public_still_requires_bearer` if still xfailed |
| MP4 | all `tests/mcp/test_server_json.py` |
| MP5 | all `tests/mcp/test_public_protocol.py` |
| MP6 | all `tests/evals/test_mcp_public_tool_selection.py` |
| MP7 | all `tests/docs/test_mcp_docs.py` |

Guard tests without xfail (should pass on trunk before MP2):

- `test_list_role_reviewer_still_includes_runtime_primitives`
- `test_reviewer_mount_still_has_create_pull_request_review`
- `test_mcp_role_url_does_not_route_unknown_agents_to_public`

## Shared helpers

- `tests/mcp/public_mcp_support.py` — D3 names, git/config fixtures, HTTP + stdio RPC helpers
- `tests/evals/support_mcp_public.py` — lazy import of `mergecraft.evals.mcp_public`
