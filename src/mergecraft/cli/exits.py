"""Named CLI process exit codes (D11 / #341).

Import these constants instead of bare integers in ``typer.Exit(...)`` under
``src/mergecraft/cli/``. Review outcomes reuse :func:`exit_code_for_outcome` /
:func:`cli_exit_code_for_review` from ``mergecraft.run_outcome``; non-review
commands use the ``CLI_*`` aliases below. See ``docs/EXIT-CODES.md`` for the
full table.
"""

from __future__ import annotations

from typing import Final

from mergecraft.run_outcome import (
    CLI_BLOCKED_EXIT_CODE,
    CLI_FINDINGS_EXIT_CODE,
    RUN_OUTCOME_EXIT_CODE,
    RunOutcome,
    cli_exit_code_for_review,
    error_code_for_outcome,
    exit_code_for_outcome,
)

CLI_SUCCESS_EXIT_CODE: Final[int] = 0
CLI_USAGE_EXIT_CODE: Final[int] = 2

CLI_CONFIGURATION_EXIT_CODE: int = RUN_OUTCOME_EXIT_CODE[RunOutcome.configuration_error]
CLI_FAILED_EXIT_CODE: int = RUN_OUTCOME_EXIT_CODE[RunOutcome.failed]
CLI_INCONCLUSIVE_EXIT_CODE: int = RUN_OUTCOME_EXIT_CODE[RunOutcome.inconclusive]
CLI_INFRA_EXIT_CODE: int = RUN_OUTCOME_EXIT_CODE[RunOutcome.infra_error]
CLI_TIMEOUT_EXIT_CODE: int = RUN_OUTCOME_EXIT_CODE[RunOutcome.timed_out]

__all__ = [
    "CLI_BLOCKED_EXIT_CODE",
    "CLI_CONFIGURATION_EXIT_CODE",
    "CLI_FAILED_EXIT_CODE",
    "CLI_FINDINGS_EXIT_CODE",
    "CLI_INCONCLUSIVE_EXIT_CODE",
    "CLI_INFRA_EXIT_CODE",
    "CLI_SUCCESS_EXIT_CODE",
    "CLI_TIMEOUT_EXIT_CODE",
    "CLI_USAGE_EXIT_CODE",
    "RUN_OUTCOME_EXIT_CODE",
    "RunOutcome",
    "cli_exit_code_for_review",
    "error_code_for_outcome",
    "exit_code_for_outcome",
]
