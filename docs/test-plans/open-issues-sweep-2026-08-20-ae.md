# Open issues sweep 2026-08-20 — Batch AE test plan (#342)

Wave plan: `.ignorelocal/waves/open-issues-sweep-2026-08-20-wave-plan.md`
Worktree: `../mergecraft-open-issues-sweep-2026-08-20` @ `wave/open-issues-sweep-2026-08-20`
Authoring wave: **W10** (Batch AE RED) · Implementation: **W11** (#342 root callback + docs)

## xfail schedule

| Wave | Test | Marker reason | Status |
|------|------|---------------|--------|
| **W11** | `test_root_help_lists_global_format_flag` | `green after W11: global CLI surface` | pending — **XFAIL** (no root `--format`) |
| **W11** | `test_root_help_lists_global_verbosity_and_color_flags[--quiet]` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_root_help_lists_global_verbosity_and_color_flags[--verbose]` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_root_help_lists_global_verbosity_and_color_flags[--log-level]` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_root_help_lists_global_verbosity_and_color_flags[--color]` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_global_format_json_inherited_by_eval_score` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_json_payload_includes_schema_version[global-format]` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_json_payload_includes_schema_version[legacy-json-flag]` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_color_contract_suppresses_ansi_in_help[no-color-1]` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_color_contract_suppresses_ansi_in_help[no-color-any-nonempty]` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_color_contract_suppresses_ansi_in_help[color-never]` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_non_tty_emits_zero_ansi_in_help` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_force_color_enables_ansi_on_dumb_tty` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_log_level_debug_shows_init_debug_message` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_quiet_suppresses_loguru_info_on_review_dry_run` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_verbose_shows_loguru_debug_on_init` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_mergecraft_log_level_env_overrides_default_quietness` | `green after W11: global CLI surface` | pending — **XFAIL** |
| **W11** | `test_diff_review_hidden_alias_emits_one_stderr_deprecation_line` | `green after W11: global CLI surface` | pending — **XFAIL** |

## Contract matrix

| # | Contract | Layer | Scenario | Primary test |
|---|----------|-------|----------|--------------|
| AE342a | Root exposes global `--format {table,json}` (D12) | functional | help | `tests/cli/test_cli_global_surface_ae.py::test_root_help_lists_global_format_flag` |
| AE342b | Root documents `--quiet` / `--verbose` / `--log-level` / `--color` | functional | help | `test_root_help_lists_global_verbosity_and_color_flags` |
| AE342c | Global format switch is `--format`, not root `--output` | functional | help guard | `test_root_help_does_not_use_output_as_global_format_switch` |
| AE342d | Root `--format json` inherited by subcommands | functional | happy — eval score | `test_global_format_json_inherited_by_eval_score` |
| AE342e | JSON payloads carry `schema_version` | functional | global + legacy `--json` | `test_json_payload_includes_schema_version` |
| AE342f | `NO_COLOR` (any non-empty) suppresses ANSI | functional | help chrome | `test_color_contract_suppresses_ansi_in_help[no-color-*]` |
| AE342g | `--color never` suppresses ANSI | functional | help chrome | `test_color_contract_suppresses_ansi_in_help[color-never]` |
| AE342h | Non-TTY emits zero ANSI | functional | CliRunner default | `test_non_tty_emits_zero_ansi_in_help` |
| AE342i | `FORCE_COLOR` re-enables ANSI on dumb TERM | functional | edge | `test_force_color_enables_ansi_on_dumb_tty` |
| AE342j | `--log-level DEBUG` reconfigures Loguru before subcommands | functional | init debug log | `test_log_level_debug_shows_init_debug_message` |
| AE342k | `--quiet` suppresses Loguru INFO lines | functional | review dry-run | `test_quiet_suppresses_loguru_info_on_review_dry_run` |
| AE342l | `--verbose` enables DEBUG Loguru records | functional | init debug log | `test_verbose_shows_loguru_debug_on_init` |
| AE342m | `MERGECRAFT_LOG_LEVEL` env honoured | functional | init debug log | `test_mergecraft_log_level_env_overrides_default_quietness` |
| AE342n | `review` visible; `diff-review` hidden in root help (D13) | functional | help | `test_review_is_documented_and_diff_review_hidden_in_root_help` |
| AE342o | Hidden `diff-review` emits one stderr deprecation line (D13) | functional | alias invoke | `test_diff_review_hidden_alias_emits_one_stderr_deprecation_line` |

## W10 notes

- **#342 RED:** `cli/app.py` root callback only exposes `--version`; no global `--format`, `--quiet`, `--verbose`, `--log-level`, or `--color`. `NO_COLOR=1` does not suppress Typer/Rich ANSI on `--help` @ W10 baseline (`078ad0fd`). Loguru is configured at import time — CLI flags cannot reconfigure it yet. `eval score --json` emits eight metric keys with no `schema_version`. `diff-review` is hidden but emits no deprecation stderr line.
- **Already green:** Root help lists `review` and omits `diff-review`; root help has no global `--output` format switch (D12 negative guard).
- **D7 gate:** AC complete @ `34939ada` / `0c8ebab6` — AE unblocked.
- **D12 / D13:** Global `--format {table,json}`; keep `review --json PATH` alias; purge `diff-review` from docs in W11.2 (out of W10 scope).

## Acceptance (W10)

- New tests collect with zero import errors
- `make lint` + `make typecheck` clean on touched paths
- Eighteen contract tests **XFAIL** until W11; two guard/help tests pass
- No `src/` edits; no D6 paths
