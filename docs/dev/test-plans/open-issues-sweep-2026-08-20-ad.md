# Open issues sweep 2026-08-20 — Batch AD test plan (#341)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-2026-08-20` @ `wave/open-issues-sweep-2026-08-20`
Authoring wave: **W8** (Batch AD RED) · Implementation: **W9** (#341 named exits + `docs/EXIT-CODES.md`)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W9** | `test_no_bare_integer_typer_exit_in_cli_module` | `green after W9: named exit constants + EXIT-CODES.md` | **green** @ W9 |
| **W9** | `test_cli_usage_exit_code_constant_is_two` | `green after W9: named exit constants + EXIT-CODES.md` | **green** @ W9 |
| **W9** | `test_cli_exit_code_contract_pins[usage_error-2-auth_invalid_scope]` | `green after W9: named exit constants + EXIT-CODES.md` | **green** @ W9 |

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| AD341a | Clean review (`RunOutcome.passed`) exits 0 | functional | happy | `tests/cli/test_cli_exit_codes_ad.py::test_cli_exit_code_contract_pins[clean_pass-0-review_passed]` |
| AD341b | Blocking findings exit 11 | functional | error — merge gate | `test_cli_exit_code_contract_pins[blocking_findings-11-review_blocked]` |
| AD341c | Missing credential / infra (`RunOutcome.infra_error`) exits 40 | functional | error — credential / provider | `test_cli_exit_code_contract_pins[missing_credential_infra-40-review_infra]` |
| AD341d | Timeout (`RunOutcome.timed_out`) exits 50 | functional | error — run budget | `test_cli_exit_code_contract_pins[timeout-50-review_timeout]` |
| AD341e | Usage / operator-input errors exit 2 | functional | error — invalid CLI input | `test_cli_exit_code_contract_pins[usage_error-2-auth_invalid_scope]` |
| AD341f | `exit_code_for_outcome` table matches D11 pins | unit | parametrized | `test_run_outcome_exit_code_contract_pins` |
| AD341g | `CLI_USAGE_EXIT_CODE == 2` exported from `run_outcome` | unit | constant | `test_cli_usage_exit_code_constant_is_two` |
| AD341h | AST scan rejects bare `typer.Exit(N)` under `src/mergecraft/cli/` | unit | lint guard | `test_no_bare_integer_typer_exit_in_cli_module` |
| AD341i | Scanner accepts named exit variables | unit | parametrized | `test_find_cli_bare_exit_violations_parametrized` |

## W8 notes

- **#341 RED:** Live `src/mergecraft/cli/` still has 61 `typer.Exit(<int-literal>)` sites (AST scan @ W8). No `docs/EXIT-CODES.md`. `CLI_USAGE_EXIT_CODE` not yet defined; invalid `auth --scope` uses `_bail` → exit 1.
- **Review pins already green:** `RunOutcome` → exit mapping and offline `review` CLI paths for 0 / 11 / 40 / 50 are implemented (`run_outcome.py`, `diff_review_cmd.py`); CC1 coverage in `tests/cli/test_exit_codes.py` overlaps but W8 adds the D11 parametrized table + bare-exit lint.
- **Scanner:** `find_cli_bare_exit_violations()` lives in the W8 test module; W9 may extract to `scripts/check_cli_exits.py` and wire `make lint`.
- **D11:** Reuse `RunOutcome` / `exit_code_for_outcome`; reserve 2 for usage error; no bare integer in `typer.Exit(...)` under `cli/`.

## Acceptance (W8)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- Three contract tests **XFAIL** until W9; unit + review functional pins pass
- No `src/` edits; no D6 paths
