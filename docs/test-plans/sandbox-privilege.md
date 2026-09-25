# Test plan — sandbox privilege drop, gate environment, and post-run sink scan

Owning wave: the red suite authored before the implementation waves that make it
green. This document maps every behaviour the wave pins to the test that covers
it, and records which tests are red until implementation lands, which are guards
that must stay green throughout, and which run only inside the privileged
(action image) backend.

## How to run

```bash
make lint
make typecheck
UV_PROJECT_ENVIRONMENT="$PWD/.venv-dev" MERGECRAFT_PYTEST_JOBS=0 \
  uv run pytest tests/mcp tests/analyzers tests/security tests/test_review_checks.py -q
```

Bare `uv run` uses the runtime virtualenv; the dev extras (pytest) live in
`.venv-dev`, which the command above pins explicitly.

## Coverage matrix

| Behaviour | Layer | Test file · test |
| --- | --- | --- |
| Namespace shell drops root identity to the agent user, after every mask, in one `exec` | Unit | `tests/mcp/test_shell_spawn_argv.py` · `test_root_unshare_shell_drops_identity_after_every_mount` |
| Sudo-elevated shell drops back to the orchestrator's numeric UID/GID with `--clear-groups` | Unit | `tests/mcp/test_shell_spawn_argv.py` · `test_sudo_unshare_shell_drops_to_the_orchestrator_identity` |
| Missing `setpriv` refuses before any process is spawned | Unit / error handling | `tests/mcp/test_shell_spawn_argv.py` · `test_missing_setpriv_refuses_before_spawning` |
| Unresolvable agent user refuses before any process is spawned | Unit / error handling | `tests/mcp/test_shell_spawn_argv.py` · `test_unresolvable_agent_user_refuses_before_spawning` |
| The Darwin `sandbox-exec` branch keeps its byte-identical argv | Guard | `tests/mcp/test_shell_spawn_argv.py` · `test_sandbox_exec_argv_is_unchanged` |
| A non-root direct-namespace host keeps today's argv, with no drop | Guard | `tests/mcp/test_shell_spawn_argv.py` · `test_non_root_unshare_argv_is_unchanged` |
| Root orchestrator drops the analyzer payload and omits the root mapping | Unit | `tests/analyzers/test_sandbox.py` · `test_root_analyzer_argv_omits_map_root_user_and_drops_identity` |
| Off the root backend the analyzer argv is unchanged | Guard | `tests/analyzers/test_sandbox.py` · `test_non_root_analyzer_argv_keeps_map_root_user_and_no_reuid` |
| The gate subprocess never sees the orchestrator's credentials | Unit / integration | `tests/test_review_checks.py` · `test_run_checks_scrubs_credentials_from_the_gate_environment` |
| An empty plan environment never inherits the process environment (bare branch) | Unit | `tests/analyzers/test_run_env.py` · `test_bare_run_plan_with_empty_env_does_not_inherit_os_environ` |
| An empty plan environment never inherits the process environment (sandboxed branch) | Unit | `tests/analyzers/test_run_env.py` · `test_sandboxed_run_plan_with_empty_env_does_not_inherit_os_environ` |
| File arguments are confined to the checkout and option-shaped entries are neutralised by path shape | Unit / error handling | `tests/analyzers/test_resolve.py` · `test_static_check_plan_confines_and_neutralises_changed_files` |
| A clean repo-relative file argument survives confinement | Guard | `tests/analyzers/test_resolve.py` · `test_static_check_plan_leaves_clean_entries_readable` |
| The sandbox failure signature table classifies each network and write-denied sample | Unit | `tests/analyzers/test_sandbox_failure_signatures.py` · `test_network_signatures_classify_as_network_disabled`, `test_write_denied_signatures_classify_as_path_not_writable`, `test_errno_write_signatures_survive_redaction` |
| A denied write is still classified after pre-classification redaction turns its path into `<redacted>` | Unit / error handling | `tests/analyzers/test_sandbox_failure_signatures.py` · `test_redacted_write_denied_line_classifies_as_path_not_writable` |
| Ordinary tool output that merely mentions "network", or a code-level "permission denied" that names no denied write, stays unclassified | Unit | `tests/analyzers/test_sandbox_failure_signatures.py` · `test_ordinary_tool_output_is_left_unclassified` |
| A code-level denial sentence (a bare denial phrase, or a generic `open` token) is not a sandbox write, while real kernel/errno write denials still classify | Unit | `tests/analyzers/test_sandbox_failure_signatures.py` · `test_ordinary_tool_output_is_left_unclassified`, `test_write_denied_positive_matrix_still_classifies` |
| Untrusted gates run inside the sandbox with a scrubbed env and scratch `HOME`/cache/tmp | Integration | `tests/mcp/test_static_checks.py` · `test_untrusted_gates_run_sandboxed_with_scratch_env` |
| A sandbox-caused failure becomes `declared-but-cannot-run`, not a finding | Integration / error handling | `tests/mcp/test_static_checks.py` · `test_sandbox_caused_gate_failure_is_declared_not_a_finding` |
| A real gate failure is still reported as that gate's result | Integration | `tests/mcp/test_static_checks.py` · `test_real_gate_failure_is_still_the_gates_result` |
| A sandboxed gate's writes never reach the real checkout | Integration | `tests/mcp/test_static_checks.py` · `test_sandboxed_gate_write_never_reaches_the_real_checkout` |
| The untrusted gate path requests the copy-on-write view and its command carries the overlay/scratch-copy fragment, widened for the dropped uid | Integration | `tests/mcp/test_static_checks.py` · `test_untrusted_gates_request_the_copy_on_write_checkout_view` |
| A gate writing build output at the repo root succeeds and the real checkout is byte-identical afterwards | Root-gated | `tests/security/test_untrusted_gate_write_view.py` · `test_gate_writes_the_view_and_leaves_the_real_checkout_untouched` |
| A gate whose output is non-empty still leaves the real checkout byte-identical (its output is not persisted into the tree) | Root-gated | `tests/security/test_untrusted_gate_write_view.py` · `test_gate_output_never_reaches_the_real_checkout` |
| A write the sandbox genuinely denies classifies as `declared-but-cannot-run` with the write reason, never `failed` | Root-gated / error handling | `tests/security/test_untrusted_gate_write_view.py` · `test_write_the_sandbox_genuinely_denies_is_declared_not_a_finding` |
| A denied write on a short, dot-free root-owned path is still classified after its path is redacted, never `failed` | Root-gated / error handling | `tests/security/test_untrusted_gate_write_view.py` · `test_redacted_write_denied_path_is_declared_not_a_finding` |
| The trusted tier runs gates as before, without a namespace | Guard | `tests/mcp/test_static_checks.py` · `test_trusted_tier_gate_still_runs_without_a_namespace` |
| The sink scan returns sink paths and never contents | Unit | `tests/security/test_review_canary.py` · `test_scan_returns_sink_paths_and_never_contents`, `test_scan_returns_nothing_for_clean_sinks` |
| A canary sink fails the run, names the path, forces the approval conclusion to `failure`, and is deleted | Functional / E2E | `tests/security/test_sink_scan_post_run.py` · `test_canary_sink_fails_the_run_names_the_path_and_is_deleted` |
| Clean sinks change nothing | Functional / E2E | `tests/security/test_sink_scan_post_run.py` · `test_clean_sinks_change_nothing` |
| Neither image recursively hands the runtime tree to the agent user; the agent user and precompiled bytecode remain | Static / guard | `tests/security/test_dockerfile_runtime_ownership.py` |
| The shell payload runs as a non-root UID with no effective capabilities | Root-gated | `tests/security/test_shell_uid_drop.py` · `test_shell_payload_runs_unprivileged_with_no_effective_capabilities` |
| The read-only checkout metadata bind still holds against the dropped payload | Root-gated | `tests/security/test_shell_uid_drop.py` · `test_shell_cannot_write_the_git_directory` |
| A root-only file stays unreadable to the dropped payload | Root-gated | `tests/security/test_shell_uid_drop.py` · `test_shell_cannot_read_a_root_only_file` |
| The analyzer payload runs non-root, writes scratch and `HOME`, and cannot write outside them | Root-gated | `tests/security/test_analyzer_uid_drop.py` · `test_analyzer_payload_runs_without_root_identity`, `test_analyzer_payload_can_write_scratch_and_home`, `test_analyzer_payload_cannot_write_outside_scratch` |
| The userspace-egress path keeps a non-root payload or fails closed by name | Root-gated | `tests/security/test_analyzer_uid_drop.py` · `test_userspace_egress_analysis_never_reaches_uid_zero` |
| The runtime tree and its virtualenv are root-owned; the agent cannot write them; its `HOME` is writable | Root-gated | `tests/security/test_runtime_tree_ownership.py` |

