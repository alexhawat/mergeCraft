# Platform hygiene — test plan

Authoring wave: **H1** (`test-creator`). Implementation: **H2** (sandbox), **H3** (markdownlint + trufflehog scope), **H4** (tracked-markdown checker). Final: **H5**.

Public markdown in this file cites behaviour and test names only. It does not use opaque ledger tokens, a wave-plan preamble, or pointers into gitignored trees.

H1 authored cross-wave reds as `H2` / `H3` / `H4` markers (`strict=False`). Reconciliation after each impl wave removes satisfied xfails. H2 xfails were stripped after the impl landed. H3 xfails were removed after `401a6a41`. `_force_no_backend` sets `cache_clear` with `raising=False` because the empty-caps stand-in is not an `lru_cache` wrapper; pytest was raising before the fail-closed gate ran.

## Contract matrix

| Contract | Greening wave | Primary test(s) |
| --- | --- | --- |
| Darwin skip of the Linux isolation probe; message names local CLI | H2 | `tests/analyzers/test_platform_hygiene_sandbox.py::test_darwin_does_not_run_linux_isolation_probe` |
| Fail-closed `--shell enabled` with no backend; refusal names `MERGECRAFT_ALLOW_UNSANDBOXED_SHELL` | H2 | `…::test_enabled_shell_refuses_without_backend_and_names_override` |
| Override is only the literal `1`; other values still refuse | H2 | `…::test_enabled_shell_override_is_only_the_literal_one` |
| Override path proceeds | H2 | `…::test_enabled_shell_override_allows_proceed` |
| `disabled` / `restricted` do not require a backend | H2 | `…::test_non_enabled_shell_does_not_require_a_backend` |
| `sandbox-exec` backend satisfies `--shell enabled` | H2 | `…::test_enabled_shell_proceeds_when_sandbox_exec_backend_exists` |
| Offline analyze does not start the pipeline when the gate refuses | H2 | `…::test_offline_analyze_enabled_shell_does_not_start_pipeline` |
| Context name: local CLI | H2 | `…::test_sandbox_execution_context_names_local_cli` |
| Context name: Action container | H2 | `…::test_sandbox_execution_context_names_action_container` |
| Context name: container-without-cgroups | H2 | `…::test_sandbox_execution_context_names_container_without_cgroups` |
| Probe reasons include the named context | H2 | `…::test_probe_reasons_include_the_named_execution_context` |
| `detect_sandbox_method()` returns `sandbox-exec` on Darwin | H2 | `…::test_detect_sandbox_method_returns_sandbox_exec_on_darwin` |
| Missing `sandbox-exec` stays `none` | H2 (already green) | `…::test_detect_sandbox_method_is_none_when_sandbox_exec_missing` |
| Policy: network denied; writes only inside the workspace | H2 | `…::test_sandbox_exec_policy_denies_network_and_writes_outside_workspace` |
| Argv starts with `sandbox-exec` | H2 | `…::test_build_sandbox_exec_argv_invokes_sandbox_exec` |
| Live write-outside blocked (Darwin) | H2 | `…::test_sandbox_exec_blocks_write_outside_workspace` |
| Live network blocked (Darwin) | H2 | `…::test_sandbox_exec_blocks_network` |
| `has_markdownlint_config` is false when absent | H3 | `tests/analyzers/test_markdownlint_fallback.py::test_has_markdownlint_config_is_false_when_absent` |
| All five filename families recognised | H3 | `…::test_has_markdownlint_config_recognises_each_filename_family` |
| Directory / nested config ignored | H3 | `…::test_has_markdownlint_config_ignores_a_directory_with_the_same_name`, `…::test_has_markdownlint_config_ignores_nested_config` |
| Fallback JSON disables only MD060 | H3 | `…::test_markdownlint_default_config_disables_only_md060` |
| Absent-config argv patch injects `--config` before `{files}`; no `--disable` | H3 | `…::test_apply_config_absent_patches_injects_fallback_before_files_token` |
| Repo config always wins | H3 (already green) | `…::test_apply_config_absent_patches_does_not_override_repo_config`, `…::test_markdownlint_with_repo_config_keeps_repo_rules` |
| Resolve path emits the fallback run note | H3 | `…::test_markdownlint_without_config_uses_conservative_fallback`, `…::test_markdownlint_fallback_note_constant_matches_prisma_pattern` |
| trufflehog exclude covers `.venv-dev` and virtualenv trees | H3 | `tests/analyzers/test_trufflehog_scope.py::test_trufflehog_exclude_paths_cover_venv_dev_and_virtualenv_trees` |
| No blanket `tests/**` skip | H3 (already green) | `…::test_trufflehog_exclude_paths_do_not_blanket_skip_tests` |
| Intentional fixtures suppressed by name with a reason | H3 | `…::test_trufflehog_named_fixture_suppressions_cover_each_intentional_fixture` |
| A newly committed secret under `tests/` still fires | H3 | `…::test_named_fixture_is_suppressed_and_a_new_test_secret_is_not` |
| Virtualenv tree is out of scope | H3 | `…::test_virtualenv_tree_is_out_of_trufflehog_scope` |
| Listing uses `git ls-files '*.md'` | H4 | `tests/scripts/test_check_tracked_markdown.py::test_list_tracked_markdown_invokes_git_ls_files` |
| Flags ledger tokens, the wave-plan preamble, and gitignored-waves citations | H4 | `…::test_scan_flags_decision_id_wave_plan_and_ignorelocal_citation` |
| Allowlist `docs/dev/changelog-archive.md` | H4 | `…::test_allowlisted_changelog_archive_is_not_an_offense` |
| `main` exit codes | H4 | `…::test_main_fails_on_tracked_decision_id`, `…::test_main_passes_on_clean_tracked_markdown` |
| Never walks a gitignored directory | H4 | `…::test_checker_never_walks_a_gitignored_directory`, `…::test_checker_reports_tracked_file_not_gitignored_twin` |
| Wired into `make lint` and pre-commit | H4 | `tests/ci/test_tracked_markdown_lint_wiring.py` |

