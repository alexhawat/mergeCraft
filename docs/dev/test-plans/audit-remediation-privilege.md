# Audit remediation lane A — privilege & execution boundary — test plan

Wave plan: `.ignorelocal/waves/10-audit-remediation-a-privilege-execution-wave-plan.md`
Authoring wave: **AP1** (RED). Implementation: **AP2–AP7**.
xfail-reconciliation: per impl wave as each AP2–AP7 lands.

Locked decisions: **D2** (single `git_argv` helper + lint checker), **D5–D8** (capability
not `CI`, fail-closed absent not degraded), **D9** (`sudo --preserve-env` by name),
**D11** (image identity not uid), **D12** (prep venv isolation), **D14a** (tests-only in AP1),
**D15** (real git at boundaries), **D17/D18** (container vs host split).

## Host vs container (D17 / D18)

| Runs on host (macOS worktree) | Requires action image (`docker build -t mergecraft:lane-a .` + privileged run) |
| --- | --- |
| AP1.1 git hardening + hostile config (real `git`) | AP3/AP4/AP6 namespace / mount / `setpriv` proofs at Final |
| AP1.4 OpenCode permissions + review canaries | — |
| AP1.6 prep isolation (mocked subprocess) | — |
| AP1.2/AP1.3 shell argv tests (mocked `Popen`) | Live `unshare`/`mount` if extending beyond mocks |

## xfail schedule

All cross-wave markers use `strict=False` and name the greening wave in `reason`.

| Greening wave | Test files | Marker reason prefix |
| --- | --- | --- |
| AP2 | `test_hostile_git_config.py`, `test_git_hardening.py`, `test_privilege_chown.py`, `test_rev_parse_guards.py`, `test_git_argv_lint.py` | `green after AP2` |
| AP3 | `test_sandbox_probes.py`, `test_sandbox_skip_visibility.py`, `test_shell_fallback.py`, `test_network_namespace.py` (inverted rows) | `green after AP3` |
| AP4 | `test_shell_spawn_argv.py`, `test_shell_git_invariant.py` | `green after AP4` |
| AP5 | `test_opencode_permissions.py` (except `test_bash_stays_denied`), `test_review_canary.py` | `green after AP5` |
| AP6 | `test_privilege_identity.py` | `green after AP6` |
| AP7 | `test_prep_env.py`, `test_prep_selection.py`, `test_prep_venv.py` | `green after AP7` |

`test_bash_stays_denied` is **not** xfailing — bash denial is already true on trunk.

## Contract → coverage matrix

### AP1.1 — root-side git (AP2, MCB-01 / MCB-33)

| Test | File | Contract |
| --- | --- | --- |
| `test_root_side_status_does_not_execute_fsmonitor` | `tests/security/test_hostile_git_config.py` | Real `git status` via `_run_git`; `core.fsmonitor` sentinel must not appear |
| `test_root_side_diff_does_not_execute_diff_external` | same | Real `git diff`; `diff.external` sentinel must not appear |
| `test_commit_path_does_not_execute_fsmonitor` | same | Commit path must pin safe config (not only `hooksPath`) |
| `test_insteadof_rewrite_does_not_leak_git_config_value_0` | same | `url.<host>.insteadOf` rewrite cannot fire on hardened argv |
| `test_xrepo_checkout_is_equally_protected` | same | `xrepo.review._rev_parse_commit` equally hardened (H-7) |
| `test_git_argv_pins_every_safe_config_key` | `tests/utils/test_git_hardening.py` | `GIT_SAFE_CONFIG` / `git_argv()` pins every D2 key |
| `test_prepare_workspace_does_not_chown_dot_git` | `tests/utils/test_privilege_chown.py` | D3 — recursive chown skips `.git` |
| `test_leading_dash_rev_is_rejected` | `tests/xrepo/test_rev_parse_guards.py` | MCB-33 leading-dash rev rejected |
| `test_rev_parse_passes_end_of_options` | same | `--end-of-options` before rev in hardened argv |
| `test_bare_git_list_literal_fails_the_checker` | `tests/ci/test_git_argv_lint.py` | D2 — `scripts/check_git_argv.py` rejects bare `["git", …]` |

Fixtures: `tests/security/hostile_git_fixtures.py` (per-test repos); corpus
`tests/security/fixtures/hostile-repo/` rebuilt via `build_hostile_repo.sh` (AP1.4b).

### AP1.2 — sandbox capability (AP3, MCB-07/09/10/35)

