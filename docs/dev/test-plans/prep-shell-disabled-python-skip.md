# Prep — `shell: disabled` Python skip is not an install failure

Regression for the live Action failure where a completed Nous review of a
Python repo never posted `mergecraft-approval` because
`InstallPythonDependencies` skipped under `shell: disabled` (this repo's
`.github/workflows/mergecraft.yml` always does) and that skip was treated as
`status="failed"`, then mapped to `RunOutcome.inconclusive`.

Live: https://github.com/alexhawat/mergeCraft/actions/runs/31946428769/job/95163172432

Log: `prep failure mapped run to inconclusive: skipped: python dependency
installation can execute arbitrary code ... which is blocked when shell is
disabled`

W6.1 fail-closed for a **real** install failure is unchanged — see
`tests/prep/test_prep_fail_closed.py` (`test_prep_failure_makes_run_inconclusive`
and `test_prep_failure_reason_is_recorded`). These tests add the skip-not-failure
counterpart; they do not weaken that suite.

Worktree: `../mergecraft-agent-pipeline-ap1` @ `feature/agent-pipeline`

## Contract

| Surface | Skip (`ignore_scripts` / `shell: disabled`) | Real install failure |
|---------|----------------------------------------------|----------------------|
| `PrepResult` | `skipped=True`, `dependencies_installed=False`; issues may describe the skip | `skipped=False`, issues non-empty, not installed |
| `is_prep_install_failure` | `False` | `True` |
| `start_installation` done-callback | `status="completed"` | `status="failed"` |
| `_format_prep_results` | `"installation skipped"` | `"installation failed"` |
| `_prep_failure_reason` / run outcome | no reason; run is **not** `inconclusive` | reason recorded; run is `inconclusive` |

## Contract → coverage matrix

### `tests/prep/test_types.py`

| Test | Layer | Scenario | Contract |
|------|-------|----------|----------|
| `test_is_prep_install_failure[skipped_with_issues]` | unit | happy / guard-deletion | Skip with issues → False (fails if the `skipped` short-circuit is deleted) |
| `test_is_prep_install_failure[failed_install]` | unit | error (W6.1) | Not skipped, not installed, issues → True |
| `test_is_prep_install_failure[successful_install]` | unit | happy | Installed → False |
| `test_is_prep_install_failure[skipped_empty_issues]` | unit | edge | Skip with empty issues → False |
| `test_is_prep_install_failure[installed_with_issues]` | unit | edge | Installed even with leftover issues → False |
| `test_is_prep_install_failure[not_installed_empty_issues]` | unit | edge | Not installed, empty issues, not skipped → False |
| `test_prep_result_skipped_defaults_false` | unit | edge | `PrepResult.skipped` defaults to `False` |

### `tests/prep/test_python.py`

| Test | Layer | Scenario | Contract |
|------|-------|----------|----------|
| `test_install_python_dependencies_skip_when_ignore_scripts` | unit | happy | `uv.lock` + `PrepOptions(ignore_scripts=True)` → `skipped=True`, `dependencies_installed=False` |

### `tests/mcp/test_dependencies.py`

| Test | Layer | Scenario | Contract |
|------|-------|----------|----------|
| `test_format_prep_results_skip_is_not_installation_failed` | unit | happy / guard-deletion | Formatter wording is "installation skipped", never "installation failed" |
| `test_format_prep_results_real_failure_still_says_failed` | unit | error (W6.1) | Genuine pip failure still says "installation failed" |
| `test_start_installation_skip_only_completes_not_failed` | unit | happy / guard-deletion | Skip-only → `status="completed"`; `ignore_scripts=True` when `shell: disabled` |
| `test_start_installation_real_failure_still_sets_failed` | unit | error (W6.1) | Real install failure still → `status="failed"` |

### `tests/prep/test_prep_fail_closed.py` (skip counterpart; existing fail-closed tests unchanged)

| Test | Layer | Scenario | Contract |
|------|-------|----------|----------|
| `test_python_skip_prep_does_not_make_run_inconclusive` | integration | happy | `prep_skip=True` through `main()` is not `inconclusive` |
| `test_prep_failure_reason_none_for_python_skip_only` | integration | happy | `_prep_failure_reason` is `None` for skip-only `status="completed"` |
| `test_prep_failure_reason_excludes_skipped_python_install` | integration | guard-deletion + W6.1 | Mixed skip + node failure: reason is the npm error, never the skip text |
| `test_prep_failure_makes_run_inconclusive` (existing) | integration | error | Do not weaken — genuine prep failure still maps the run to `inconclusive` |

## Status

Bugfix characterisation — tests are written to **pass against current `src/`**.
A genuine pip/npm failure must still fail closed (rows above marked W6.1, and
the existing tests in `tests/prep/test_prep_fail_closed.py`).
