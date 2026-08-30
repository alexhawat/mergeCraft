# CI gate operator surface — test plan

Maps **W1 RED** contracts for wave plan 16 to the test suite.
Source plan: `.ignorelocal/waves/16-ci-gate-operator-surface-wave-plan.md`.

All cross-wave reds use `@pytest.mark.xfail(..., strict=True)` per the lane plan —
`scripts/check_xpass.py` fails non-strict xfails that pass.

## W1.1 — settings root → W2

| Contract | Tests | Layer |
| --- | --- | --- |
| `load_repo_settings(root=<base>)` reads base config with `GITHUB_WORKSPACE` at head (#573 guard) | `tests/config/test_ci_gate_settings_root.py::test_load_repo_settings_root_reads_base_with_github_workspace_at_head` | unit |
| cwd in sibling worktree wins over `GITHUB_WORKSPACE` (D2) | `…::test_cwd_worktree_wins_over_github_workspace` | unit |
| cwd inside `GITHUB_WORKSPACE` unchanged (normal CI) | `…::test_cwd_inside_github_workspace_unchanged` | unit |
| `MERGECRAFT_CONFIG` wins (D3) | `…::test_mergecraft_config_wins_over_workspace_and_cwd` | unit |
| explicit `root=` wins over `GITHUB_WORKSPACE` | `…::test_explicit_root_wins_over_github_workspace` | unit |
| outside git repo, no `GITHUB_WORKSPACE` → cwd fallback | `…::test_outside_git_repo_falls_back_to_cwd` | unit |
| base tree validates when head config has unknown key (#573 e2e) | `…::test_base_tree_validates_cleanly_when_head_config_has_unknown_key` | integration |

Shared helpers: `tests/config/support_ci_gate_settings.py`.

Pinned API: `mergecraft.config.settings.load_repo_settings`, `_workspace_root` (W2).

## W1.2 — coverage gate → W3

| Contract | Tests | Layer |
| --- | --- | --- |
| `BASE_WORKTREE_MEASURE_BLOCK` markers parseable (D7) | `tests/ci/test_ci_gate_coverage_delta.py::test_base_measure_block_markers_remain_parseable` | structural |
| `UV_PROJECT_ENVIRONMENT` export survives | `…::test_base_measure_block_exports_uv_project_environment` | structural |
| pre-TH inline measure fallback survives | `…::test_base_measure_block_keeps_pre_th_inline_fallback` | structural |
| head `make coverage-gate` stays hard (D5) | `…::test_head_coverage_gate_stays_unguarded_outside_subshell` | structural |
| broken base → no `coverage-base.json`, exit 0 (D4) | `…::test_broken_base_measurement_exits_zero_without_base_json` | integration |
| skipped delta emits warning with reason (D6) | `…::test_skipped_delta_emits_warning_with_reason` | integration |
| healthy base still runs delta comparison | `…::test_successful_base_measurement_still_runs_delta_comparison` | structural |
| worktree cleaned up when measurement fails | `…::test_worktree_cleaned_up_when_base_measurement_fails` | integration |
| head regression still fails when base skips (D5) | `…::test_head_coverage_regression_still_fails_when_base_skips` | integration |

Existing wrapper guard: `tests/ci/test_coverage_delta_wrapper.py` (D7 base block must not run `make coverage-gate`).

Shared helpers: `tests/ci/support_ci_gate_coverage.py`.

Pinned script: `scripts/ci_coverage_delta_gate.sh`.

## W1.3 — `provider status --github` → W4

| Contract | Tests | Layer |
| --- | --- | --- |
| every reviewer + `pN` slot + provider (D8) | `tests/cli/test_provider_status_cmd.py::test_provider_status_renders_every_reviewer_slot_and_provider` | E2E |
| no credential → not available + env var name (D11) | `…::test_provider_status_missing_credential_reports_env_var_not_value` | E2E |
| unwired ≠ no credential (D10) | `…::test_provider_status_unwired_is_distinct_from_missing_credential` | E2E |
| `after:` / dispatch level rendered | `…::test_provider_status_renders_dispatch_level_and_after_ordering` | E2E |
| disabled provider renders disabled (#521) | `…::test_provider_status_disabled_provider_renders_disabled` | E2E |
| `--github` no token → unknown, exit 0 (D9) | `…::test_provider_status_github_without_token_is_unknown_exit_zero` | E2E |
| `--github` with token → secret presence only (D11) | `…::test_provider_status_github_with_token_reports_secret_presence` | E2E |
| `--json` stable documented schema | `…::test_provider_status_json_matches_documented_schema` | E2E |
| `--cwd` selects every target | `…::test_provider_status_cwd_selects_config_workflow_and_registry_targets` | E2E |
| read-only (D9) | `…::test_provider_status_is_read_only` | E2E |

Shared helpers: `tests/cli/support_provider_status.py`.

Pinned modules (W4): `mergecraft.cli.provider_status` (`STATUS_JSON_SCHEMA`), roster sources `resolve_roles` / `resolve_role_levels`, `parse_auth_manifest`, `credential_status_for_slug` adapter.

## xfail reconciliation

| Wave | Marker reason prefix | Files |
| --- | --- | --- |
| W2 | `green after W2: settings-root worktree resolution` | `tests/config/test_ci_gate_settings_root.py` |
| W3 | `green after W3: base measurement signal not gate` | `tests/ci/test_ci_gate_coverage_delta.py` |
| W4 | `green after W4: provider status roster view` | `tests/cli/test_provider_status_cmd.py` |

Guard tests (no xfail) must stay green through W2–W4 implementation.
