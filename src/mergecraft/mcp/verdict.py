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
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import TerminalSubmission
from mergecraft.review_taxonomy import FINDING_SEVERITIES

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_ALLOWED_VERDICTS = frozenset({"approve", "request_changes"})
_ALLOWED_TOP_LEVEL_KEYS = frozenset({"verdict", "summary", "findings"})
_REQUIRED_TOP_LEVEL_KEYS = frozenset({"verdict", "summary"})

REJECTION_INVALID_VERDICT = "invalid_verdict"
REJECTION_UNKNOWN_FIELDS = "unknown_fields"
REJECTION_MISSING_REQUIRED_FIELDS = "missing_required_fields"
REJECTION_REQUEST_CHANGES_NO_FINDINGS = "request_changes_without_findings"
REJECTION_APPROVE_CONFIRMED_BLOCKER = "approve_with_confirmed_blocker"
REJECTION_APPROVE_FAILED_GATE = "approve_with_failed_required_gate"
REJECTION_CONFLICTING_SUBMISSION = "conflicting_submission"


def _canonical_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SubmissionValidation:
    """Typed validator result (D5) — not a bare bool."""

    accepted: bool
    rejection_reason: str | None


def _finding_fingerprint(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("fingerprint") or "")
    return str(getattr(item, "fingerprint", "") or "")


def _coerce_confirmed_finding(item: Any) -> Any | None:
    from mergecraft.analyzers.finding import Finding, FindingValidationError

    if isinstance(item, Finding):
        return item
    if hasattr(item, "severity") and not isinstance(item, dict):
        return item
    if isinstance(item, dict):
        try:
            return Finding.model_validate(item)
        except (FindingValidationError, ValueError, TypeError):  # fmt: skip
            severity = item.get("severity")
            if not severity:
                return None
            from types import SimpleNamespace

            return SimpleNamespace(
                fingerprint=str(item.get("fingerprint") or ""),
                severity=str(severity),
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

        if not isinstance(value, list):
            msg = "findings must be a list"
            raise ValueError(msg)
        coerced: list[Any] = []
        for item in value:
            if isinstance(item, AgentFinding):
                finding = item
            elif isinstance(item, dict):
                finding = AgentFinding.model_validate(item)
            else:
                msg = "each finding must be an object"
                raise ValueError(msg)
            if finding.severity not in FINDING_SEVERITIES:
                msg = f"severity must be one of {FINDING_SEVERITIES!r}, got {finding.severity!r}"
                raise ValueError(msg)
            coerced.append(finding)
        return coerced


def record_validated_terminal_submission(
    ctx: ToolContext,
    submission: dict[str, Any],
) -> TerminalSubmission:
    """Validate and record a terminal submission on ``ToolState``."""
    validated = SubmitReviewVerdictParams.model_validate(submission)
    payload_hash = _canonical_payload_hash(validated.model_dump(mode="json"))
    existing = ctx.tool_state.terminal_submission
    if existing is not None:
        if existing.payload_hash == payload_hash:
            return existing
        ctx.tool_state.terminal_submission_conflict = True
        msg = (
            "terminal submission conflict: a different verdict payload was already "
            "recorded for this run"
        )
        raise ValueError(msg)

    payload = {
        "verdict": validated.verdict,
        "summary": validated.summary,
        "findings": [item.model_dump(mode="json") for item in validated.findings],
    }
    validation = validate_submission(
        payload,
        state=validation_state_from_tool_context(ctx),
    )
    if not validation.accepted:
        msg = f"terminal submission rejected: {validation.rejection_reason}"
        raise ValueError(msg)

    recorded = TerminalSubmission(
        id=uuid.uuid4().hex,
        verdict=validated.verdict,
        summary=validated.summary,
        findings=list(validated.findings),
        payload_hash=payload_hash,
        submitted_at=datetime.now(UTC).isoformat(),
        attempt_id=ctx.tool_state.fallback_index,
    )
    ctx.tool_state.terminal_submission = recorded
    ctx.tool_state.terminal_submission_conflict = False
    return recorded


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
        existing = ctx.tool_state.terminal_submission
        if existing is not None:
            validated = SubmitReviewVerdictParams.model_validate(params)
            payload_hash = _canonical_payload_hash(validated.model_dump(mode="json"))
            if existing.payload_hash == payload_hash:
                # Conflict stays sticky for this attempt. VP2 treats the flag as
                # "this attempt is unusable"; a later identical replay must not
                # wash that out. `_prepare_chain_attempt` is the only reset.
                return {
                    "recorded": True,
                    "id": existing.id,
                    "verdict": existing.verdict,
                    "replayed": True,
                }
            ctx.tool_state.terminal_submission_conflict = True
            msg = (
                "terminal submission conflict: a different verdict payload was already "
                "recorded for this run"
            )
            raise ValueError(msg)

        recorded = record_validated_terminal_submission(ctx, dict(params))
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
    "SubmissionValidation",
    "SubmitReviewVerdictParams",
    "record_validated_terminal_submission",
    "recorded_submission_payload",
    "revalidate_recorded_submission",
    "submit_review_verdict_tool",
    "validate_submission",
    "validation_state_from_tool_context",
    "validation_state_from_tool_state",
]
