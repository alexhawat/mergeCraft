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
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal


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


__all__ = [
    "RUN_OUTCOME_CONCLUSION",
    "CompletionConclusion",
    "RunOutcome",
    "error_code_for_outcome",
    "run_succeeded_for_outcome",
]
