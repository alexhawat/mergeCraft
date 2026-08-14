# Open issues sweep — Batch D test plan (W11 RED)

Wave plan: `.ignorelocal/waves/open-issues-sweep-wave-plan.md`
Worktree: `mergecraft-issues-d-providers` @ `wave/issues-d-providers`

## xfail schedule

| Wave | Test | Marker reason |
|------|------|---------------|
| **W12–W15** | `tests/agents/test_agent_resolve_providers.py::test_resolve_runtime_agent_fail_loud_without_credentials[...]` (×4) | `green after W12-W15: D12 fail-loud resolve_runtime_agent` |
| **W12–W15** | `tests/agents/test_agent_resolve_providers.py::test_resolve_runtime_agent_never_returns_opencode_for_provider_models[...]` (×4) | same |
| **W12** | `tests/agents/test_agent_resolve_providers.py::test_resolve_runtime_agent_selects_codex_with_codex_auth_json` | `green after W12: codex subscription resolve (#10)` |
| **W13** | `tests/agents/test_agent_resolve_providers.py::test_resolve_runtime_agent_selects_codex_with_openai_api_key_only` | `green after W13: OPENAI_API_KEY resolve (#11)` |
| **W14** | `tests/agents/test_agent_resolve_providers.py::test_resolve_runtime_agent_selects_gemini_with_gemini_api_key` | `green after W14: Gemini resolve (#12)` |
| **W15** | `tests/agents/test_agent_resolve_providers.py::test_resolve_runtime_agent_selects_cursor_with_cursor_api_key` | `green after W15: Cursor Cloud resolve (#13)` |
| **W12** | `tests/agents/test_codex.py::test_codex_harness_invokes_cli_and_parses_agent_result` | `green after W12: codex harness contract (#10)` |
| **W14** | `tests/agents/test_gemini.py::test_gemini_harness_invokes_cli_and_parses_agent_result` | `green after W14: Gemini harness contract (#12)` |
| **W15** | `tests/agents/test_cursor.py::test_cursor_harness_launches_cloud_agent_and_parses_agent_result` | `green after W15: Cursor Cloud harness contract (#13)` |

All cross-wave markers use `strict=False`.

## Contract matrix

| Issue | Decision | Layer | Scenario | Primary test |
|-------|----------|-------|----------|--------------|
| **#10–#13** | D12 — fail loud, never fall through to `opencode` | Unit | Error — `codex/*`/`openai/*`/`google/*`/`cursor/*` slug without required credential | `test_agent_resolve_providers.py::test_resolve_runtime_agent_fail_loud_without_credentials` |
| **#10–#13** | D12 | Unit | Error — must not return `opencode` agent silently | `test_agent_resolve_providers.py::test_resolve_runtime_agent_never_returns_opencode_for_provider_models` |
| **#10** | D10 — Codex subscription harness | Unit | Happy path — `CODEX_AUTH_JSON` resolves to `codex` agent | `test_agent_resolve_providers.py::test_resolve_runtime_agent_selects_codex_with_codex_auth_json` |
| **#10** | D10 | Integration | Happy path — fake `codex` CLI + env → argv + `AgentResult` | `test_codex.py::test_codex_harness_invokes_cli_and_parses_agent_result` |
| **#11** | D10 — reuse Codex harness for API key | Unit | Happy path — `OPENAI_API_KEY` only resolves to `codex` | `test_agent_resolve_providers.py::test_resolve_runtime_agent_selects_codex_with_openai_api_key_only` |
| **#12** | D11 — dedicated Gemini harness | Unit | Happy path — `GEMINI_API_KEY` resolves to `gemini` | `test_agent_resolve_providers.py::test_resolve_runtime_agent_selects_gemini_with_gemini_api_key` |
| **#12** | D11 | Integration | Happy path — fake Gemini CLI + env → argv + `AgentResult` | `test_gemini.py::test_gemini_harness_invokes_cli_and_parses_agent_result` |
| **#13** | D9 — Cursor Cloud Phase A only | Unit | Happy path — `CURSOR_API_KEY` resolves to `cursor` | `test_agent_resolve_providers.py::test_resolve_runtime_agent_selects_cursor_with_cursor_api_key` |
| **#13** | D9 | Integration | Happy path — mocked Cloud API → terminal run + dashboard metadata | `test_cursor.py::test_cursor_harness_launches_cloud_agent_and_parses_agent_result` |

## Pinned module surface (for impl waves)

| Module | Expected symbols |
|--------|------------------|
| `mergecraft.agents.codex` | `_run_codex_once`, `agent(name="codex", …)` |
| `mergecraft.agents.gemini` | `_run_gemini_once`, `agent(name="gemini", …)` |
| `mergecraft.agents.cursor` | `_run_cursor_once`, `CursorCloudClient`, `agent(name="cursor", …)` |
| `mergecraft.utils.agent_resolve` | D12 errors naming missing env vars; registry entries for `codex`, `gemini`, `cursor` |

## Implementation notes for impl waves

- **W12:** Add `agents/codex.py`, register in `agents/__init__.py`, wire `resolve_runtime_agent` for `CODEX_AUTH_JSON`; un-xfail codex resolve + codex harness tests; keep shared D12 xfails until W13–W15 land their provider portions.
- **W13:** Extend codex harness for `OPENAI_API_KEY`-only; un-xfail OpenAI API resolve test.
- **W14:** Add `agents/gemini.py`; un-xfail Gemini resolve + harness tests.
- **W15:** Add `agents/cursor.py` with Cloud client (`create_cloud_agent`, `get_run`, `list_artifacts`); un-xfail Cursor resolve + harness tests; remove remaining D12 xfails when all four providers are wired.
