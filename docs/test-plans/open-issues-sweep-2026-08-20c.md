# Open issues sweep 2026-08-20c — Batch CA test plan (#350)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20c-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-2026-08-20c` @ `wave/open-issues-sweep-2026-08-20c`
Authoring wave: **W1** (Batch CA RED) · Implementation: **W2** (#350 drop write modes + workspace RO)

Issue #350 out of scope (honoured — no tests): MCP Bearer/auth-header gaps (#345/#346); trust tiers / privilege drop (`analyzers/trust.py`, `utils/privilege.py`).

Do **not** cover W3 here (`mergecraft capabilities`, `SECURITY.md`).

## xfail schedule

All cross-wave markers use `@pytest.mark.xfail(..., strict=False)`.

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W2** | `test_production_registry_excludes_write_capable_modes` | `green after W2: review-only production boundary (#350)` | pending — **XFAIL** |
| **W2** | `test_compute_modes_excludes_write_capable_modes` | same | pending — **XFAIL** |
| **W2** | `test_static_modes_export_excludes_write_capable_modes` | same | pending — **XFAIL** |
| **W2** | `test_select_mode_rejects_write_capable_names[*]` | same | pending — **XFAIL** (5 names) |
| **W2** | `test_custom_config_cannot_reenable_write_capable_fix` | same (D12) | pending — **XFAIL** |
| **W2** | `test_reviewer_shaped_run_cannot_edit_tracked_file[*]` | same | pending — **XFAIL** (Review, IncrementalReview) |
| **W2** | `test_reviewer_shaped_run_cannot_git_commit[*]` | same | pending — **XFAIL** |
| **W2** | `test_reviewer_shaped_run_cannot_git_push[*]` | same | pending — **XFAIL** |
| **W2** | `test_reviewer_shaped_run_cannot_open_code_changing_pr[*]` | same | pending — **XFAIL** |

## W1.1 current-state pins (green; recon after W2 should remove or invert)

These document Finding 1 on `a2e3944d`. They **pass today**. After W2 they will fail until recon deletes them (W2.2).

| Test | What it pins |
|------|----------------|
| `test_production_registry_still_lists_write_capable_modes` | `_MODE_DEFS` includes Build, AddressReviews, Fix, ResolveConflicts, Task |
| `test_compute_modes_still_exposes_write_capable_modes` | `compute_modes` still returns those names |
| `test_static_modes_export_still_includes_fix` | `modes` still lists `Fix` |
| `test_write_mode_modules_remain_importable_as_negative_fixtures` | D12: `modes/Fix.py` (and siblings) stay importable |
| `test_select_mode_still_accepts_write_capable_names[*]` | `select_mode` still resolves write-capable built-ins |

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| CA350a | Production `_MODE_DEFS` still has write modes (baseline) | unit | happy / current | `tests/modes/test_review_only_boundary.py::test_production_registry_still_lists_write_capable_modes` |
| CA350b | After W2, `_MODE_DEFS` is review-only (D12) | unit | happy | `test_production_registry_excludes_write_capable_modes` |
| CA350c | After W2, `compute_modes` / `modes` leak no write names | unit | happy | `test_compute_modes_excludes_write_capable_modes`, `test_static_modes_export_excludes_write_capable_modes` |
| CA350d | After W2, `select_mode` rejects write-capable names | integration | error | `test_select_mode_rejects_write_capable_names` |
| CA350e | Empty/unknown `select_mode` is existing behaviour (not this file) | — | — | existing `select_mode` tests if any; W1 does not restyle them |
| CA350f | Repo config cannot re-enable `Fix` (D12) | integration | error | `test_custom_config_cannot_reenable_write_capable_fix` |
| CA350g | Reviewer-shaped run cannot edit a tracked file | functional | error + edge (file unchanged) | `test_reviewer_shaped_run_cannot_edit_tracked_file` |
| CA350h | Reviewer-shaped run cannot `git commit` (`commit_changes`) | functional | error | `test_reviewer_shaped_run_cannot_git_commit` |
| CA350i | Reviewer-shaped run cannot `git push` (`push_branch`) | functional | error | `test_reviewer_shaped_run_cannot_git_push` |
| CA350j | Reviewer-shaped run cannot open a code-changing PR | functional | error | `test_reviewer_shaped_run_cannot_open_code_changing_pr` |
| CA350k | `git` MCP tool still does not forward `commit` | unit | already green | `test_git_mcp_tool_does_not_forward_commit` |

Write-capable names under test: `Build`, `AddressReviews`, `Fix`, `ResolveConflicts`, `Task`.
Reviewer-shaped modes: `Review`, `IncrementalReview`.
Kept production modes after W2: `Review`, `IncrementalReview`, `Plan`.

Error contract for W2 negatives: `ToolResult.is_error is True` and the message contains **`review-only`** (plus `commit` / `push` where those verbs apply). `create_pull_request` must not call `scm.post`. `commit_changes` / `push_branch` must not invoke `_run_git` with those verbs.

## Recon notes (W2.2)

- Un-xfail every `green after W2` marker in `tests/modes/test_review_only_boundary.py`.
- Delete the W1.1 current-state pins (CA350a / still-accepts `select_mode`).
- Update `tests/test_modes.py` `EXPECTED_MODE_NAMES` (still lists write modes today). W2 impl cannot edit `tests/`; recon owns that follow-up.

## Acceptance (W1)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean
- Current-state pins **pass**; W2 negatives **XFAIL** (`strict=False`)
- No `src/` edits; no D6 paths (README, `AGENTS.md`, tracing exporters, `cli/app.py` root callback)
