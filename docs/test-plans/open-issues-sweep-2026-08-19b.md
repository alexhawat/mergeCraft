# Open issues sweep 2026-08-19b — Batch G test plan

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-19b-wave-plan.md`
Worktree: `../mergecraft-issues-sweep-2026-08-19b` @ `wave/issues-sweep-2026-08-19b`
Authoring wave: **W1** (Batch G RED). Implementation: **W3** (#277), **W4** (#278).

W1 pins #277 (xdist flake on grandchild reap) and #278 (`MERGECRAFT_LIVE=1` opt-in)
without changing production code. D6-forbidden paths are not touched.

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W3** | `test_setup_script_grandchildren_are_reaped` | `green after W3: #277 wait for pid_file before kill clock` | pending — deterministic RED: readiness file delayed past `wait_or_kill(..., timeout=0.5)` |
| **W4** | `test_live_module_skips_when_mergecraft_live_unset` (6 cases) | `green after W4: MERGECRAFT_LIVE skip gate` | pending |

No xfail on:

- `_wait_until_exists` / `_record_pid_reaped` helper units (green now; W3 reuses them)
- `test_live_module_fails_when_flag_set_without_credentials` (D8 fail-closed already holds)

## Contract matrix

### #277 / D12 — grandchild reap without a 0.5s spawn window

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| G277a | Readiness poll is independent of the 0.5s kill clock | unit | happy — file appears at 0.8s | `tests/config/test_setup_script_timeout.py::test_wait_until_exists_does_not_assume_half_second_grace` |
| G277b | Missing readiness file is not ready | unit | edge — never written | `test_wait_until_exists_returns_false_when_file_never_appears` |
| G277c | Reap recording takes an explicit deadline | unit | happy / edge — `sleep 10` still alive after 0.25s | `test_record_pid_reaped_deadline_is_independent_of_wait_or_kill_timeout` |
| G277d | Non-positive reap deadline is rejected | unit | error — `0` / `-1` | `test_record_pid_reaped_rejects_non_positive_deadline` |
| G277e | Kill-before-readiness fails deterministically | functional | error — old timing | `test_setup_script_grandchildren_are_reaped` (xfail until W3) |

W3 greens G277e by calling `_wait_until_exists(pid_file)` **before** `wait_or_kill_process_group`. Do not mock `kill_process_group`.

### #278 / D8 — live opt-in

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| G278a | Unset / empty / `"0"` → skip, not fail | functional | happy + edge | `tests/ci/test_live_opt_in.py::test_live_module_skips_when_mergecraft_live_unset` |
| G278b | `MERGECRAFT_LIVE=1` + no creds → fail | functional | error (D9 preserved) | `test_live_module_fails_when_flag_set_without_credentials` |

Both live modules are parametrized:

- `tests/integration/test_live_providers.py`
- `tests/integration/test_github_integration.py`

Child pytest runs with credentials stripped so a developer laptop with keys cannot accidentally hit a provider.

## W1.1 note

Deterministic RED, not inspection-only. The grandchild script delays the pid-file write by 1s so `wait_or_kill(..., timeout=0.5)` expires before readiness. Helpers `_wait_until_exists` and `_record_pid_reaped` have no 0.5s default.

## Acceptance (W1)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- G277 helper units pass; G277e xfail; G278a xfail; G278b pass
- No `src/` edits; no D6 paths
