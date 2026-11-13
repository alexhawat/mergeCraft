"""One run-outcome resolver shared by the Action and the offline review (#SM1, #SM9).

Module: mergecraft.review.outcome_resolution
Depends: mergecraft.main_outcome, mergecraft.run_outcome, mergecraft.utils.run_bounds

Exports:
    Classes:
        OutcomeInputs — Every run-level input the outcome of one run depends on.
    Functions:
        resolve_run_outcome — Map one run's ``OutcomeInputs`` to a ``RunOutcome`` and reason.
        roster_failure_from_result — Read a required reviewer's failure off a result.
        structured_output_error — Why a required ``set_output`` payload is unusable.
        approval_withheld_reason — Why a formal APPROVE must not be posted for a run.
        finalize_run_outcome — Apply the disposition-ledger downgrade after publication.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.run_outcome import RunOutcome, outcome_with_disposition_ledger

if TYPE_CHECKING:
    from mergecraft.action.inputs import SetupFailurePolicy
    from mergecraft.agents.shared import AgentResult
    from mergecraft.evidence.packet import MergeEvidencePacket
    from mergecraft.modes import Mode
    from mergecraft.utils.run_bounds import BudgetExhausted


@dataclass(frozen=True, slots=True)
class OutcomeInputs:
    """Every run-level input :func:`resolve_run_outcome` reads.

    The Action (``main._finalize``) and the offline review
    (``review.offline_agent``) both build one of these, so the same run state
    resolves to the same outcome on either path. Publication inputs default to
    "not applicable" (``None``): the offline path never publishes, and the
    Action resolves once before publishing (to decide whether an APPROVE may be
    posted) and once after (with the receipt).

    Attributes:
        result: The driver result after post-run finalize and the roster fold.
        mode: The selected mode (``None`` for a lite run or a modeless run).
        verdict_protocol: ``enforce`` or ``shadow``.
        setup_reason: Trusted-tier setup-script failure text, empty when none.
        setup_policy: The closed ``setupFailurePolicy`` value.
        prep_reason: Review-relevant dependency-prep failure, if any.
        final_summary_written: Whether an IncrementalReview wrote its summary.
        terminal_publication_failed: Whether every publish attempt failed.
        terminal_publication_receipt: Whether a receipt proves publication.
        terminal_publication_mismatch: ``(published, recorded)`` verdicts.
        terminal_publication_unproven: Whether the receipt proves no verdict.
        coverage_incomplete_reason: The gated changed-line coverage gap.
        diff_budget_reason: Hard scope loss that also blocks progress-only
            incremental completion, independently of advisory coverage policy.
        terminal_rejection: The last refused terminal attempt, if any.
        budget_exhaustion: A token, cost or tool-call budget that ran out.
        finalize_failure: Why the post-run finalize step raised, if it did.
        roster_failure: A required reviewer's dispatch failure, if any.
        roster_infra_reason: That failure's infrastructure reason, if any.
        lite_reason: Why a lite run cannot pass, if it cannot.
        sink_scan_error: A credential found in a local sink, if any.
        structured_output_error: Why a required ``set_output`` payload is
            missing or invalid, if it is (see :func:`structured_output_error`).
    """

    result: AgentResult
    mode: str | Mode | None = None
    verdict_protocol: Literal["shadow", "enforce"] | None = "enforce"
    setup_reason: str = ""
    setup_policy: SetupFailurePolicy = "warn"
    prep_reason: str | None = None
    final_summary_written: bool = False
    terminal_publication_failed: bool = False
    terminal_publication_receipt: bool | None = None
    terminal_publication_mismatch: tuple[str, str] | None = None
    terminal_publication_unproven: bool = False
    coverage_incomplete_reason: str | None = None
    diff_budget_reason: str | None = None
    terminal_rejection: str | None = None
    budget_exhaustion: BudgetExhausted | None = None
    finalize_failure: str | None = None
    roster_failure: str | None = None
    roster_infra_reason: str | None = None
    lite_reason: str | None = None
    sink_scan_error: str | None = None
    structured_output_error: str | None = None


def structured_output_error(raw: str | None, *, findings: bool = False) -> str | None:
    """Return why a required structured output is unusable, or ``None`` when it is usable.

    A run that was asked for structured output (an ``output_schema``) and never
    called ``set_output`` did not reach the result its caller asked for, the same
    as a review that never submitted a verdict. With ``findings=True`` the payload
    must also parse as a findings payload (the offline review's schema).

    Args:
        raw (str | None): ``tool_state.output`` after the run.
        findings (bool): Whether the payload must parse as findings.

    Returns:
        str | None: The reason, else ``None``.

    Examples:
        >>> structured_output_error(None) is not None
        True
        >>> structured_output_error('{"findings": []}', findings=True) is None
        True
        >>> structured_output_error("not json", findings=True) is not None
        True
    """
    from mergecraft.analyzers.finding import STRUCTURED_OUTPUT_REQUIRED_MSG

    if not raw:
        return STRUCTURED_OUTPUT_REQUIRED_MSG
    if not findings:
        return None
    from mergecraft.analyzers.finding import parse_findings_payload

    try:
        parse_findings_payload(raw)
    except ValueError as exc:
        return str(exc)
    return None


def roster_failure_from_result(result: AgentResult) -> tuple[str | None, str | None]:
    """Return ``(roster_failure, roster_infra_reason)`` stamped on ``result``.

    Args:
        result (AgentResult): The result ``apply_roster_failure`` returned.

    Returns:
        tuple[str | None, str | None]: The failure text and its infrastructure
        reason, each ``None`` when absent.

    Examples:
        >>> from mergecraft.agents.shared import AgentResult
        >>> roster_failure_from_result(AgentResult(success=True))
        (None, None)
    """
    from mergecraft.review.roster_execution import ROSTER_FAILURE_KEY, ROSTER_INFRA_REASON_KEY

    metadata = result.metadata or {}
    failure = metadata.get(ROSTER_FAILURE_KEY)
    infra = metadata.get(ROSTER_INFRA_REASON_KEY)
    return (
        str(failure) if isinstance(failure, str) and failure else None,
        str(infra) if isinstance(infra, str) and infra else None,
    )


def _finalize_failure_reason(finalize_failure: str) -> str:
    return (
        f"{finalize_failure} — the post-run finalize step raised, so the terminal "
        "verdict could not be confirmed"
    )


def resolve_run_outcome(inputs: OutcomeInputs) -> tuple[RunOutcome, str | None]:
    """Map one run's inputs to ``(RunOutcome, failure_reason)``.

    Precedence, strongest first: a credential sink hit is ``failed``; an
    exhausted budget is its own outcome (``budget_exhaustion_outcome``); then
    the classifier (``main_outcome._classify_outcome``) reads the driver result,
    setup, prep, rejection, publication and coverage inputs. On top of that, and
    monotone (never upgrading): a post-run finalize failure makes a ``passed``
    or ``inconclusive`` run ``inconclusive`` naming the finalize error; a
    required reviewer's failure makes a ``passed`` run ``inconclusive`` (or
    ``infra_error`` when it carried an infrastructure reason); a lite run's own
    reason makes a ``passed`` run ``inconclusive``; a missing or invalid required
    structured output makes a ``passed`` run ``inconclusive`` (the run did not
    produce the result it was asked for — never ``configuration_error`` or
    ``infra_error``).

    Args:
        inputs (OutcomeInputs): Everything the run's outcome depends on.

    Returns:
        tuple[RunOutcome, str | None]: The outcome and the reason it is not
        ``passed`` (``None`` when it is).

    Examples:
        >>> from mergecraft.agents.shared import AgentResult
        >>> resolve_run_outcome(OutcomeInputs(result=AgentResult(success=True)))
        (<RunOutcome.passed: 'passed'>, None)

        >>> resolve_run_outcome(
        ...     OutcomeInputs(result=AgentResult(success=True), roster_failure="timed out")
        ... )
        (<RunOutcome.inconclusive: 'inconclusive'>, 'timed out')
    """
    from mergecraft.main_outcome import _classify_outcome
    from mergecraft.utils.run_bounds import budget_exhaustion_outcome

    outcome: RunOutcome
    reason: str | None
    if inputs.budget_exhaustion is not None:
        outcome = budget_exhaustion_outcome(inputs.budget_exhaustion)
        reason = str(inputs.budget_exhaustion)
    else:
        outcome, reason = _classify_outcome(
            result=inputs.result,
            setup_reason=inputs.setup_reason,
            setup_policy=inputs.setup_policy,
            prep_reason=inputs.prep_reason,
            mode=inputs.mode,
            verdict_protocol=inputs.verdict_protocol,
            final_summary_written=inputs.final_summary_written,
            terminal_publication_failed=inputs.terminal_publication_failed,
            terminal_publication_receipt=inputs.terminal_publication_receipt,
            terminal_publication_mismatch=inputs.terminal_publication_mismatch,
            terminal_publication_unproven=inputs.terminal_publication_unproven,
            coverage_incomplete_reason=inputs.coverage_incomplete_reason,
            diff_budget_reason=inputs.diff_budget_reason,
            terminal_rejection=inputs.terminal_rejection,
        )
        if inputs.finalize_failure is not None and outcome in {
            RunOutcome.passed,
            RunOutcome.inconclusive,
        }:
            outcome = RunOutcome.inconclusive
            reason = _finalize_failure_reason(inputs.finalize_failure)
        if inputs.roster_failure is not None and outcome is RunOutcome.passed:
            # #1132 keeps the driver's own exit from outranking an accepted
            # verdict; a required reviewer that never finished is not that exit.
            outcome = (
                RunOutcome.infra_error if inputs.roster_infra_reason else RunOutcome.inconclusive
            )
            reason = inputs.roster_failure
            logger.warning("» required reviewer failed; the run is {}: {}", outcome, reason)
        if inputs.lite_reason is not None and outcome is RunOutcome.passed:
            logger.warning("» {}", inputs.lite_reason)
            outcome, reason = RunOutcome.inconclusive, inputs.lite_reason
        if inputs.structured_output_error is not None and outcome is RunOutcome.passed:
            logger.warning("» {}", inputs.structured_output_error)
            outcome, reason = RunOutcome.inconclusive, inputs.structured_output_error
    if inputs.sink_scan_error is not None:
        # A sink hit outranks the published verdict: the run failed, whatever
        # the review said, and the reason names the sink path, never its contents.
        outcome, reason = RunOutcome.failed, inputs.sink_scan_error
    return outcome, reason


def approval_withheld_reason(inputs: OutcomeInputs) -> str | None:
    """Return why a formal APPROVE must not be posted, or ``None`` when it may be.

    Resolved before publication with the publication inputs "not applicable":
    every gate that is already known (budget, finalize, setup, prep, coverage,
    roster, rejection, lite, sink scan) is checked, so the run publishes an
    APPROVE only when its outcome would be ``passed``.

    Args:
        inputs (OutcomeInputs): The run's inputs before publication.

    Returns:
        str | None: The reason the outcome is not ``passed``, else ``None``.

    Examples:
        >>> from mergecraft.agents.shared import AgentResult
        >>> approval_withheld_reason(OutcomeInputs(result=AgentResult(success=True))) is None
        True
    """
    pre = replace(
        inputs,
        terminal_publication_receipt=None,
        terminal_publication_mismatch=None,
        terminal_publication_unproven=False,
    )
    outcome, reason = resolve_run_outcome(pre)
    if outcome is RunOutcome.passed:
        return None
    return reason or f"the run outcome is {outcome.value}"


def finalize_run_outcome(
    outcome: RunOutcome,
    packet: MergeEvidencePacket | None,
    *,
    disposition_reason: str | None = None,
) -> tuple[RunOutcome, str | None]:
    """Apply publication + disposition downgrades (monotone — never upgrades)."""
    resolved, reason = outcome_with_disposition_ledger(outcome, packet)
    if disposition_reason and resolved is RunOutcome.inconclusive and reason is None:
        return resolved, disposition_reason
    return resolved, reason


__all__ = [
    "OutcomeInputs",
    "approval_withheld_reason",
    "finalize_run_outcome",
    "resolve_run_outcome",
    "roster_failure_from_result",
    "structured_output_error",
]
