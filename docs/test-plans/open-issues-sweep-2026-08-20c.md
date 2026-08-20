# Open issues sweep 2026-08-20c — Batch CA test plan (#350)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20c-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-2026-08-20c` @ `wave/open-issues-sweep-2026-08-20c`
Authoring wave: **W1** (Batch CA RED) · Implementation: **W2.1** (`a2c76fd9`) · Recon: **W2.2**
W3.1 impl: `16a01b47` · W3 recon: un-xfail `capabilities` + `SECURITY.md` pins

Issue #350 out of scope (honoured — no tests): MCP Bearer/auth-header gaps (#345/#346); trust tiers / privilege drop (`analyzers/trust.py`, `utils/privilege.py`).

## xfail schedule

All cross-wave markers use `@pytest.mark.xfail(..., strict=False)`.

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W2** | `test_production_registry_excludes_write_capable_modes` | `green after W2: review-only production boundary (#350)` | **PASS** — un-xfailed W2.2 |
| **W2** | `test_compute_modes_excludes_write_capable_modes` | same | **PASS** — un-xfailed W2.2 |
| **W2** | `test_static_modes_export_excludes_write_capable_modes` | same | **PASS** — un-xfailed W2.2 |
| **W2** | `test_select_mode_rejects_write_capable_names[*]` | same | **PASS** — un-xfailed W2.2 (5 names) |
| **W2** | `test_custom_config_cannot_reenable_write_capable_fix` | same (D12) | **PASS** — un-xfailed W2.2 |
| **W2** | `test_reviewer_shaped_run_cannot_edit_tracked_file[*]` | same | **PASS** — un-xfailed W2.2 |
| **W2** | `test_reviewer_shaped_run_cannot_git_commit[*]` | same | **PASS** — un-xfailed W2.2 |
| **W2** | `test_reviewer_shaped_run_cannot_git_push[*]` | same | **PASS** — un-xfailed W2.2 |
| **W2** | `test_reviewer_shaped_run_cannot_open_code_changing_pr[*]` | same | **PASS** — un-xfailed W2.2 |
| **W3** | `tests/cli/test_capabilities_cmd.py` (11 tests) | `green after W3: mergecraft capabilities manifest (#350 / D10)` | **PASS** — un-xfailed W3 recon |
| **W3** | `tests/test_security_md_review_only.py` (3 tests) | `green after W3: SECURITY.md review-only guarantee (D9 / #350)` | **PASS** — un-xfailed W3 recon |

