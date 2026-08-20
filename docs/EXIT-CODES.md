# CLI exit codes

Every `mergecraft` CLI command exits with a named process exit code. Review
outcomes reuse the `RunOutcome` taxonomy via `exit_code_for_outcome` /
`cli_exit_code_for_review`; other commands import constants from
`mergecraft.cli.exits` (re-exported from `mergecraft.run_outcome`).

**Breaking change (pre-0.0.1):** scripts that branched on exit code `1` for
generic CLI failures must follow this table instead. Usage / operator-input
errors now exit `2`. Most former `1` paths exit `30` (configuration) unless
documented otherwise below.

## Success and usage

| Code | Constant | When |
|------|----------|------|
| `0` | `CLI_SUCCESS_EXIT_CODE` | Command completed successfully (including `--version`, successful auth writes, empty config validation). |
| `2` | `CLI_USAGE_EXIT_CODE` | Invalid CLI flags or arguments (Typer usage errors, unknown `--scope`, bad `--format`, malformed input). |

## Review outcomes (`mergecraft review`)

These codes apply to `mergecraft review` and the hidden `diff-review` alias.

| Code | Constant / helper | `RunOutcome` | When |
|------|-------------------|--------------|------|
| `0` | `exit_code_for_outcome(passed)` | `passed` | Clean pass — no blocking findings. |
| `10` | `CLI_FINDINGS_EXIT_CODE` | `failed` (findings only) | Non-blocking findings on an otherwise successful review. |
| `11` | `CLI_BLOCKED_EXIT_CODE` | `failed` (blocked) | Blocking-severity findings — merge gate should fail. |
| `12` | `CLI_FAILED_EXIT_CODE` | `failed` | Review failed without classified findings. |
| `20` | `CLI_INCONCLUSIVE_EXIT_CODE` | `inconclusive` | Review could not reach a verdict. |
| `30` | `CLI_CONFIGURATION_EXIT_CODE` | `configuration_error` | Invalid repo config, missing required paths, or other setup errors. |
| `40` | `CLI_INFRA_EXIT_CODE` | `infra_error` | Provider / credential / runtime infrastructure failure. |
| `50` | `CLI_TIMEOUT_EXIT_CODE` | `timed_out` | Run exceeded its budget or wall-clock timeout. |

## Other commands

Non-review commands that fail after argument parsing typically exit
`CLI_CONFIGURATION_EXIT_CODE` (`30`) unless the failure is clearly a usage
error (`2`) or matches a review-style outcome when a subcommand delegates to
review logic.

Examples:

- `mergecraft auth codex --scope everywhere` → `2` (unknown `--scope`)
- `mergecraft findings export --format xml` → `2` (unsupported `--format`)
- `mergecraft doctor` with a missing dependency → `30` (configuration / environment)
- `mergecraft config validate` with a YAML schema error → `30`

## Implementation notes

- No bare integer literals in `typer.Exit(...)` under `src/mergecraft/cli/`.
  Import from `mergecraft.cli.exits`.
- `CLI_USAGE_EXIT_CODE` is reserved for operator-input mistakes; Typer may also
  emit `2` for its own usage errors before a command handler runs.
- GitHub Actions consumers should prefer structured `--format json` output and
  the documented codes above over parsing stderr text.

See also: README review examples (exit-code summary), `docs/REVIEW-DOCTRINE.md`
("Run outcome taxonomy").