## Pinned symbols H2–H4 must implement

| Symbol | Module | Role |
| --- | --- | --- |
| `require_sandbox_for_enabled_shell` | `mergecraft.analyzers.sandbox` | Fail-closed gate for `--shell enabled`; names `MERGECRAFT_ALLOW_UNSANDBOXED_SHELL=1` |
| `sandbox_execution_context` | `mergecraft.analyzers.sandbox` | Returns `local CLI`, `Action container`, or `container-without-cgroups` |
| `sandbox_exec_policy` | `mergecraft.analyzers.sandbox` | Seatbelt profile: read-only outside workspace, network denied |
| `build_sandbox_exec_argv` | `mergecraft.analyzers.sandbox` | Wraps argv in `sandbox-exec` |
| `detect_sandbox_method` | `mergecraft.mcp.shell` | Gains the `sandbox-exec` backend on Darwin |
| `has_markdownlint_config` | `mergecraft.analyzers.detect` | All five markdownlint config filename families |
| `_apply_config_absent_patches` | `mergecraft.analyzers.resolve` | Existing mechanism; new markdownlint branch |
| `_MARKDOWNLINT_FALLBACK_NOTE` | `mergecraft.analyzers.resolve` | Run note, prisma-lint pattern |
| `markdownlint-default-config.json` | `src/mergecraft/analyzers/catalog/` | `{"MD060": false}` only |
| `trufflehog_named_fixture_suppressions` | `mergecraft.analyzers.config` | Path → named reason |
| `is_trufflehog_path_suppressed` | `mergecraft.analyzers.config` | Named fixtures and virtualenv trees; not blanket `tests/` |
| `write_trufflehog_exclude_paths` | `scripts.ci_extended_sarif` | Must include `.venv-dev` |
| `list_tracked_markdown` | `scripts/check_tracked_markdown.py` | `git ls-files '*.md'` only |
| `scan_markdown` | `scripts/check_tracked_markdown.py` | Offense scan |
| `main` | `scripts/check_tracked_markdown.py` | Exit 0/1 |

Guard-deletion note: fail-closed tests assert the refusal when `_OVERRIDE` is unset or not the literal `1`. A removed guard makes those cases proceed and fail the assertion.

## Already-green companions (not xfailed)

- `tests/analyzers/test_sandbox_platform.py` — existing Darwin skip of `subprocess.run` for the Linux probe
- `tests/mcp/test_shell_sandbox_honesty.py` — forced onto the no-backend path so H2's Darwin backend does not change the `none` registration cases
- Repo-config-wins markdownlint cases and the no-blanket-`tests/` trufflehog exclude case
