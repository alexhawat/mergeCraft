# Open issues sweep 2026-08-20 — Batch AC test plan (#340)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-2026-08-20` @ `wave/open-issues-sweep-2026-08-20`
Authoring wave: **W6** (Batch AC RED) · Implementation: **W7** (#340 completion + consoles)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W7** | `test_show_completion_exits_zero` | `green after W7: completion + stderr consoles` | pending — **XFAIL** (`add_completion=False`; exit 2) |
| **W7** | `test_json_stdout_is_strict_while_chrome_enabled` | `green after W7: completion + stderr consoles` | pending — **XFAIL** (recall gate chrome appended to stdout) |
| **W7** | `test_no_bare_stdout_console_in_cli_module` | `green after W7: completion + stderr consoles` | pending — **XFAIL** (~19 bare `Console()` sites) |

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| AC340a | Root Typer app exposes shell completion (`--show-completion` exits 0) | functional | happy | `tests/cli/test_cli_shell_ac.py::test_show_completion_exits_zero` |
| AC340b | `--json` stdout is strictly JSON while Rich chrome is enabled | functional | error path — recall gate after JSON payload | `test_json_stdout_is_strict_while_chrome_enabled` |
| AC340c | AST scan rejects `Console(...)` without `stderr=True` under `src/mergecraft/cli/` | unit | lint guard | `test_no_bare_stdout_console_in_cli_module` |
| AC340d | Scanner accepts `Console(stderr=True)` and flags bare `Console()` | unit | parametrized | `test_find_cli_console_violations_parametrized` |

## W6 notes

- **#340 RED:** `cli/app.py:43` still sets `add_completion=False`. Live code has ~19 `Console(` sites under `src/mergecraft/cli/` without `stderr=True` (D14 baseline @ `236f1444`).
- **JSON pin:** `eval score … --json --min-recall 0.5` with zero findings emits valid JSON then appends a Rich recall failure line on stdout via bare `console.print` (`eval_cmd.py` post-echo path). Chrome-enabled env uses `TERM=xterm-256color` and omits `NO_COLOR`.
- **Scanner:** `find_cli_console_violations()` lives in the test module for W6; W7 may extract to `scripts/check_cli_consoles.py` and wire `make lint`. Shared `out_console` / `err_console` allowlist is W7 scope.
- **D14:** Data on stdout, chrome on stderr; lint blocks ad-hoc stdout consoles in `cli/`.

## Acceptance (W6)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- Three contract tests **XFAIL** until W7; parametrized scanner test passes
- No `src/` edits; no D6 paths