## Red / green split

**Red until the implementation waves land** (assertions fail, or the
not-yet-existing module raises at test time; collection stays clean):

- the shell drop and its two fail-closed refusals in
  `tests/mcp/test_shell_spawn_argv.py`;
- the root analyzer argv in `tests/analyzers/test_sandbox.py`;
- every `tests/analyzers/test_run_env.py` case;
- both `static_check_plan` file-argument cases;
- all three classes of case in `tests/analyzers/test_sandbox_failure_signatures.py`
  (the signature module does not exist yet);
- the sandboxed untrusted-gate cases in `tests/mcp/test_static_checks.py`;
- the sink-path return shape and the post-run sink cases;
- the recursive-chown and precompiled-bytecode checks in
  `tests/security/test_dockerfile_runtime_ownership.py`;
- the credential-scrubbing gate cases in `tests/test_review_checks.py`.

**Follow-up fixes — green** (authored red after the final-verification round,
now green against the landed fixes):

- the dropped-uid write allowance in the copy-on-write fragment
  (`tests/mcp/test_static_checks.py` · `test_untrusted_gates_request_the_copy_on_write_checkout_view`);
- the run's `mergecraft-approval` conclusion on a sink hit
  (`tests/security/test_sink_scan_post_run.py` · `test_canary_sink_fails_the_run_names_the_path_and_is_deleted`);
