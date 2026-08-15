"""Terminal review verdict MCP tool (VP1) and semantic validation (VP2).

Records a typed terminal submission on ``ToolState`` without publishing to
GitHub. VP2 adds ``validate_submission`` and wires it into the tool so
schema-invalid and semantically-invalid payloads fail closed without setting
``terminal_submission``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import TerminalSubmission
from mergecraft.tracing.redaction import redact_attrs

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_ALLOWED_VERDICTS = frozenset({"approve", "request_changes"})
_ALLOWED_TOP_LEVEL_KEYS = frozenset({"verdict", "summary", "findings"})
_REQUIRED_TOP_LEVEL_KEYS = frozenset({"verdict", "summary"})
_REVIEW_MODES = frozenset({"Review", "IncrementalReview"})

REJECTION_INVALID_VERDICT = "invalid_verdict"
REJECTION_UNKNOWN_FIELDS = "unknown_fields"
REJECTION_MISSING_REQUIRED_FIELDS = "missing_required_fields"
REJECTION_REQUEST_CHANGES_NO_FINDINGS = "request_changes_without_findings"
REJECTION_APPROVE_CONFIRMED_BLOCKER = "approve_with_confirmed_blocker"
REJECTION_APPROVE_FAILED_GATE = "approve_with_failed_required_gate"
REJECTION_CONFLICTING_SUBMISSION = "conflicting_submission"


class ReviewPhase(StrEnum):
    """Closed review-phase vocabulary (D10 / VP4)."""

    INIT = "INIT"
    ESTABLISH_SCOPE = "ESTABLISH_SCOPE"
    COLLECT_EVIDENCE = "COLLECT_EVIDENCE"
    REVIEW = "REVIEW"
    NORMALIZE = "NORMALIZE"
    VERIFY_BLOCKERS = "VERIFY_BLOCKERS"
    SUBMIT = "SUBMIT"
    POLICY = "POLICY"
    PUBLISH = "PUBLISH"
    COMPLETE = "COMPLETE"


class VerdictDiagnostic(StrEnum):
    """Closed vocabulary for terminal-verdict shadow diagnostics (VP3)."""

    provider_failure = "provider_failure"
    provider_success_without_submission = "provider_success_without_submission"
    schema_invalid = "schema_invalid"
    semantic_invalid = "semantic_invalid"
    policy_rejection = "policy_rejection"
    agent_approved_but_blocked = "agent_approved_but_blocked"
    approved = "approved"
    fallback_triggered = "fallback_triggered"


def span_attrs_for_verdict_diagnostic(
    diagnostic: VerdictDiagnostic,
    *,
    summary: str,
) -> dict[str, Any]:
    """Build redacted span attrs carrying a closed ``VerdictDiagnostic`` code."""
    return redact_attrs(
        {
            "verdict.diagnostic": diagnostic.value,
            "summary": summary,
        }
    )


def stamp_review_phase_on_active_span(phase: ReviewPhase) -> None:
    """Stamp ``review.phase`` on the active span when one is open (D10)."""
    from mergecraft.tracing import Span
    from mergecraft.tracing.tracer import _ACTIVE_SPAN

    active = _ACTIVE_SPAN.get()
    if isinstance(active, Span):
        active.set_attribute("review.phase", phase.value)
        active.set_attribute("mergecraft.review.phase", phase.value)


def _current_review_phase(tool_state: Any) -> ReviewPhase:
    raw = getattr(tool_state, "review_phase", ReviewPhase.INIT)
    if isinstance(raw, ReviewPhase):
        return raw
    return ReviewPhase(str(raw))


def record_validated_terminal_submission(
    ctx: ToolContext,
    submission: dict[str, Any],
    *,
    findings: list[Any] | None = None,
) -> TerminalSubmission:
    """Validate and record a terminal submission on ``ToolState`` (VP4 delegate path)."""
    payload_hash = _canonical_payload_hash(_submission_dict_for_hash(submission))
    existing = ctx.tool_state.terminal_submission

    if existing is not None:
        if existing.payload_hash == payload_hash:
            ctx.tool_state.terminal_submission_conflict = False
            return existing
        ctx.tool_state.terminal_submission_conflict = True
        msg = (
            "terminal submission conflict: a different verdict payload was already "
            "recorded for this run"
        )
        raise ValueError(msg)

    validation = validate_submission(
        submission,
        state=validation_state_from_tool_context(ctx),
    )
    if not validation.accepted:
        msg = f"terminal submission rejected: {validation.rejection_reason}"
        raise ValueError(msg)

    verdict = submission["verdict"]
    summary = submission["summary"]
    resolved_findings = findings if findings is not None else list(submission.get("findings") or [])

    recorded = TerminalSubmission(
        id=uuid.uuid4().hex,
        verdict=verdict,
        summary=str(summary),
        findings=list(resolved_findings),
        payload_hash=payload_hash,
        submitted_at=datetime.now(UTC).isoformat(),
        attempt_id=ctx.tool_state.attempt_id,
    )
    ctx.tool_state.terminal_submission = recorded
    ctx.tool_state.terminal_submission_conflict = False
    return recorded


def verdict_satisfies_attempt(
    submission: TerminalSubmission,
    *,
    current_attempt_id: int,
) -> bool:
    """Return whether ``submission`` belongs to the active model-chain attempt (V7)."""
    return submission.attempt_id == current_attempt_id


def _canonical_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _submission_dict_for_hash(submission: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable submission dict for canonical hashing."""
    findings_raw = submission.get("findings") or []
    serializable_findings: list[Any] = []
    for item in findings_raw:
        if hasattr(item, "model_dump"):
            serializable_findings.append(item.model_dump())
        else:
            serializable_findings.append(item)
    return {
        "verdict": submission["verdict"],
        "summary": submission["summary"],
        "findings": serializable_findings,
    }


