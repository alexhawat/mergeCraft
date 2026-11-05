"""Incident-derived eval cases — postmortem PRs with revert/fix-forward (#1163).

An incident case ties a merged PR that caused production harm to the follow-up
revert or fix-forward PR and a **confirmed** bug location. Provenance uses the
same tier vocabulary as the flywheel (:mod:`mergecraft.evals.adjudication`); rows
without provenance or a confirmed location are refused fail-closed (R-D6).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mergecraft.evals.adjudication import (
    AdjudicationRecord,
    provenance_for,
    tier_for_provenance,
)
from mergecraft.evals.flywheel import (
    AGENT_SEEDED_PROVENANCE,
    INVALID_CASE_ID_REASON,
    classify_candidate,
)
from mergecraft.evals.ids import CASE_ID_RE
from mergecraft.evals.store import CATEGORY_INCIDENT_DERIVED, Case, add_case

INCIDENT_REFUSAL_NO_LOCATION: Final[str] = (
    "incident case requires confirmed_bug_path and a positive line range"
)
INCIDENT_REFUSAL_NO_PROVENANCE: Final[str] = (
    "incident case requires label_provenance with a recognised tier or agent-seeded"
)


class IncidentCaseInput(BaseModel):
    """Operator input to seed one incident-derived structural case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1)
    incident_pr: int = Field(ge=1)
    followup_pr: int = Field(ge=1, description="Revert or fix-forward PR number.")
    confirmed_bug_path: str = Field(min_length=1)
    confirmed_bug_start_line: int = Field(ge=1)
    confirmed_bug_end_line: int = Field(ge=1)
    label_provenance: str = ""
    adjudication: AdjudicationRecord | None = None
    expected_decision: str = Field(default="block", min_length=1)
    failure_mode: str = Field(default="missed_finding", min_length=1)
    run_id: str = Field(min_length=1)
    author_login: str = Field(min_length=1)
    author_association: str | None = None
    trust_tier: str = "trusted"
    body: str = ""
    recorded_findings: list[dict[str, object]] | None = None
    run_succeeded: bool = True

    @model_validator(mode="after")
    def _lines_ordered(self) -> IncidentCaseInput:
        if self.confirmed_bug_end_line < self.confirmed_bug_start_line:
            msg = "confirmed_bug_end_line must be >= confirmed_bug_start_line"
            raise ValueError(msg)
        return self

    @property
    def confirmed_bug_location(self) -> str:
        """Wire-format location matching ``expected_finding`` conventions."""
        return (
            f"{self.confirmed_bug_path}:{self.confirmed_bug_start_line}-"
            f"{self.confirmed_bug_end_line}"
        )


class IncidentAddOutcome(BaseModel):
    """Result of attempting to write one incident case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    accepted: bool
    reason: str = ""
    path: str | None = None


def _validate_incident_provenance(spec: IncidentCaseInput) -> tuple[bool, str]:
    declared = spec.label_provenance.strip()
    if not declared:
        return False, INCIDENT_REFUSAL_NO_PROVENANCE
    if declared == AGENT_SEEDED_PROVENANCE:
        return True, ""
    if tier_for_provenance(declared) == "none":
        return False, INCIDENT_REFUSAL_NO_PROVENANCE
    if spec.adjudication is None:
        return False, f"provenance {declared!r} requires an adjudication record (R-D6)"
    if provenance_for(spec.adjudication) != declared:
        return False, "adjudication record does not match label_provenance (R-D6)"
    return True, ""


def build_incident_case(spec: IncidentCaseInput, *, stored_provenance: str) -> Case:
    """Build a durable :class:`Case` from validated incident input."""
    from mergecraft.utils.learnings import LearningProvenance

    now = datetime.now(UTC)
    trust: Literal["trusted", "untrusted"] = (
        "untrusted" if spec.trust_tier == "untrusted" else "trusted"
    )
    provenance = LearningProvenance(
        run_id=spec.run_id,
        pr_number=spec.incident_pr,
        source_field="incident_derived",
        author_login=spec.author_login,
        author_association=spec.author_association,
        trust_tier=trust,
        timestamp=now,
    )
    body = spec.body.strip() or (
        f"# {spec.case_id}\n\n"
        f"Incident PR #{spec.incident_pr}; follow-up (revert/fix) PR #{spec.followup_pr}.\n\n"
        f"## Confirmed bug\n\n"
        f"{spec.confirmed_bug_location}\n"
    )
    return Case(
        id=spec.case_id,
        title=spec.title,
        category=CATEGORY_INCIDENT_DERIVED,
        submitted_at=now,
        run_id=spec.run_id,
        pr_number=spec.incident_pr,
        failure_mode=spec.failure_mode,
        expected_finding=spec.confirmed_bug_location,
        expected_decision=spec.expected_decision,
        replay_command=f"mergecraft eval replay {spec.case_id}",
        provenance=provenance,
        body=body,
        recorded_findings=spec.recorded_findings,
        run_succeeded=spec.run_succeeded,
        trust_tier=trust,
        label_provenance=stored_provenance,
        incident_pr=spec.incident_pr,
        followup_pr=spec.followup_pr,
        confirmed_bug_path=spec.confirmed_bug_path,
        confirmed_bug_start_line=spec.confirmed_bug_start_line,
        confirmed_bug_end_line=spec.confirmed_bug_end_line,
    )


def add_incident_case(spec: IncidentCaseInput, *, bank_dir: Path) -> IncidentAddOutcome:
    """Validate and write one incident case, fail-closed."""
    if not CASE_ID_RE.match(spec.case_id):
        return IncidentAddOutcome(
            case_id=spec.case_id, accepted=False, reason=INVALID_CASE_ID_REASON
        )
    if not spec.confirmed_bug_path.strip():
        return IncidentAddOutcome(
            case_id=spec.case_id, accepted=False, reason=INCIDENT_REFUSAL_NO_LOCATION
        )
    ok, reason = _validate_incident_provenance(spec)
    if not ok:
        return IncidentAddOutcome(case_id=spec.case_id, accepted=False, reason=reason)

    from mergecraft.evals.flywheel import FlywheelCandidate

    candidate = FlywheelCandidate(
        case_id=spec.case_id,
        title=spec.title,
        category=CATEGORY_INCIDENT_DERIVED,
        failure_mode=spec.failure_mode,
        expected_finding=spec.confirmed_bug_location,
        expected_decision=spec.expected_decision,
        provenance=spec.label_provenance.strip(),
        adjudication=spec.adjudication,
        recorded_findings=spec.recorded_findings,
        run_succeeded=spec.run_succeeded,
        trust_tier=spec.trust_tier,
        body=spec.body,
        pr_number=spec.incident_pr,
        run_id=spec.run_id,
        author_login=spec.author_login,
        author_association=spec.author_association,
    )
    accepted, fly_reason, stored, _tier = classify_candidate(candidate)
    if not accepted:
        return IncidentAddOutcome(case_id=spec.case_id, accepted=False, reason=fly_reason)
    try:
        case = build_incident_case(spec, stored_provenance=stored)
        path = add_case(bank_dir, case)
    except Exception as exc:
        return IncidentAddOutcome(
            case_id=spec.case_id, accepted=False, reason=f"write failed: {exc}"
        )
    return IncidentAddOutcome(case_id=spec.case_id, accepted=True, path=str(path))


__all__ = [
    "IncidentAddOutcome",
    "IncidentCaseInput",
    "add_incident_case",
    "build_incident_case",
]
