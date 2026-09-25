# Test plan — credentials that outlive their purpose

Companion to the wave plan `41-credentials-logging-wave-plan.md` (gitignored).
This document maps every contract the wave introduces to the tests that pin it,
across unit, integration and functional layers, and records which tests are
red until the implementation waves land.

Owner: `test-creator` (sole writer of `tests/` and this file). Implementation
waves CR2–CR4 have landed; every contract below is pinned by a plain passing
test.

## Contract → test map

### CR2 — one composed log patcher, on every entrypoint

| Contract | Layer | Tests |
| --- | --- | --- |
| `utils/log.py` owns one composed patcher: bound context first, then the registered message redactor. Install order does not matter. | unit | `tests/utils/test_log.py::test_configure_then_install_keeps_context_and_redaction`, `::test_install_then_configure_keeps_context_and_redaction`, `::test_repeated_configure_after_install_keeps_redaction` |
| A later `configure_logging(force=True)` keeps the redactor installed. | unit | `tests/utils/test_log.py::test_repeated_configure_after_install_keeps_redaction` |
| The CLI root callback leaves both behaviours installed for `review`, `diff-review`, `mcp serve`, `gha`. | unit + functional | `tests/cli/test_logging_entrypoints.py::test_root_callback_keeps_context_and_redaction`, `::test_entrypoint_logging_state_keeps_context_and_redaction[review|diff-review|mcp-serve|gha]` |
| `main()`'s preamble keeps bound context after its redaction call. | functional | `tests/test_main_phases.py::test_preamble_keeps_bound_context_after_redaction_install` |
| Redaction stays scoped to `record["message"]` (no `extra` / exception coverage). | guard | `tests/analyzers/test_redaction_boundaries.py` (unchanged, must stay green) |

### CR3 — env that admits only what it names

| Contract | Layer | Tests |
| --- | --- | --- |
| `git_env_for_token` drops ambient `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT` and every `GIT_CONFIG_KEY_<n>`/`GIT_CONFIG_VALUE_<n>`, before the token check. | unit | `tests/utils/test_git_setup.py::test_git_env_for_token_no_token_skips_config_pairs`, `::test_git_env_for_token_with_token_keeps_only_its_own_pairs` |
| The trace / askpass / ssh / proxy / exec-path families are absent on both the token and no-token paths; `GIT_TERMINAL_PROMPT=0` stays. | unit | `tests/utils/test_git_setup.py::test_git_env_for_token_drops_trace_and_redirect_names` |
| An ambient `GIT_TRACE_CURL` file cannot capture the bearer token from a real git child. | functional | `tests/security/test_hostile_git_config.py::test_ambient_git_trace_cannot_capture_the_token` |
| An ambient credential helper is unreachable by a real `git config` child run with the returned env. | functional | `tests/security/test_hostile_git_config.py::test_ambient_credential_helper_is_unreachable_from_returned_env` |
| `GITHUB_*`/`RUNNER_*` passthrough becomes an explicit name list; lookalike credential names are excluded. | unit | `tests/utils/test_secrets.py::test_prefix_lookalike_credentials_are_not_passed_through` |
| Documented runner names and versioned toolchain homes still pass. | guard | `tests/utils/test_secrets.py::test_documented_runner_names_stay_passed_through` |
| `envAllowlist` still readmits one name. | guard | `tests/utils/test_secrets.py::test_env_allowlist_readmits_a_prefix_lookalike_credential` |
| Active-provider and Bedrock/Vertex reinjection unchanged. | guard | `tests/utils/test_secrets.py::test_active_provider_key_reinjection_is_unchanged`, `::test_bedrock_and_vertex_reinjection_is_unchanged` |

### CR4 — cleanup and revocation that say when they fail