@dataclass(frozen=True, slots=True)
class SubmissionValidation:
    """Typed validator result (D5) — not a bare bool."""

    accepted: bool
    rejection_reason: str | None


def _confirmed_findings_from_state(state: Any) -> list[Any]:
    explicit = getattr(state, "confirmed_findings", None)
    if explicit:
        return list(explicit)
    analyzer_run = getattr(state, "analyzer_run", None)
    if analyzer_run is None:
        return []
    verified_ids = getattr(analyzer_run, "verified_ids", None) or set()
    findings_raw = getattr(analyzer_run, "findings", None) or []
    from mergecraft.analyzers.finding import Finding

    confirmed: list[Any] = []
    for item in findings_raw:
        if isinstance(item, Finding):
            finding = item
        elif isinstance(item, dict):
            finding = Finding.model_validate(item)
        else:
            continue
        if finding.fingerprint in verified_ids:
            confirmed.append(finding)
    return confirmed


def _static_checks_from_state(state: Any) -> list[dict[str, str]]:
    explicit = getattr(state, "static_checks", None)
    if explicit:
        return [dict(row) for row in explicit if isinstance(row, dict)]
    return []


def validation_state_from_tool_context(ctx: ToolContext) -> Any:
    """Build the duck-typed consultation object ``validate_submission`` reads."""
    from types import SimpleNamespace

    tool_state = ctx.tool_state
    state = SimpleNamespace(
        terminal_submission=tool_state.terminal_submission,
        terminal_submission_conflict=tool_state.terminal_submission_conflict,
        confirmed_findings=[],
        static_checks=[dict(row) for row in tool_state.static_checks if isinstance(row, dict)],
        withdrawn_fingerprints=set(),
        tool_state=tool_state,
        analyzer_run=tool_state.analyzer_run,
    )
    state.confirmed_findings = _confirmed_findings_from_state(state)
    return state


def validate_submission(submission: dict[str, Any], *, state: Any) -> SubmissionValidation:
    """Pure semantic + structural validation for a terminal verdict payload (D5, D9)."""
    if getattr(state, "terminal_submission_conflict", False):
        return SubmissionValidation(
            accepted=False,
            rejection_reason=REJECTION_CONFLICTING_SUBMISSION,
        )

    if not isinstance(submission, dict):
        return SubmissionValidation(
            accepted=False,
            rejection_reason=REJECTION_MISSING_REQUIRED_FIELDS,
        )

    unknown = set(submission.keys()) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        return SubmissionValidation(
            accepted=False,
            rejection_reason=REJECTION_UNKNOWN_FIELDS,
        )

    for key in _REQUIRED_TOP_LEVEL_KEYS:
        if key not in submission:
            return SubmissionValidation(
                accepted=False,
                rejection_reason=REJECTION_MISSING_REQUIRED_FIELDS,
            )

    verdict = submission["verdict"]
    if verdict not in _ALLOWED_VERDICTS:
        return SubmissionValidation(
            accepted=False,
            rejection_reason=REJECTION_INVALID_VERDICT,
        )

    findings_raw = submission.get("findings", [])
    if findings_raw is None:
        findings_raw = []
    if not isinstance(findings_raw, list):
        return SubmissionValidation(
            accepted=False,
            rejection_reason=REJECTION_MISSING_REQUIRED_FIELDS,
        )

    if verdict == "request_changes" and len(findings_raw) == 0:
        return SubmissionValidation(
            accepted=False,
            rejection_reason=REJECTION_REQUEST_CHANGES_NO_FINDINGS,
        )

    if verdict == "approve":
        from mergecraft.agents.gates import BLOCKING_SEVERITIES, has_failed_required_static_check

        for finding in _confirmed_findings_from_state(state):
            severity = finding.severity if hasattr(finding, "severity") else finding.get("severity")
            if severity in BLOCKING_SEVERITIES:
                return SubmissionValidation(
                    accepted=False,
                    rejection_reason=REJECTION_APPROVE_CONFIRMED_BLOCKER,
                )
        if has_failed_required_static_check(_static_checks_from_state(state)):
            return SubmissionValidation(
                accepted=False,
                rejection_reason=REJECTION_APPROVE_FAILED_GATE,
            )

    return SubmissionValidation(accepted=True, rejection_reason=None)


class SubmitReviewVerdictParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["approve", "request_changes"]
    summary: str
    findings: list[Any] = Field(default_factory=list)

    @field_validator("findings", mode="before")
    @classmethod
    def _coerce_findings(cls, value: object) -> list[Any]:
        from mergecraft.agents.verifier import AgentFinding

        if not value:
            return []
        if not isinstance(value, list):
            msg = "findings must be a list"
            raise TypeError(msg)
        coerced: list[Any] = []
        for item in value:
            if isinstance(item, AgentFinding):
                coerced.append(item)
            elif isinstance(item, dict):
                coerced.append(AgentFinding.model_validate(item))
            else:
                msg = "each finding must be an object"
                raise TypeError(msg)
        return coerced


def submit_review_verdict_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        mode = ctx.tool_state.selected_mode
        if mode in _REVIEW_MODES and _current_review_phase(ctx.tool_state) == ReviewPhase.INIT:
            msg = (
                "submit_review_verdict requires checkout_pr to establish review scope "
                "before the terminal verdict can be recorded"
            )
            raise ValueError(msg)

        validated = SubmitReviewVerdictParams.model_validate(params)
        payload_hash = _canonical_payload_hash(dict(params))
        submission_dict = {
            "verdict": validated.verdict,
            "summary": validated.summary,
            "findings": [item.model_dump() for item in validated.findings],
        }
        existing = ctx.tool_state.terminal_submission
        if existing is not None and existing.payload_hash == payload_hash:
            ctx.tool_state.terminal_submission_conflict = False
            ctx.tool_state.review_phase = ReviewPhase.SUBMIT.value
            stamp_review_phase_on_active_span(ReviewPhase.SUBMIT)
            return {
                "recorded": True,
                "id": existing.id,
                "verdict": existing.verdict,
                "replayed": True,
            }

        recorded = record_validated_terminal_submission(
            ctx,
            submission_dict,
            findings=list(validated.findings),
        )
        ctx.tool_state.review_phase = ReviewPhase.SUBMIT.value
        stamp_review_phase_on_active_span(ReviewPhase.SUBMIT)
        return {
            "recorded": True,
            "id": recorded.id,
            "verdict": recorded.verdict,
            "replayed": False,
        }

    return tool(
        name="submit_review_verdict",
        description=(
            "Record the terminal review verdict for this run: approve or request_changes, "
            "a summary, and structured findings. Identical re-submissions are idempotent; "
            "conflicting payloads are rejected. Does not publish to GitHub — call "
            "create_pull_request_review separately when publication is required."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["approve", "request_changes"],
                    "description": "Structural terminal verdict for this review run.",
                },
                "summary": {
                    "type": "string",
                    "description": "Short summary of the review outcome.",
                },
                "findings": {
                    "type": "array",
                    "description": "Structured findings backing a request_changes verdict.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "line": {"type": "number"},
                            "severity": {
                                "type": "string",
                                "enum": ["Critical", "Major", "Minor", "Trivial"],
                            },
                            "body": {"type": "string"},
                            "fingerprint": {"type": "string"},
                        },
                        "required": ["path", "body", "severity"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["verdict", "summary"],
            "additionalProperties": False,
        },
        mutates=False,
        execute=execute(_run, "submit_review_verdict"),
    )


__all__ = [
    "REJECTION_APPROVE_CONFIRMED_BLOCKER",
    "REJECTION_APPROVE_FAILED_GATE",
    "REJECTION_CONFLICTING_SUBMISSION",
    "REJECTION_INVALID_VERDICT",
    "REJECTION_MISSING_REQUIRED_FIELDS",
    "REJECTION_REQUEST_CHANGES_NO_FINDINGS",
    "REJECTION_UNKNOWN_FIELDS",
    "ReviewPhase",
    "SubmissionValidation",
    "SubmitReviewVerdictParams",
    "VerdictDiagnostic",
    "record_validated_terminal_submission",
    "span_attrs_for_verdict_diagnostic",
    "stamp_review_phase_on_active_span",
    "submit_review_verdict_tool",
    "validate_submission",
    "validation_state_from_tool_context",
    "verdict_satisfies_attempt",
]