| Test | File | Contract |
| --- | --- | --- |
| `test_probe_does_not_consult_ci_env_var` | `tests/analyzers/test_sandbox_probes.py` | D5 — probe runs without `CI` as the answer |
| `test_all_probes_share_one_privilege_ladder` | same | One sudo/unshare ladder across probes |
| `test_probe_capabilities_is_cached` | same | MCB-35 — `lru_cache` on `probe_capabilities` |
| `test_reset_detection_cache_clears_probe_cache` | same | D13 — cache cleared with `reset_detection_cache` |
| `test_skipped_untrusted_analyzers_emit_a_finding` | `tests/analyzers/test_sandbox_skip_visibility.py` | D7 — `rule_id: analyzers.sandbox-unavailable` |
| `test_unsandboxed_shell_refuses_by_default` | `tests/mcp/test_shell_fallback.py` | D8 — default refuse without isolation |
| `test_allow_unsandboxed_env_var_overrides` | same | `MERGECRAFT_ALLOW_UNSANDBOXED_SHELL=1` opt-out |
| `test_fallback_branch_masks_container_sockets_when_it_runs` | same | MCB-07 — fallback passes `wrapped` (socket mask) |
| `test_untrusted_shell_absent_when_netns_unavailable` | `tests/mcp/test_network_namespace.py` | MCB-10 / D6 — shell tool absent when netns missing |
| `test_unshare_argv_skips_net_when_probe_unavailable` | same | Inverted — spawn fails closed instead of omitting `--net` |
| `test_network_namespace_available_true_when_unshare_net_succeeds_without_ci` | same | D5 — probe without `CI=true` |

### AP1.3 — sudo argv + git invariant (AP4, MCB-08/25)

| Test | File | Contract |
| --- | --- | --- |
| `test_no_provider_key_value_appears_in_any_branch_argv` | `tests/mcp/test_shell_spawn_argv.py` | D9 — no `PROVIDER_KEY_ENV_VARS` value in argv (all branches) |
| `test_sudo_branch_uses_preserve_env_by_name` | same | `sudo --preserve-env=<names>`, not `sudo env KEY=val` |
| `test_git_dir_is_read_only_in_every_branch` | `tests/mcp/test_shell_git_invariant.py` | D10 — `.git` ro bind in every spawn branch |
| `test_git_binary_unavailable_in_untrusted_namespace` | same | Git binary masked/unavailable in namespace |

### AP1.4 — OpenCode permissions (AP5, MCB-06)

| Test | File | Contract |
| --- | --- | --- |
| `test_review_mode_denies_webfetch` | `tests/agents/test_opencode_permissions.py` | Review mode denies `webfetch` |
| `test_review_mode_denies_external_directory` | same | Denies `external_directory` |
| `test_review_mode_denies_edit` | same | Denies broad `edit` |
| `test_review_mode_read_is_allowlisted_to_the_checkout` | same | Read allowlisted to checkout, not `*` |
| `test_bash_stays_denied` | same | Guard — bash stays `deny` |
| `test_outside_checkout_canary_is_unreadable` | `tests/security/test_review_canary.py` | Outside-checkout read boundary |
| `test_provider_key_canary_does_not_reach_a_local_sink` | same | Provider key not in local sinks |
| `test_config_yaml_is_unwritable_during_review` | same | `.mergecraft/config.yaml` integrity |

### AP1.5 — privilege identity (AP6, MCB-24/32)

| Test | File | Contract |
| --- | --- | --- |
| `_uid_independent_privilege_boundary` (autouse) | `tests/prep/test_prep_fail_closed.py` | AP1.4b — monkeypatch `prepare_workspace_for_agent` |
| `test_root_outside_action_image_refuses_with_policy_message` | `tests/utils/test_privilege_identity.py` | D11 — policy refusal + diagnostic |
| `test_allow_root_env_var_overrides` | same | `MERGECRAFT_ALLOW_ROOT=1` override |
| `test_in_action_image_detects_is_sandbox_and_opt_dir` | same | `_in_action_image()` keys on `IS_SANDBOX` + `/opt/mergecraft` |
| `test_setpriv_argv_carries_no_new_privs_and_cleared_caps` | same | MCB-32 — `--no-new-privs`, cap clearing |

### AP1.6 — prep isolation (AP7, MCB-22)

| Test | File | Contract |
| --- | --- | --- |
| `test_prep_env_is_a_real_allowlist` | `tests/prep/test_prep_env.py` | No `ANTHROPIC_API_KEY` / `GITHUB_TOKEN` in prep env |
| `test_uv_lock_wins_over_a_stray_requirements_txt` | `tests/prep/test_prep_selection.py` | `uv.lock` wins over `requirements.txt` |
| `test_cwd_is_threaded_not_read_twice` | same | Explicit cwd threading (not double `Path.cwd()`) |
| `test_install_targets_a_dedicated_virtualenv` | `tests/prep/test_prep_venv.py` | D12 — install targets prep venv, not reviewer interpreter |

## Imports of not-yet-existing symbols

Symbols in `mergecraft.utils.git_hardening`, `mergecraft.security.review_integrity`,
`mergecraft.prep.python._prep_env`, `utils.privilege._in_action_image`, and
`scripts/check_git_argv.py` are imported **inside test bodies** (or via lazy
`getattr`/`pytest.fail`) so collection succeeds before AP2–AP7 land.

## Status

AP1 RED suite authored on `wave/ap1-privilege-red`. Assertions fail or xfail pending
AP2–AP7 implementation. Collection, `make lint`, and `make typecheck` must stay clean.
