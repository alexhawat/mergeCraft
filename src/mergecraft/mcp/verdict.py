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

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergecraft.findings.agent_adapter import (
    coerce_agent_finding,
    normalize_agent_findings_via_pipeline,
)
from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import TerminalSubmission, primary_repo_state
from mergecraft.review_taxonomy import FINDING_SEVERITIES
from mergecraft.tracing.redaction import redact_attrs

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding

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
    """Stamp ``review.phase`` on the active span when one is open (D10).

    OB4 / O9 — the same transition seam also emits a ``mergecraft.phase``
    point span via the active span's tracer, so the trace shows the
    lifecycle as it advances and a run that dies early visibly stops before
    the terminal phases. Best-effort: a span-emission failure must never
    break the transition itself (convention 3).
    """
    from mergecraft.tracing import Span
    from mergecraft.tracing.tracer import _ACTIVE_SPAN

    active = _ACTIVE_SPAN.get()
    if isinstance(active, Span):
        active.set_attribute("review.phase", phase.value)
        active.set_attribute("mergecraft.review.phase", phase.value)
        try:
            from mergecraft.tracing.signals import emit_phase

            emit_phase(active.tracer, phase=phase)
        except Exception:
            logger.debug("phase span emission skipped for {}", phase.value)


def _current_review_phase(tool_state: Any) -> ReviewPhase:
    raw = getattr(tool_state, "review_phase", ReviewPhase.INIT)
    if isinstance(raw, ReviewPhase):
        return raw
    return ReviewPhase(str(raw))


def ensure_review_scope_for_terminal(tool_state: Any, tool_name: str) -> None:
    """Raise when a Review-mode terminal tool runs before ``checkout_pr`` (D10)."""
    mode = getattr(tool_state, "selected_mode", None)
    if mode not in _REVIEW_MODES or _current_review_phase(tool_state) != ReviewPhase.INIT:
        return
    if mode == "IncrementalReview":
        primary = primary_repo_state(tool_state)
        if primary.incremental_changed_paths:
            return
    msg = (
        f"{tool_name} requires checkout_pr to establish review scope "
        "before the terminal verdict can be recorded"
    )
    raise ValueError(msg)


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
            if ctx.tool_state.terminal_submission_conflict:
                return existing
            validation = validate_submission(
                submission,
                state=validation_state_from_tool_context(ctx),
            )
            if not validation.accepted:
                msg = f"terminal submission rejected: {validation.rejection_reason}"
                raise ValueError(msg)
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


def _finding_fingerprint(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("fingerprint") or "")
    return str(getattr(item, "fingerprint", "") or "")


def _coerce_confirmed_finding(item: Any) -> Finding | None:
    from mergecraft.analyzers.finding import Finding, FindingValidationError, make_finding

    if isinstance(item, Finding):
        return item
    if isinstance(item, dict):
        try:
            return Finding.model_validate(item)
        except (FindingValidationError, ValueError, TypeError):  # fmt: skip
            severity = item.get("severity")
            if not severity:
                return None
            from typing import cast

            from mergecraft.analyzers.finding import IntroducedByPr

            introduced_raw = str(item.get("introduced_by_pr") or "unknown")
            introduced = cast(
                "IntroducedByPr",
                introduced_raw if introduced_raw in {"true", "false", "unknown"} else "unknown",
            )
            return make_finding(
                tool=str(item.get("tool") or "agent"),
                rule_id=str(item.get("rule_id") or "agent:confirmed"),
                category=str(item.get("category") or "Functional Correctness"),
                severity=str(severity),
                confidence=str(item.get("confidence") or "likely"),
                message=str(item.get("message") or item.get("body") or ""),
                path=str(item.get("path") or ""),
                start_line=int(item.get("start_line") or item.get("line") or 1),
                end_line=int(item.get("end_line") or item.get("line") or 1),
                source="agent",
                fingerprint=str(item.get("fingerprint") or "") or None,
                introduced_by_pr=introduced,
            )
    return None


def _confirmed_findings_from_state(state: Any) -> list[Any]:
    collected: list[Any] = []
    seen: set[str] = set()

    def _add(item: Any) -> None:
        coerced = _coerce_confirmed_finding(item)
        if coerced is None:
            return
        fingerprint = _finding_fingerprint(coerced)
        if fingerprint:
            if fingerprint in seen:
                return
            seen.add(fingerprint)
        collected.append(coerced)

    explicit = getattr(state, "confirmed_findings", None)
    if explicit:
        for item in explicit:
            _add(item)
        return collected

    tool_state = getattr(state, "tool_state", None)
    if tool_state is not None:
        for item in getattr(tool_state, "confirmed_findings", None) or []:
            _add(item)

    analyzer_run = getattr(state, "analyzer_run", None)
    if analyzer_run is None and tool_state is not None:
        analyzer_run = getattr(tool_state, "analyzer_run", None)
    verified_ids: set[str] = set()
    if tool_state is not None:
        verified_ids |= set(getattr(tool_state, "verified_ids", None) or set())
    if analyzer_run is not None:
        verified_ids |= set(getattr(analyzer_run, "verified_ids", None) or set())
        for item in getattr(analyzer_run, "findings", None) or []:
            if _finding_fingerprint(item) in verified_ids:
                _add(item)
    return collected