W1.1 current-state pins (CA350a / still-accepts `select_mode`) **deleted** in W2.2.

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| CA350b | `_MODE_DEFS` is review-only (D12) | unit | happy | `tests/modes/test_review_only_boundary.py::test_production_registry_excludes_write_capable_modes` |
| CA350c | `compute_modes` / `modes` leak no write names | unit | happy | `test_compute_modes_excludes_write_capable_modes`, `test_static_modes_export_excludes_write_capable_modes` |
| CA350d | `select_mode` rejects write-capable names | integration | error | `test_select_mode_rejects_write_capable_names` |
| CA350e | Empty/unknown `select_mode` is existing behaviour (not this file) | — | — | existing `select_mode` tests if any |
| CA350f | Repo config cannot re-enable `Fix` (D12) | integration | error | `test_custom_config_cannot_reenable_write_capable_fix` |
| CA350g | Reviewer-shaped run cannot edit a tracked file | functional | error + edge (file unchanged) | `test_reviewer_shaped_run_cannot_edit_tracked_file` |
| CA350h | Reviewer-shaped run cannot `git commit` (`commit_changes`) | functional | error | `test_reviewer_shaped_run_cannot_git_commit` |
| CA350i | Reviewer-shaped run cannot `git push` (`push_branch`) | functional | error | `test_reviewer_shaped_run_cannot_git_push` |
| CA350j | Reviewer-shaped run cannot open a code-changing PR | functional | error | `test_reviewer_shaped_run_cannot_open_code_changing_pr` |
| CA350k | `git` MCP tool still does not forward `commit` | unit | already green | `test_git_mcp_tool_does_not_forward_commit` |
| CA350l | Write-mode modules remain importable (D12) | unit | happy | `test_write_mode_modules_remain_importable_as_negative_fixtures` |
| CA350m | Production catalog names are Review / IncrementalReview / Plan | unit | happy | `tests/test_modes.py::EXPECTED_MODE_NAMES` / `test_compute_modes_returns_all_built_ins` |
| CA350n | New `cli/capabilities_cmd.py` with `run` + `capabilities_manifest()` | unit | happy | `tests/cli/test_capabilities_cmd.py::test_capabilities_module_is_a_new_cli_file`, `test_capabilities_module_exports_run_and_manifest` |
| CA350o | `mergecraft capabilities` in root help; default table is review-only | functional | happy | `test_root_help_lists_capabilities_command`, `test_capabilities_help_describes_manifest`, `test_capabilities_table_states_review_only` |
| CA350p | Global `--format json` emits schema_versioned review-only manifest | functional | happy | `test_capabilities_json_uses_global_format_flag` |
| CA350q | Manifest allowed/forbidden sets; no write mode names | functional | edge | `test_capabilities_json_forbidden_covers_write_surface`, `test_capabilities_json_allowed_is_review_verbs_only`, `test_capabilities_json_modes_exclude_write_capable_names` |
| CA350r | Extra argv / unknown option → usage exit 2 | functional | error | `test_capabilities_rejects_unexpected_positional`, `test_capabilities_unknown_option_is_usage_error` |
| CA350s | `SECURITY.md` states review-only guarantee (D9) | unit | happy | `tests/test_security_md_review_only.py::test_security_md_states_review_only_guarantee` |
| CA350t | `SECURITY.md` forbids edit/commit/push/code-changing PR | unit | happy | `test_security_md_forbids_source_edits_commits_pushes_and_code_changing_prs` |
| CA350u | `SECURITY.md` allows identify/investigate/verify/explain/prioritize/suggest | unit | happy | `test_security_md_allows_identify_investigate_verify_explain_prioritize_suggest` |

Write-capable names under test: `Build`, `AddressReviews`, `Fix`, `ResolveConflicts`, `Task`.
Reviewer-shaped modes: `Review`, `IncrementalReview`.
Production modes: `Review`, `IncrementalReview`, `Plan`.

Error contract for W2 negatives: `ToolResult.is_error is True` and the message contains **`review-only`** (plus `commit` / `push` where those verbs apply). `create_pull_request` must not call `scm.post`. `commit_changes` / `push_branch` must not invoke `_run_git` with those verbs.

## Recon notes (W2.2)

- Un-xfailed every `green after W2` marker in `tests/modes/test_review_only_boundary.py`.
- Deleted W1.1 still-registered / still-accepts pins (CA350a).
- Kept D12 import fixture (`modes/Fix.py` and siblings remain importable).
- Updated `tests/test_modes.py` `EXPECTED_MODE_NAMES` to Review / IncrementalReview / Plan. Write-mode prompt pins (`Build` signed-commits, `ResolveConflicts`, `AddressReviews` withdrawn heading, `mergecraft-reviewer` on Build) render unregistered templates via `_expand_template` so D12 modules stay covered without being in the production catalog.

## Acceptance (W2.2)

- W2 negatives **PASS** (no leftover xfail, no XPASS)
- W1.1 still-registered pins gone
- `make lint` + `make typecheck` clean
- No `src/` edits; no CHANGELOG (Unreleased Security bullet already in `a2c76fd9`)

## W3 recon (`mergecraft capabilities` + SECURITY.md)

- Un-xfailed every `green after W3` marker in `tests/cli/test_capabilities_cmd.py`
  and `tests/test_security_md_review_only.py` (14 tests).
- W3.1 (`16a01b47`) already added `capabilities_cmd.py`, additive
  `app.command("capabilities")`, and the `SECURITY.md` review-only guarantee.
- CAF not started.

## Acceptance (W3 recon)

- W3 pins **PASS** (no leftover xfail, no XPASS)
- `make lint` + `make typecheck` clean
- No `src/` or `SECURITY.md` edits; CAF not marked