- the sudo-elevated identity resolution: root via `sudo` off the action image drops to the invoking `SUDO_UID`/`SUDO_GID` with `--clear-groups`, a zero sudo id still fails closed, and the agent-user fallback is unchanged (`tests/analyzers/test_sandbox.py`, `tests/mcp/test_shell_spawn_argv.py`);
- the copy-on-write write-view cases in
  `tests/security/test_untrusted_gate_write_view.py` (root-gated). Two were
  added after a later round: a denied write on a short, dot-free root-owned
  path is still classified once its path has been redacted
  (`test_redacted_write_denied_path_is_declared_not_a_finding`), and a gate that
  prints output still leaves the real checkout byte-identical
  (`test_gate_output_never_reaches_the_real_checkout`). The classifier half of
  the first case is host-runnable as
  `tests/analyzers/test_sandbox_failure_signatures.py` ·
  `test_redacted_write_denied_line_classifies_as_path_not_writable`.

**Green throughout** (guards that must not regress):

- `test_non_root_unshare_argv_is_unchanged`,
  `test_sandbox_exec_argv_is_unchanged`,
  `test_non_root_analyzer_argv_keeps_map_root_user_and_no_reuid`;
- `test_trusted_tier_gate_still_runs_without_a_namespace`,
  `test_real_gate_failure_is_still_the_gates_result`;
- `test_static_check_plan_leaves_clean_entries_readable`;
- `test_scan_returns_nothing_for_clean_sinks`, the pre-existing canary and hash
  cases in `tests/security/test_review_canary.py`;
- the pre-existing static-check, discovery, and shell-disabled registration
  cases in `tests/mcp/test_static_checks.py`.

The full green-guard set that must stay passing is:

```
tests/utils/test_privilege.py
tests/utils/test_privilege_identity.py
tests/security/test_privilege_fail_closed.py
tests/security/test_containment.py
tests/mcp/test_shell_sandbox_honesty.py
tests/analyzers/test_sandbox_execution.py
tests/analyzers/test_shell_disabled_split.py
tests/agents/test_required_static_checks.py
```

## Root-gated (in-image) names

These four files skip outside the privileged backend with the single
precondition reason *"requires euid 0, Linux, unshare and setpriv — runs in the
action image"* and must genuinely execute when run as root in the image:

```
tests/security/test_shell_uid_drop.py
tests/security/test_analyzer_uid_drop.py
tests/security/test_runtime_tree_ownership.py
tests/security/test_untrusted_gate_write_view.py
```

They assert process identity and mount state — never an escape payload.

## Notes and limitations

- The untrusted static-check cases pin the *constructed* child command and its
  environment. The host case asserts the copy-on-write fragment's shape and
  that it widens the view for the dropped uid; whether the mounted view is
  actually writable, and whether a denied write is classified rather than
  reported as a finding, can only be observed on the privileged backend — the
  root-gated copy-on-write cases in
  `tests/security/test_untrusted_gate_write_view.py` carry that half, not the
  analyzer UID-drop cases (those keep the read-only bind).
- The post-run sink cases drive the real orchestrator through the scripted
  run harness, planting the canary during the agent phase so it is present when
  the finalize stage scans. The harness can run the real status-check reporting
  against a recording client (`capture_status_checks=True`) so the assertion is
  on the check-runs the run would post — the `mergecraft-approval` conclusion
  included — not on the orchestrator's arguments to the reporting layer.
- No test asserts a coverage floor or adds a required check.