def _static_checks_from_state(state: Any) -> list[dict[str, str]]:
    explicit = getattr(state, "static_checks", None)
    if explicit:
        return [dict(row) for row in explicit if isinstance(row, dict)]
    return []


def validation_state_from_tool_state(tool_state: Any) -> Any:
    """Build the duck-typed consultation object ``validate_submission`` reads."""
    from types import SimpleNamespace

    state = SimpleNamespace(
        terminal_submission=tool_state.terminal_submission,
        terminal_submission_conflict=tool_state.terminal_submission_conflict,
        confirmed_findings=[],
        static_checks=[dict(row) for row in tool_state.static_checks if isinstance(row, dict)],
        withdrawn_fingerprints=set(),
        tool_state=tool_state,
        analyzer_run=getattr(tool_state, "analyzer_run", None),
    )
    state.confirmed_findings = _confirmed_findings_from_state(state)
    return state


def validation_state_from_tool_context(ctx: ToolContext) -> Any:
    """Build the consultation object from a live ``ToolContext``."""
    return validation_state_from_tool_state(ctx.tool_state)


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
        from mergecraft.analyzers.finding import Finding
        from mergecraft.findings.causality import apply_causality_policy

        for finding in _confirmed_findings_from_state(state):
            if not isinstance(finding, Finding):
                continue
            adjusted = apply_causality_policy(finding)
            if adjusted.severity in BLOCKING_SEVERITIES:
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
        if not isinstance(value, list):
            msg = "findings must be a list"
            raise ValueError(msg)
        coerced: list[Any] = []
        for item in value:
            finding = coerce_agent_finding(item)
            if finding.severity not in FINDING_SEVERITIES:
                msg = f"severity must be one of {FINDING_SEVERITIES!r}, got {finding.severity!r}"
                raise ValueError(msg)
            coerced.append(finding)
        return coerced


def recorded_submission_payload(submission: Any) -> dict[str, Any]:
    findings: list[Any] = []
    for item in submission.findings:
        if hasattr(item, "model_dump"):
            findings.append(item.model_dump(mode="json"))
        else:
            findings.append(item)
    return {
        "verdict": submission.verdict,
        "summary": submission.summary,
        "findings": findings,
    }


def revalidate_recorded_submission(ctx: ToolContext) -> None:
    """Reject a stored verdict that current evidence has made unusable."""
    submission = ctx.tool_state.terminal_submission
    if submission is None:
        return
    validation = validate_submission(
        recorded_submission_payload(submission),
        state=validation_state_from_tool_context(ctx),
    )
    if not validation.accepted:
        msg = f"terminal submission rejected: {validation.rejection_reason}"
        raise ValueError(msg)


def submit_review_verdict_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        ensure_review_scope_for_terminal(ctx.tool_state, "submit_review_verdict")
        validated = SubmitReviewVerdictParams.model_validate(params)
        normalized_findings = normalize_agent_findings_via_pipeline(
            list(validated.findings),
            rule_id="agent:terminal",
        )
        submission_dict = {
            "verdict": validated.verdict,
            "summary": validated.summary,
            "findings": [
                item.model_dump() if hasattr(item, "model_dump") else item
                for item in normalized_findings
            ],
        }
        existing = ctx.tool_state.terminal_submission
        existing_id = existing.id if existing is not None else None
        recorded = record_validated_terminal_submission(
            ctx,
            submission_dict,
            findings=normalized_findings,
        )
        ctx.tool_state.review_phase = ReviewPhase.SUBMIT.value
        stamp_review_phase_on_active_span(ReviewPhase.SUBMIT)
        return {
            "recorded": True,
            "id": recorded.id,
            "verdict": recorded.verdict,
            "replayed": existing_id is not None and recorded.id == existing_id,
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
                                "enum": list(FINDING_SEVERITIES),
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
        tool_class=ToolClass.TERMINAL_PROTOCOL,
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
    "ensure_review_scope_for_terminal",
    "record_validated_terminal_submission",
    "recorded_submission_payload",
    "revalidate_recorded_submission",
    "span_attrs_for_verdict_diagnostic",
    "stamp_review_phase_on_active_span",
    "submit_review_verdict_tool",
    "validate_submission",
    "validation_state_from_tool_context",
    "validation_state_from_tool_state",
    "verdict_satisfies_attempt",
]
