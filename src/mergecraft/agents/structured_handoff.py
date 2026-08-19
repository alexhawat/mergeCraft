"""Typed specialist handoff — prose discovery, typed ``AgentFinding`` emission (AP3, D6).

Specialists reason in free-form prose during discovery; the orchestrator dispatch
prompt deliberately carries no finding schema. At the boundary the specialist
emits typed findings (``---typed-findings---`` tail or structured output schema).
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, ValidationError

from mergecraft.agents.verifier import AgentFinding, plan_agent_verifications

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.agents.registry import AgentBinding

_TYPED_FINDINGS_MARKER: Final[str] = "---typed-findings---"
# Matched against the original text so the offsets stay byte-for-byte valid:
# ``casefold()`` is not length-preserving (``ß`` → ``ss``), and the reasoning
# half is arbitrary model output.
_TYPED_FINDINGS_PATTERN: Final[re.Pattern[str]] = re.compile(
    re.escape(_TYPED_FINDINGS_MARKER), re.IGNORECASE
)
_AGENT_FINDING_SCHEMA_ID: Final[str] = "mergecraft.agent_finding"


class SpecialistHandoff(BaseModel):
    """Prose reasoning plus typed findings at the specialist boundary."""

    model_config = ConfigDict(extra="forbid")

    reasoning: str
    findings: tuple[AgentFinding, ...]


def agent_finding_output_schema_id() -> str:
    """Registry ``output_schema`` id for specialist typed emission."""
    return _AGENT_FINDING_SCHEMA_ID


def parse_specialist_handoff(raw: str) -> SpecialistHandoff:
    """Split prose reasoning from a typed findings tail (D6)."""
    text = raw.strip()
    match = _TYPED_FINDINGS_PATTERN.search(text)
    if match is not None:
        reasoning = text[: match.start()].strip()
        payload = text[match.end() :].strip()
    else:
        reasoning = text
        payload = "[]"

    try:
        rows = json.loads(payload)
    except json.JSONDecodeError as exc:
        msg = f"specialist handoff: typed-findings tail is not valid JSON: {exc}"
        raise ValueError(msg) from exc

    if not isinstance(rows, list):
        msg = "specialist handoff: typed-findings tail must be a JSON array"
        raise ValueError(msg)

    findings: list[AgentFinding] = []
    for row in rows:
        if not isinstance(row, dict):
            msg = "specialist handoff: each finding must be a JSON object"
            raise ValueError(msg)
        try:
            findings.append(AgentFinding.model_validate(row))
        except ValidationError as exc:
            msg = f"specialist handoff: invalid finding row: {exc}"
            raise ValueError(msg) from exc

    return SpecialistHandoff(reasoning=reasoning, findings=tuple(findings))


def build_specialist_dispatch_prompt(binding: AgentBinding) -> str:
    """Discovery dispatch brief — no finding schema pre-shapes output (D6)."""
    del binding
    return (
        "Review the dispatched scope using read-only tools. Reason in free-form "
        "prose while you investigate — do not pre-format findings as JSON during "
        "discovery and do not call structured-output tools until handoff."
    )


def verification_plan_from_handoff(
    handoff: SpecialistHandoff,
    *,
    budget: int,
    learnings_text: str = "",
    repo_root: Path | None = None,
) -> object:
    """Queue verifier dispatches from typed handoff findings."""
    return plan_agent_verifications(
        list(handoff.findings),
        budget=budget,
        learnings_text=learnings_text,
        repo_root=repo_root,
    )


__all__ = [
    "SpecialistHandoff",
    "agent_finding_output_schema_id",
    "build_specialist_dispatch_prompt",
    "parse_specialist_handoff",
    "verification_plan_from_handoff",
]
