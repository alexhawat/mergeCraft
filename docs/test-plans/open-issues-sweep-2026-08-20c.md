# Open issues sweep 2026-08-20c — Batch CA test plan (#350)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20c-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-2026-08-20c` @ `wave/open-issues-sweep-2026-08-20c`
Authoring wave: **W1** (Batch CA RED) · Implementation: **W2.1** (`a2c76fd9`) · Recon: **W2.2**

Issue #350 out of scope (honoured — no tests): MCP Bearer/auth-header gaps (#345/#346); trust tiers / privilege drop (`analyzers/trust.py`, `utils/privilege.py`).

Do **not** cover W3 here (`mergecraft capabilities`, `SECURITY.md`).

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
