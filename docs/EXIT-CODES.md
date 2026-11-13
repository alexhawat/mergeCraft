# CLI exit codes

Every `mergecraft` CLI command exits with a named process exit code. Review
outcomes reuse the `RunOutcome` taxonomy via `exit_code_for_outcome` /
`cli_exit_code_for_review` from `mergecraft.run_outcome`; general CLI codes
(`CLI_SUCCESS_EXIT_CODE`, `CLI_USAGE_EXIT_CODE`) and review aliases live in
`mergecraft.cli.exits`. See this table for the full mapping.

Scripts that branched on exit code `1` for generic CLI failures must follow
this table instead: usage and operator-input errors exit `2`, and most former
`1` paths exit `30` (configuration). Code `1` remains only for the failed
verification row below.

## Success and usage

| Code | Constant | When |
|------|----------|------|
| `0` | `CLI_SUCCESS_EXIT_CODE` | Command completed successfully (including `--version`, successful auth writes, empty config validation). |
| `1` | `CLI_AUDIT_VERIFY_FAILED_EXIT_CODE` | A verification found a problem: `audit verify` (broken or unreadable chain), `verify-behavior` (blocked or failed), `opencode doctor --strict` (a failed check). |
| `2` | `CLI_USAGE_EXIT_CODE` | Invalid CLI flags or arguments (Typer usage errors, unknown `--scope`, bad `--format`, malformed input), an unknown id (`agent show`, `lens show`, `analyzers explain`, `memory show`, `eval replay`, `evidence show`, `requirements explain`, `explain`), and root `--format json` on a command with no JSON output. |

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

Findings refine only an outcome the review reached: `10` and `11` apply when the
outcome is `passed` or `failed`. An `inconclusive`, `configuration_error`,
`infra_error` or `timed_out` run keeps its own code even when analyzer or
reviewer findings include blockers.

## Other commands

Non-review commands that fail after argument parsing typically exit
`CLI_CONFIGURATION_EXIT_CODE` (`30`) unless the failure is clearly a usage
error (`2`) or matches a review-style outcome when a subcommand delegates to
review logic.

Examples:

The `eval` examples require a source checkout. Installed packages omit that
maintainer command and return usage error `2` if it is invoked.

- `mergecraft auth codex --scope everywhere` → `2` (unknown `--scope`)
- `mergecraft findings export --output-format xml` → `2` (unsupported `--output-format`)
- `mergecraft lens show no-such-lens` → `2` (unknown id)
- `mergecraft --format json doctor` → `2` (`doctor` has no JSON output)
- `mergecraft eval gate --bank no-such-dir` → `30` (an explicit bank must exist)
- `mergecraft eval replay` with a verdict regression → `12` (`CLI_FAILED_EXIT_CODE`)
- `mergecraft doctor` with a missing dependency → `30` (configuration / environment)
- `mergecraft config validate` with a YAML schema error → `30`

## Implementation notes

- No bare integer literals in `typer.Exit(...)` under `src/mergecraft/cli/`.
  Import from `mergecraft.cli.exits`.
- `CLI_USAGE_EXIT_CODE` is reserved for operator-input mistakes; Typer may also
  emit `2` for its own usage errors before a command handler runs.
- GitHub Actions consumers should prefer structured `--output-format json` (or root
  `--format json`) and the documented codes above over parsing stderr text.
- Default `mergecraft review` human text is written to stderr; stdout stays
  reserved for `--agent` JSONL. Capture text with `2>`, not `>`.

See also: README review examples (exit-code summary), `docs/REVIEW-DOCTRINE.md`
("Run outcome taxonomy").