| Contract | Layer | Tests |
| --- | --- | --- |
| Overwrite failure warns once, names the path, leaks no content, does not raise. | unit | `tests/security/test_credentials.py::test_secure_overwrite_warns_when_the_file_cannot_be_opened` |
| Askpass unlink failure warns once and names the path. | unit | `tests/security/test_credentials.py::test_cleanup_warns_when_the_askpass_unlink_fails` |
| Tree removal reports each failed path through an error callback, never silently. | unit | `tests/security/test_credentials.py::test_cleanup_warns_when_rmtree_reports_a_failure` |
| A surviving askpass file is named after the removal attempt. | unit | `tests/security/test_credentials.py::test_cleanup_warns_when_the_askpass_file_survives` |
| Leak-surface wipe failure warns and names the path. | unit | `tests/security/test_credentials.py::test_wipe_warns_when_a_registered_path_cannot_be_removed` |
| Successful scrub/cleanup is silent and removes the tree. | guard | `tests/security/test_credentials.py::test_secure_overwrite_success_emits_no_warning`, `::test_cleanup_success_emits_no_warning` |
| A rejected token revocation logs at `warning`, without the token value. | unit | `tests/utils/test_token.py::test_revoke_installation_token_logs_http_failures_at_warning` |
| Each `main()` teardown step failing in turn still runs the later steps, logs one warning naming the step and exception, and leaves `MainResult` unchanged. | functional | `tests/test_main_phases.py::test_finally_logs_a_failed_step_and_still_runs_later_steps` |
| A successful teardown logs no cleanup-step warning. | guard | `tests/test_main_phases.py::test_teardown_success_logs_no_cleanup_warning` |

## Matrix coverage

- **Unit** — `utils/log.py` composition; `git_env_for_token` env shape; the
  secret allowlist; each cleanup function under a monkeypatched failure; the
  token-revocation log level.
- **Integration** — `git_env_for_token` → real `git ls-remote` / `git config`
  children against a local stub; `main()` teardown orchestration through the
  run harness; the CLI root callback wiring logging state.
- **Functional / E2E** — the four CLI entrypoints invoked through the real
  Typer app; `main()` driven end to end by the scripted run harness.

Scenario classes: happy path (documented success behaviour, and the explicit
guards that a clean run stays silent), edge cases (no token vs token, default
vs explicit remote, repeated configuration, residual files), and error handling
(monkeypatched `OSError`/failure callbacks, HTTP 401/403/500, teardown steps
raising) with assertions on emitted warnings and their contents.

## Red / green status

All contracts in this plan are implemented and every test is a plain passing
assertion — no `xfail` markers remain for this plan.

Green (enforced):

- `tests/utils/test_log.py` — 3 composed-patcher tests.
- `tests/cli/test_logging_entrypoints.py` — 5 root-callback / entrypoint tests.
- `tests/test_main_phases.py` — the `main()` preamble bound-context test and the 4 teardown-step tests.
- `tests/utils/test_git_setup.py` — 29 git-config / trace-redirect tests.
- `tests/security/test_hostile_git_config.py` — 2 ambient-trace / credential-helper tests.
- `tests/utils/test_secrets.py` — 3 lookalike-credential-name tests.
- `tests/security/test_credentials.py` — 5 cleanup-warning tests.
- `tests/utils/test_token.py` — 3 revocation-level tests.

Guards that must stay green: `tests/analyzers/test_redaction_boundaries.py`,
the success-path tests in `tests/security/test_credentials.py`, the documented
passthrough / allowlist / reinjection tests in `tests/utils/test_secrets.py`,
the success-silence tests in `tests/utils/test_git_setup.py`, and
`tests/test_main_phases.py::test_teardown_success_logs_no_cleanup_warning`.

## Test hermeticity

The loguru patcher and the message-redactor slot are process-global. Every test
module that installs one restores it in a module-local autouse fixture
(`configure_logging(force=True)` plus clearing the redactor slot when the setter
exists). No test edits `tests/conftest.py`; ambient environment is set and
undone per test with `monkeypatch`.

## Notes

- `tests/support/run_main_harness.py` gained a defaulted `stop_mcp_error`
  parameter so a teardown failure can be scripted without changing existing
  callers. It appends no new lifecycle event.
- Warnings are captured through a local loguru sink at `WARNING` level and
  filtered to the cleanup-step format, so unrelated run warnings do not affect
  the assertions.
