"""Validate and stage recurring review feedback for maintainer approval.

Exports:
    FeedbackSource, FeedbackProposal, ApprovedFeedback — persisted record shapes.
    FeedbackReport — bounded proposal report for a GitHub Actions run.
    FeedbackHistory — aggregate independent observations by finding and reason.
    parse_approved_feedback — validate an approval document against its repository.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.findings.materiality import DISMISSAL_REASON_CODES
from mergecraft.memory.store import MIN_HISTORICAL_EVIDENCE, ingest_dismissal_signal

APPROVED_FEEDBACK_PATH = ".mergecraft/approved-feedback.json"
MAX_APPROVAL_BYTES = 32_768
MAX_HISTORY_PULLS = 12
MAX_PROPOSALS = 12
_FEEDBACK_REASONS = DISMISSAL_REASON_CODES | {"thread_resolved", "thumbs_down"}


class FeedbackSource(BaseModel):
    """Link to the original finding at `/pull/<pull>#discussion_r<comment>`."""

    model_config = ConfigDict(extra="forbid", strict=True)

    pull: int = Field(gt=0)
    comment: int = Field(gt=0)


def _valid_path(path: str) -> str:
    if not is_feedback_path(path):
        raise ValueError("expected an exact repository-relative path")
    return path


def _known_reason(reason: str) -> str:
    if reason not in _FEEDBACK_REASONS:
        raise ValueError("unknown feedback reason")
    return reason


def _independent_sources(evidence: list[FeedbackSource]) -> list[FeedbackSource]:
    if len({source.pull for source in evidence}) != len(evidence) or len(
        {source.comment for source in evidence}
    ) != len(evidence):
        raise ValueError("evidence must name distinct pulls and root comments")
    return evidence


def _safe_guidance(guidance: str) -> str:
    guidance = guidance.strip()
    if not guidance or redact_secrets(guidance) != guidance:
        raise ValueError("approval guidance must contain text without credentials")
    return guidance


class FeedbackProposal(BaseModel):
    """Repeated evidence with no authority to change a review."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{6,64}$")
    path: Annotated[str, AfterValidator(_valid_path)] = Field(min_length=1, max_length=512)
    reason: Annotated[str, AfterValidator(_known_reason)]
    evidence: Annotated[list[FeedbackSource], AfterValidator(_independent_sources)] = Field(
        min_length=MIN_HISTORICAL_EVIDENCE, max_length=MAX_HISTORY_PULLS
    )


class ApprovedFeedback(FeedbackProposal):
    """Maintainer-curated guidance associated with a finding on an exact path."""

    guidance: Annotated[str, AfterValidator(_safe_guidance)] = Field(min_length=1, max_length=500)


class _ApprovalDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    entries: list[ApprovedFeedback] = Field(max_length=32)


class FeedbackReport(BaseModel):
    """Proposal payload exposed only in the Actions summary."""

    version: Literal[1] = 1
    repository: str
    status: Literal["complete", "partial", "unavailable"]
    examined_pulls: list[int] = Field(default_factory=list)
    unread_pulls: list[int] = Field(default_factory=list)
    history_limited: bool = False
    proposals_limited: bool = False
    staged: list[FeedbackProposal] = Field(default_factory=list)

    def summary(self) -> str:
        """Render the copyable, non-instructional proposal payload."""
        data = json.dumps(
            {
                "version": self.version,
                "repository": self.repository,
                "status": self.status,
                "examined_pulls": self.examined_pulls,
                "incomplete_pulls": self.unread_pulls,
                "history_limited": self.history_limited,
                "proposals_limited": self.proposals_limited,
                "staged": [entry.model_dump() for entry in self.staged],
            },
            indent=2,
        ).replace("`", "\\u0060")
        return (
            "### Review feedback proposals\n\n"
            "Review the referenced discussions before approving entries in "
            f"`{APPROVED_FEEDBACK_PATH}`. The default branch controls approval.\n\n"
            f"```json\n{data}\n```\n"
        )


def is_feedback_path(path: str) -> bool:
    """Accept printable exact Git paths that are safe to include in reports."""
    return (
        0 < len(path) <= 512
        and path.isprintable()
        and all(part not in {"", ".", ".."} for part in path.split("/"))
        and redact_secrets(path) == path
    )


def _feedback_id(repository: str, fingerprint: str, path: str, reason: str) -> str:
    scope = json.dumps([1, repository.casefold(), fingerprint, path, reason], separators=(",", ":"))
    return hashlib.sha256(scope.encode()).hexdigest()


def parse_approved_feedback(text: str, repository: str) -> tuple[ApprovedFeedback, ...]:
    """Return bounded, valid entries scoped to this repository, or no guidance."""
    if len(text.encode()) > MAX_APPROVAL_BYTES:
        return ()
    try:
        approved = _ApprovalDocument.model_validate_json(text)
    except ValidationError:
        return ()
    if approved.repository.casefold() != repository.casefold():
        return ()
    ids = set()
    for entry in approved.entries:
        if entry.id in ids or entry.id != _feedback_id(
            repository, entry.fingerprint, entry.path, entry.reason
        ):
            return ()
        ids.add(entry.id)
    return tuple(approved.entries)


@dataclass(slots=True)
class FeedbackHistory:
    """Keep one source per PR and exclude an occurrence with conflicting reasons."""

    _sources: dict[tuple[str, str], dict[int, dict[str, int]]] = field(default_factory=dict)

    def add(
        self, *, fingerprint: str, path: str, pull: int, comment: int, reasons: set[str]
    ) -> None:
        """Record distinct reasons without counting duplicate findings on one PR."""
        occurrence = self._sources.setdefault((fingerprint, path), {}).setdefault(pull, {})
        for reason in reasons:
            occurrence[reason] = min(comment, occurrence.get(reason, comment))

    def proposals(self, repository: str) -> tuple[list[FeedbackProposal], bool]:
        """Stage candidates with at least two independent, consistently coded PRs."""
        proposals: list[FeedbackProposal] = []
        for (fingerprint, path), pulls in sorted(self._sources.items()):
            groups: dict[str, list[FeedbackSource]] = {}
            for pull, reasons in sorted(pulls.items()):
                if len(reasons) != 1:
                    continue
                ((reason, comment),) = reasons.items()
                groups.setdefault(reason, []).append(FeedbackSource(pull=pull, comment=comment))
            for reason, evidence in sorted(groups.items()):
                if not ingest_dismissal_signal(
                    fingerprint=fingerprint, reason_code=reason, evidence_count=len(evidence)
                ).durable:
                    continue
                proposals.append(
                    FeedbackProposal(
                        id=_feedback_id(repository, fingerprint, path, reason),
                        fingerprint=fingerprint,
                        path=path,
                        reason=reason,
                        evidence=evidence,
                    )
                )
        return proposals[:MAX_PROPOSALS], len(proposals) > MAX_PROPOSALS
