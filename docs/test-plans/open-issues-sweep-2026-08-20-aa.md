# Open issues sweep 2026-08-20 — Batch AA test plan (#345, #346)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-2026-08-20` @ `wave/open-issues-sweep-2026-08-20`
Authoring wave: **W1** (Batch AA RED) · Implementation: **W2** (#345) · **W3** (#346)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W2** | `test_reviewer_serve_rejects_unauthenticated_tools_list` | `green after W2: mcp serve Bearer auth` | pending — **FAIL** (unauth returns 200) |
| **W2** | `test_reviewer_serve_rejects_unauthenticated_tools_call` | `green after W2: mcp serve Bearer auth` | pending — **FAIL** |
| **W3** | `test_gemini_write_mcp_config_includes_bearer_when_token_set` | `green after W3: gemini/opencode/cursor Bearer pins` | pending — likely **XPASS** (helper wired) |
| **W3** | `test_gemini_write_mcp_config_omits_bearer_when_token_empty` | `green after W3: gemini/opencode/cursor Bearer pins` | pending — likely **XPASS** |
| **W3** | `test_opencode_build_security_config_includes_bearer_when_token_set` | `green after W3: gemini/opencode/cursor Bearer pins` | pending — likely **XPASS** |
| **W3** | `test_opencode_build_security_config_omits_headers_when_token_empty` | `green after W3: gemini/opencode/cursor Bearer pins` | pending — likely **XPASS** |
| **W3** | `test_cursor_build_mcp_servers_includes_bearer_when_token_set` | `green after W3: gemini/opencode/cursor Bearer pins` | pending — likely **XPASS** |
| **W3** | `test_cursor_build_mcp_servers_omits_headers_when_token_empty` | `green after W3: gemini/opencode/cursor Bearer pins` | pending — likely **XPASS** |

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| AA345a | `build_mcp_app_for_role(role="reviewer")` rejects unauthenticated `tools/list` | functional | error — no Bearer | `tests/cli/test_mcp_serve_bearer_auth.py::test_reviewer_serve_rejects_unauthenticated_tools_list` |
| AA345b | Reviewer `tools/call` on write tool rejected without Bearer | functional | error — write surface | `tests/cli/test_mcp_serve_bearer_auth.py::test_reviewer_serve_rejects_unauthenticated_tools_call` |
| AA346a | Gemini `write_mcp_config` emits `Authorization: Bearer` when token set | unit | happy | `tests/agents/test_harness_mcp_bearer_pins.py::test_gemini_write_mcp_config_includes_bearer_when_token_set` |
| AA346b | Gemini omits Authorization when token empty | unit | edge — empty token | `test_gemini_write_mcp_config_omits_bearer_when_token_empty` |
| AA346c | OpenCode `build_security_config` emits Bearer headers when token set | unit | happy | `test_opencode_build_security_config_includes_bearer_when_token_set` |
| AA346d | OpenCode omits MCP `headers` block when token empty | unit | edge — empty token | `test_opencode_build_security_config_omits_headers_when_token_empty` |
| AA346e | Cursor `_build_mcp_servers` emits Bearer for cloud-reachable URL | unit | happy | `test_cursor_build_mcp_servers_includes_bearer_when_token_set` |
| AA346f | Cursor omits MCP `headers` when token empty | unit | edge — empty token | `test_cursor_build_mcp_servers_omits_headers_when_token_empty` |

## W1 notes

- **#345 RED:** Live `build_mcp_app_for_role` calls `create_mcp_app(...)` without `auth_token` (`cli/mcp_serve.py`). Unauthenticated reviewer RPC returns HTTP 200 today.
- **#346 pins:** Codex Bearer coverage lives in `tests/agents/test_codex_mcp_unix_socket.py`. Batch AA adds parallel pins for Gemini / OpenCode / Cursor. Harness helpers (`mcp_auth_headers`) may already satisfy the contract — W3 reconciles xfails.
- **D9 token shape:** Per-serve secret minted at serve time; `Authorization: Bearer <token>` on harness MCP calls; stderr token print is W2 scope (not asserted here).
- Cursor tests use a non-loopback URL so `_build_mcp_servers` does not drop MCP for cloud-unreachable loopback.

## Acceptance (W1)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- #345 tests xfail (**FAIL**); #346 tests xfail (may **XPASS** until W3 un-xfail)
- No `src/` edits; no D6 paths
