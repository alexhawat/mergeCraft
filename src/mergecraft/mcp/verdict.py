"""Terminal review verdict MCP tool (VP1).

Records a typed terminal submission on ``ToolState`` without publishing to
GitHub. Enforcement and outcome wiring land in VP2; this module is inert for
run outcomes until then.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import TerminalSubmission

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def _canonical_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
                coerced.append(item)
            elif isinstance(item, dict):
                coerced.append(AgentFinding.model_validate(item))
            else:
                msg = "each finding must be an object"
                raise ValueError(msg)
        return coerced


def submit_review_verdict_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        validated = SubmitReviewVerdictParams.model_validate(params)
        payload_hash = _canonical_payload_hash(validated.model_dump(mode="json"))
        existing = ctx.tool_state.terminal_submission

        if existing is not None:
            if existing.payload_hash == payload_hash:
                ctx.tool_state.terminal_submission_conflict = False
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

        submission = TerminalSubmission(
            id=uuid.uuid4().hex,
            verdict=validated.verdict,
            summary=validated.summary,
            findings=list(validated.findings),
            payload_hash=payload_hash,
            submitted_at=datetime.now(UTC).isoformat(),
            attempt_id=ctx.tool_state.fallback_index,
        )
        ctx.tool_state.terminal_submission = submission
        ctx.tool_state.terminal_submission_conflict = False
        return {
            "recorded": True,
            "id": submission.id,
            "verdict": submission.verdict,
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


__all__ = ["SubmitReviewVerdictParams", "submit_review_verdict_tool"]
