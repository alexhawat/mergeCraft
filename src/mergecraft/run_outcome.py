"""``RunOutcome`` taxonomy — the closed set of ways a run can end (D3, W5.1).

Six named values, no more, no less — the enum below is the taxonomy's only
definition; every other module imports it rather than re-declaring the
values. ``mergecraft.main`` re-exports it as ``mergecraft.main.RunOutcome``
so ``MainResult.outcome`` and this module agree on one symbol.

Mapping table (outcome -> check-run conclusion -> ``result`` output JSON):
this module ships the outcome -> check-conclusion half
(:data:`RUN_OUTCOME_CONCLUSION`); the outcome -> ``result`` JSON half lives
next to its only writer, ``cli/gha_cmd.py`` (W5.3), keyed by
:func:`error_code_for_outcome`. See ``docs/REVIEW-DOCTRINE.md`` ("Run
outcome taxonomy") for the operator-facing walkthrough of both halves.

CC1 adds a sibling outcome -> process exit-code table for the CLI machine
contract (:data:`RUN_OUTCOME_EXIT_CODE`, :func:`exit_code_for_outcome`).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final, Literal

from mergecraft.agents.gates import BLOCKING_SEVERITIES

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.analyzers.finding import Finding


class RunOutcome(StrEnum):
    """D3 — the closed run-outcome taxonomy. Exactly these six values."""

    passed = "passed"
    failed = "failed"
    inconclusive = "inconclusive"
    infra_error = "infra_error"
    timed_out = "timed_out"
    configuration_error = "configuration_error"


CompletionConclusion = Literal["success", "failure", "neutral", "timed_out"]
"""Valid GitHub check-run conclusions the ``mergecraft`` completion check
(``utils/status_checks.py:COMPLETION_CHECK``) may report for a ``RunOutcome``."""


# D3 mapping table, half one: outcome -> completion check-run conclusion.
# Only `passed` may ever produce `success` — every other outcome reports
# either the hard `failure` the agent itself declared, the literal
# `timed_out` GitHub conclusion, or a conservative `neutral` — so "infra
# never looks like success" (the pre-W5 invariant `run_succeeded: bool`
# encoded) holds for the whole taxonomy, not just the boolean it replaces.
# The sibling `mergecraft-approval` check stays governed by
# `agents.gates.decide_approval`'s existing 3-way conclusion; see
# `run_succeeded_for_outcome` below for how the two stay consistent.
RUN_OUTCOME_CONCLUSION: Final[dict[RunOutcome, CompletionConclusion]] = {
    RunOutcome.passed: "success",
    RunOutcome.failed: "failure",
    RunOutcome.timed_out: "timed_out",
    RunOutcome.infra_error: "neutral",
    RunOutcome.configuration_error: "neutral",
    RunOutcome.inconclusive: "neutral",
}

# CC1 — CLI process exit codes (one distinct code per ``RunOutcome`` value).
# ``RunOutcome.failed`` with blocking severities uses :data:`CLI_BLOCKED_EXIT_CODE`
# via :func:`exit_code_for_outcome` / :func:`cli_exit_code_for_review`.
RUN_OUTCOME_EXIT_CODE: Final[dict[RunOutcome, int]] = {
    RunOutcome.passed: 0,
    RunOutcome.failed: 12,
    RunOutcome.inconclusive: 20,
    RunOutcome.configuration_error: 30,
    RunOutcome.infra_error: 40,
    RunOutcome.timed_out: 50,
}

CLI_SUCCESS_EXIT_CODE: Final[int] = 0
CLI_USAGE_EXIT_CODE: Final[int] = 2
CLI_FINDINGS_EXIT_CODE: Final[int] = 10
CLI_BLOCKED_EXIT_CODE: Final[int] = 11


def run_succeeded_for_outcome(outcome: RunOutcome) -> bool:
    """Only ``passed`` counts as a succeeded run for the approval gate (D3).

    Feeds ``agents.gates.decide_approval`` / ``utils.status_checks.
    report_status_checks``'s pre-existing ``run_succeeded`` boolean, so every
    non-``passed`` outcome — ``inconclusive``, both error categories, and
    ``timed_out`` alike — is treated exactly like the pre-W5 "crashed run"
    case: ``neutral`` at best, never ``success`` (approval-gate semantics
    for non-``passed`` outcomes stay conservative, per D3).
    """
    return outcome is RunOutcome.passed


def error_code_for_outcome(outcome: RunOutcome) -> str:
    """Stable, machine-readable error code for the ``result`` output JSON (W5.3).

    Stable means: the code is a pure function of the outcome value, never of
    the (unstable, free-text) error message — a consumer can branch on it
    without string-matching prose.
    """
    return f"mergecraft.{outcome.value}"


def exit_code_for_outcome(
    outcome: RunOutcome,
    *,
    blocked: bool = False,
    findings_only: bool = False,
) -> int:
    """Map a ``RunOutcome`` to a distinct CLI process exit code (CC1).

    ``RunOutcome.failed`` with blocking severities uses :data:`CLI_BLOCKED_EXIT_CODE`
    so merge gates can distinguish blockers from non-blocking findings.
    Non-blocking findings use :data:`CLI_FINDINGS_EXIT_CODE` (10); bare ``failed``
    outcomes use :data:`RUN_OUTCOME_EXIT_CODE` (12).
    """
    if outcome is RunOutcome.failed:
        if blocked:
            return CLI_BLOCKED_EXIT_CODE
        if findings_only:
            return CLI_FINDINGS_EXIT_CODE
    return RUN_OUTCOME_EXIT_CODE[outcome]


def cli_exit_code_for_review(
    outcome: RunOutcome,
    findings: Sequence[Finding] | None = None,
) -> int:
    """Resolve the CLI exit code for a completed offline review (CC1)."""
    rows = list(findings or [])
    if rows and any(row.severity in BLOCKING_SEVERITIES for row in rows):
        return exit_code_for_outcome(RunOutcome.failed, blocked=True)
    if rows and outcome is RunOutcome.passed:
        return exit_code_for_outcome(RunOutcome.failed, findings_only=True)
    return exit_code_for_outcome(outcome)


__all__ = [
    "CLI_BLOCKED_EXIT_CODE",
    "CLI_FINDINGS_EXIT_CODE",
    "CLI_SUCCESS_EXIT_CODE",
    "CLI_USAGE_EXIT_CODE",
    "RUN_OUTCOME_CONCLUSION",
    "RUN_OUTCOME_EXIT_CODE",
    "CompletionConclusion",
    "RunOutcome",
    "cli_exit_code_for_review",
    "error_code_for_outcome",
    "exit_code_for_outcome",
    "run_succeeded_for_outcome",
]
