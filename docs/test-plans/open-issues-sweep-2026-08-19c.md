# Open issues sweep 2026-08-19c — test plan

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-19c-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-19c` @ `wave/open-issues-sweep-2026-08-19c`
Authoring wave: **W11** (Batch O RED — #282 / #283 / D9 / D14 / D15 / D16)

W1 pins #284: PR install lifecycle scripts must not run in the privileged Action
process when the tree is untrusted. Today `start_installation` sets
`PrepOptions.ignore_scripts` from `ctx.payload.shell == "disabled"` only
(`src/mergecraft/mcp/dependencies.py`). Default `shell: restricted` therefore
still runs `postinstall`. W3 greens the RED rows by following D10.

W1.2: `tests/mcp/test_dependencies_python_skip.py` is **not** edited. It asserts
`ignore_scripts is True` under `shell: disabled` (a subset of D10 that stays
true after W3). The old exclusive coupling is pinned in the sibling below.

Batches K–N landed. **W11** authors Batch O RED (#282 / #283 / D9 / D14 / D15 / D16).

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W3** | `test_start_installation_ignore_scripts_follows_d10[untrusted-restricted]` | `green after W3: ignore_scripts follows trust` | greened |
| **W3** | `test_start_installation_ignore_scripts_follows_d10[untrusted-enabled]` | `green after W3: ignore_scripts follows trust` | greened |
| **W3** | `test_start_installation_untrusted_restricted_does_not_run_postinstall` | `green after W3: ignore_scripts follows trust` | greened |
| **W6** | `test_untrusted_restricted_sandbox_none_omits_shell` | `green after W6: untrusted + sandbox none does not register shell` | greened |
| **W8** | `test_harness_mcp_cli_name_fixture_exists` (+ AgentId pins) | `green after W8: harness deny-list CLI name fixtures` | greened |
| **W10** | `test_security_md_does_not_claim_stripping_for_any_mcp_tool` | `green after W10: SECURITY.md residual` | greened |
| **W10** | `test_security_md_limits_stripping_to_agent_env_and_shell` | `green after W10: SECURITY.md residual` | greened |
| **W12** | `test_primary_reviewer_dispatch_url_ends_with_reviewer_endpoint` | `green after W12: role MCP URL dispatch` | pending |
| **W12** | `test_verifier_dispatch_url_ends_with_verifier_endpoint` | `green after W12: role MCP URL dispatch` | pending |
| **W12** | `test_reviewer_role_mcp_post_push_branch_is_not_orchestrator_invocation` | `green after W12: CLI single-role mount` | pending |
| **W12** | `test_verifier_role_mcp_post_push_branch_is_not_orchestrator_invocation` | `green after W12: CLI single-role mount` | pending |
| **W13** | `test_reviewer_tools_list_includes_create_pull_request_review` | `green after W13: primary reviewer publication allow` | pending |
| **W14** | `test_tools_list_and_call_require_per_run_token` | `green after W14: per-run MCP token and unguessable port` | pending |
| **W14** | `test_select_port_is_not_3764_plus_fifty_wide_scan` | `green after W14: per-run MCP token and unguessable port` | pending |
| **W14** | `test_started_server_port_is_loopback_and_not_the_3764_band` | `green after W14: per-run MCP token and unguessable port` | pending |
| **W14** | `test_codex_mcp_config_uses_unix_domain_socket` | `green after W14: per-run MCP token and unguessable port` | pending |
| **W14** | `test_doctor_mcp_probe_does_not_treat_3764_as_the_mcp_port` | `green after W14: per-run MCP token and unguessable port` | pending |

All cross-wave xfails use `strict=False`. Do not use `strict=True` (pytest.ini
has `xfail_strict = true`).

## Contract matrix

### #284 / D10 — `ignore_scripts` follows trust, not only shell

D10 (binding): `ignore_scripts=True` when `trust_tier == "untrusted"` **or**
`shell == "disabled"`. Trusted + `restricted` may still run lifecycle scripts.
Do not change Node/Python prep adapters beyond the flag they already honor.

Fixture: `package.json` with a `postinstall` that writes `SENTINEL`. npm is
stubbed (`shutil.which` + `_run_cmd`) so CI does not need a real Node install;
the stub writes `SENTINEL` unless `--ignore-scripts` is in the npm args.

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| K284a | Untrusted + `restricted` → `PrepOptions.ignore_scripts is True` | unit | happy (bug) | `tests/mcp/test_dependencies_ignore_scripts_trust.py::test_start_installation_ignore_scripts_follows_d10[untrusted-restricted]` |
| K284b | Untrusted + `enabled` → `ignore_scripts is True` | unit | edge (D10 is trust **or** disabled) | `…[untrusted-enabled]` |
| K284c | Untrusted + `disabled` → `ignore_scripts is True` | unit | happy (already true today) | `…[untrusted-disabled]` |
| K284d | Trusted + `disabled` → `ignore_scripts is True` | unit | happy (any `shell == disabled`) | `…[trusted-disabled]` |
| K284e | Trusted + `restricted` → `ignore_scripts is False` | unit | control (maintainer tree) | `…[trusted-restricted]` |
| K284f | Trusted + `enabled` → `ignore_scripts is False` | unit | edge | `…[trusted-enabled]` |
| K284g | Untrusted + `restricted` does not create `SENTINEL` via `start_installation` → `run_prep_phase` | functional | happy (bug) | `test_start_installation_untrusted_restricted_does_not_run_postinstall` |
| K284h | Trusted + `restricted` **may** run `postinstall` (`SENTINEL` created) | functional | control | `test_start_installation_trusted_restricted_may_run_postinstall` |
| K284i | `shell == disabled` skips `postinstall` for both trust tiers | functional | happy + edge | `test_start_installation_shell_disabled_skips_postinstall` |
| K284j | `run_prep_phase(PrepOptions(ignore_scripts=True))` does not create `SENTINEL` | functional | adapter control | `test_run_prep_phase_ignore_scripts_skips_postinstall` |
| K284k | `run_prep_phase(PrepOptions(ignore_scripts=False))` does create `SENTINEL` | functional | adapter control | `test_run_prep_phase_without_ignore_scripts_runs_postinstall` |

K284j/K284k pass against current `src/` — W3 must not break node flag plumbing.

## W1.2 note

Do not loosen `tests/mcp/test_dependencies_python_skip.py`. That file's
`test_start_installation_completes_on_python_policy_skip` still requires
`ignore_scripts is True` when `shell: disabled`. After W3 that remains correct.

## Acceptance (W1)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean
- K284c–f, K284h–k pass today; K284a, K284b, K284g greened in W3
- No `src/` edits; no D6 paths (`mcp/git.py`, `upload.py`, `labels.py`,
  `check_runs.py`, `verdict.py`, `tracing/*`, `cli/diff_review_cmd.py`,
  `analyzers/trust.py`, `mcp/git_guards.py`)

## Batch L — #287 / D11 (W4 RED)

`detect_sandbox_method` returns `"none"` when `CI != "true"`. `build_common_tools`
still registers `shell` / `kill_background` for `shell: restricted`. W6 must not
register those tools when sandbox is `"none"` **and** `trust_tier == "untrusted"`.

Reset `_detected_sandbox` between cases (module global).

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| L287a | `CI` unset / `false` / `0` / empty → `detect_sandbox_method() == "none"` | unit | happy | `tests/mcp/test_shell_sandbox_honesty.py::test_detect_sandbox_method_none_outside_ci` |
| L287b | Cache reset between cases | unit | edge | `test_detect_sandbox_method_cache_resets_between_env` |
| L287c | Untrusted + restricted + `"none"` omits `shell` / `kill_background` | integration | happy (bug) | `test_untrusted_restricted_sandbox_none_omits_shell` |
| L287d | Trusted + restricted + `"none"` still includes `shell` | integration | control | `test_trusted_restricted_sandbox_none_keeps_shell` |

## Batch M — #285 / D13 (W7 RED)

Per harness, `format_mcp_tool_ref(id, "push_branch")` must appear in the rendered
deny list **and** equal a checked-in fixture of the CLI name that harness
documents. Fixture path: `tests/agents/fixtures/harness_mcp_cli_names.json`
(added in W8). Do not spawn a live provider CLI. `tests/agents/test_verifier.py`
formatter checks stay.

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| M285a | Fixture exists | unit | missing-file RED | `tests/agents/test_harness_deny_list_pin.py::test_harness_mcp_cli_name_fixture_exists` (xfail W8) |
| M285b | Each `AgentId` `format_mcp_tool_ref` equals fixture | unit | happy | `test_format_mcp_tool_ref_matches_documented_cli_name` (xfail W8) |
| M285c | Claude `disallowedTools` contains documented `push_branch` | integration | happy | `test_claude_disallowed_tools_use_documented_push_branch_name` (xfail W8) |
| M285d | OpenCode `permission: deny` contains documented `push_branch` | integration | happy | `test_opencode_permission_deny_uses_documented_push_branch_name` (xfail W8) |
| M285e | Gemini `excludeTools` contains documented `push_branch` | integration | happy | `test_gemini_exclude_tools_uses_documented_push_branch_name` (xfail W8) |
| M285f | Codex subagent instructions contain documented `push_branch` | integration | happy | `test_codex_subagent_instructions_use_documented_push_branch_name` (xfail W8) |

## Batch N — #286 / D12 (W9 RED)

`SECURITY.md` (historically lines 24–26) claims `utils/secrets.py` filters
sensitive env vars before they reach **any** shell/MCP tool. D12 restore
path is **off**: `mcp/git.py` `_run_git` still defaults to
`os.environ.copy()`, so the broad sentence is false. W10 rewrites it to
the agent subprocess (`build_agent_env` / `filter_env`) and the sandboxed
`shell` tool (`resolve_env`). Do not claim `git`. Do not edit `mcp/git.py`
(D6).

Sibling of `tests/test_security_parity.py` (that file is runtime permission
parity, not docs wording).

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| N286a | Broad “any shell/MCP tool” / “any MCP tool” / “every MCP tool” / “all MCP tools” is gone (whitespace-normalised) | unit (docs) | happy (bug) | `tests/test_security_md_residual.py::test_security_md_does_not_claim_stripping_for_any_mcp_tool` (xfail W10) |
| N286b | `reach any (shell/)?MCP tool` regex is absent | unit (docs) | edge (line-wrap / slash spacing) | same test |
| N286c | Names `build_agent_env`, `filter_env`, and `resolve_env` | unit (docs) | happy (narrowed replacement) | `test_security_md_limits_stripping_to_agent_env_and_shell` (xfail W10) |
| N286d | Missing `SECURITY.md` fails with a clear assertion | unit (docs) | error | helper `_security_text` inside the xfail tests |
| N286e | `_run_git` source still contains `os.environ.copy()` | unit | control (D12 off; passes today) | `test_run_git_still_defaults_to_os_environ_copy` |

N286e passes against current `src/` — W10 must not restore the broad sentence
and must not edit `git.py`.

## Batch O — #282 / #283 / D9 / D14 / D15 / D16 (W11 RED)

Primary reviewer is still wired to orchestrator `/mcp`. Role routes exist
and are class-filtered; the Action never uses them. `create_pull_request_review`
is `REVIEW_WRITE` + `mutates=True` and is **not** in
`REVIEWER_ALLOWED_TOOL_CLASSES`, so naive `/mcp/reviewer` routing would
stop reviews from publishing. D9 splits primary publication from the
subagent complement. `git` stays on the reviewer surface (still
`REPOSITORY_READ`). `tools/call` / `tools/list` are unauthenticated
loopback. Port allocator is `3764 + randint(0, 49)`. Codex cannot send
`http_headers` (D16 = unix-socket).

Do not invent `http_headers` in Codex tests. `x-mergecraft-agent-id` is
tracing-only, not the credential. Keep morning E `jsonschema.validate` in
`handle_rpc` (D17). Tests only under `tests/mcp/` / `tests/agents/` /
`tests/cli/`.

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| O282a | Primary reviewer `AgentRunContext.mcp_server_url` path is `/mcp/reviewer`, not `/mcp` | functional | happy (bug) | `tests/agents/test_role_dispatch_urls.py::test_primary_reviewer_dispatch_url_ends_with_reviewer_endpoint` (xfail W12) |
| O282b | Verifier dispatch / harness config path is `/mcp/verifier` | integration | happy (bug) | `test_verifier_dispatch_url_ends_with_verifier_endpoint` (xfail W12) |
| O282c | `/mcp/reviewer` `tools/list` includes `create_pull_request_review` + `checkout_pr` | integration | happy (bug) | `tests/mcp/test_reviewer_publication_allow.py::test_reviewer_tools_list_includes_create_pull_request_review` (xfail W13) |
| O282d | `/mcp/reviewer` keeps `git`; excludes `push_branch`, `upload_file`, `delete_branch`, `create_pull_request` | integration | control | `test_reviewer_tools_list_keeps_git_and_excludes_repo_mutations` |
| O282e | `tools/call` `push_branch` on `/mcp/reviewer` is `-32601` | integration | error | `test_reviewer_tools_call_push_branch_errors` |
| O282f | CLI `build_mcp_app_for_role(role="reviewer")` `POST /mcp` `push_branch` is not a successful orchestrator invocation | functional | happy (bug) | `tests/cli/test_mcp_serve_single_role.py::test_reviewer_role_mcp_post_push_branch_is_not_orchestrator_invocation` (xfail W12) |
| O282g | Same single-role mount for `role="verifier"` | functional | edge | `test_verifier_role_mcp_post_push_branch_is_not_orchestrator_invocation` (xfail W12) |
| O282h | Subagent deny list still contains `create_pull_request_review` after D9 | unit | regression pin | `test_subagent_deny_list_still_contains_create_pull_request_review` (passes today; must survive W13) |
| O283a | Unauthenticated `tools/list` + `tools/call` fail (401 or JSON-RPC `-32600`); Bearer token succeeds | functional | happy (bug) + error | `tests/mcp/test_mcp_auth_and_port.py::test_tools_list_and_call_require_per_run_token` (xfail W14) |
| O283b | `x-mergecraft-agent-id` alone does not authenticate | functional | edge | same test |
| O283c | `/health` stays unauthenticated | functional | control | `test_health_stays_unauthenticated` |
| O283d | Port allocator is not `3764 + offset ∈ [0, 49]` | unit | happy (bug) | `test_select_port_is_not_3764_plus_fifty_wide_scan` (xfail W14) |
| O283e | `MERGECRAFT_MCP_PORT` override still honored | unit | control | `test_mergecraft_mcp_port_override_still_honored` |
| O283f | Codex MCP config has no `http_headers` | unit | control (D16) | `tests/agents/test_codex_mcp_unix_socket.py::test_codex_mcp_config_does_not_invent_http_headers` |
| O283g | Codex MCP config uses a Unix-domain socket (or documented equivalent) | unit | happy (bug) | `test_codex_mcp_config_uses_unix_domain_socket` (xfail W14) |
| O283h | `mergecraft doctor` MCP probe does not name 3764 as "the" port | functional | edge | `tests/cli/test_doctor.py::test_doctor_mcp_probe_does_not_treat_3764_as_the_mcp_port` (xfail W14) |

O282d, O282e, O282h, O283e, O283f pass against current `src/`. W13 must not
drop `create_pull_request_review` from the subagent deny list or put
`push_branch` on `/mcp/reviewer`. W14 must not invent Codex
`http_headers`.

Existing live `tools/list` tests in `tests/mcp/test_tool_classes.py`
forward a Bearer token when `ctx.mcp_auth_token` is set so W14 does not
break them. Reviewer mutation assertions there now allow D9's primary
publication exception without requiring it (W13 greens O282c).

## Acceptance (W11)

- New tests collect with zero import errors
- `make lint` clean
- O282d/e/h, O283e/f pass today; remaining rows xfail until the tagged wave
- No `src/` edits; D6 O-allowlist is for impl waves W12–W14 only
