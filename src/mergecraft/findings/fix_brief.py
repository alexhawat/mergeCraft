"""Versioned, advisory handoff from a review to a human or coding agent.

Exports:
    FixBrief, FixBriefFinding — validated wire models; finding text is untrusted data.
    fix_brief_path, read_fix_brief, write_run_fix_brief — artifact boundary.
    action_fix_brief_output — bounded JSON for the Action output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal, Self, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mergecraft.analyzers.redact import redact_known_secret_patterns, redact_secrets
from mergecraft.review_taxonomy import BODY_ONLY_EFFORT
from mergecraft.utils.atomic_write import write_bytes_atomically

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding
    from mergecraft.evidence.packet import MergeEvidencePacket
    from mergecraft.mcp.tool_state import ToolState

FixSeverity = Literal["Critical", "Major", "Minor"]
FixStatus = Literal["actionable", "deferred"]
Severity = Literal["Critical", "Major", "Minor", "Trivial"]
_MAX_BRIEF_BYTES = 8 * 1024 * 1024
_ACTION_OUTPUT_LIMIT = 48 * 1024


class FixBriefFinding(BaseModel):
    """One in-scope finding, without any executable fix or tool parameters."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{6,64}$")]
    status: FixStatus
    severity: FixSeverity
    path: str
    start_line: Annotated[int, Field(ge=1)] | None
    end_line: Annotated[int, Field(ge=1)] | None
    message: Annotated[str, Field(min_length=1)]
    evidence: list[str]
    remediation: str | None


class FixBrief(BaseModel):
    """A snapshot of eligible findings at one exact reviewed head."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    schema_version: Literal["1.0.0"]
    change_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*$")]
    reviewed_head_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    findings: list[FixBriefFinding]

    @model_validator(mode="after")
    def _unique_findings(self) -> Self:
        if len({row.fingerprint for row in self.findings}) != len(self.findings):
            msg = "duplicate fix brief finding fingerprint"
            raise ValueError(msg)
        return self


class _DeferredRow(BaseModel):
    """The overflow row emitted by analyzers.budget.finding_to_deferred_row."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    path: str
    line: int | None
    end_line: int | None
    body: str
    severity: Severity
    fingerprint: str
    scope: Literal["change", "run"]
    introduced_by_pr: Literal["true", "false", "unknown"]


def fix_brief_path(packet_path: Path) -> Path:
    """Return the separate brief artifact location for an evidence packet.

    Args:
        packet_path: Path where the run writes its evidence packet.

    Returns:
        Sibling path reserved for this run's brief.
    """
    return packet_path.with_name(f"{packet_path.stem}-fix-brief.json")


def read_fix_brief(path: Path) -> FixBrief:
    """Read one supported brief with a byte bound before JSON validation.

    Args:
        path: File containing exactly one fix brief document.

    Returns:
        The validated brief, with opaque text preserved.
    """
    with path.open("rb") as source:
        data = source.read(_MAX_BRIEF_BYTES + 1)
    if len(data) > _MAX_BRIEF_BYTES:
        msg = "fix brief exceeds its size limit"
        raise ValueError(msg)
    return FixBrief.model_validate_json(data)


def action_fix_brief_output(path: Path) -> str | None:
    """Return bounded JSON for the Actions step output, with the file retained.

    Args:
        path: Path to the emitted fix brief.

    Returns:
        Validated compact JSON, or None when it exceeds the step output cap.
    """
    brief = read_fix_brief(path)
    text = brief.model_dump_json(ensure_ascii=True)
    if len(text) > _ACTION_OUTPUT_LIMIT:
        return None
    return text


def _eligible_severity(severity: str) -> FixSeverity | None:
    if severity in get_args(FixSeverity):
        return cast("FixSeverity", severity)  # Runtime Literal membership narrows str.
    return None


def _project_finding(
    finding: Finding, *, severity: FixSeverity, status: FixStatus
) -> FixBriefFinding:
    return FixBriefFinding(
        fingerprint=finding.fingerprint,
        status=status,
        severity=severity,
        path=redact_known_secret_patterns(finding.path),
        start_line=finding.start_line,
        end_line=finding.end_line,
        message=redact_secrets(finding.message),
        evidence=[redact_secrets(item) for item in finding.evidence],
        remediation=redact_secrets(finding.remediation)
        if finding.remediation is not None
        else None,
    )


def _assemble_fix_brief(packet: MergeEvidencePacket, state: ToolState) -> FixBrief | None:
    submission, receipt = state.terminal_submission, state.review
    if (
        packet.trajectory is None
        or state.review_comment_fallback_applied
        or packet.reviewed_head_sha is None
        or submission is None
        or receipt is None
        or receipt.reviewed_sha != packet.reviewed_head_sha
        or receipt.verdict != submission.verdict
        or packet.agent_terminal_verdict != submission.verdict
    ):
        return None
    if packet.run_health is not None and any(
        row.rule_id in {"dropped-finding-rows", "unparseable-diff-paths"}
        for row in packet.run_health.findings
    ):
        msg = "review evidence is incomplete"
        raise ValueError(msg)

    excluded = set(state.withdrawn_fingerprints)
    for agent_row in state.agent_findings:
        if isinstance(agent_row, dict) and agent_row.get("effort") == BODY_ONLY_EFFORT:
            fingerprint = agent_row.get("fingerprint")
            if isinstance(fingerprint, str):
                excluded.add(fingerprint)
    ledger_deferred: set[str] = set()
    if state.finding_ledger is not None:
        for record in state.finding_ledger.records():
            if record.state == "deferred":
                ledger_deferred.add(record.fingerprint)
            elif record.state != "open":
                excluded.add(record.fingerprint)
    deferred = {}
    if state.analyzer_run is not None:
        deferred = {
            row.fingerprint: row
            for raw in state.analyzer_run.deferred_findings
            if (row := _DeferredRow.model_validate(raw)).scope == "change"
            and row.introduced_by_pr != "false"
            and row.fingerprint not in excluded
            and row.severity != "Trivial"
        }

    findings = {}
    for finding in packet.findings:
        severity = _eligible_severity(finding.severity)
        if (
            severity is None
            or finding.scope != "change"
            or finding.introduced_by_pr == "false"
            or finding.fingerprint in excluded
        ):
            continue
        status: FixStatus = (
            "deferred"
            if finding.fingerprint in deferred or finding.fingerprint in ledger_deferred
            else "actionable"
        )
        findings[finding.fingerprint] = _project_finding(finding, severity=severity, status=status)

    for fingerprint, row in deferred.items():
        severity = _eligible_severity(row.severity)
        if severity is not None and fingerprint not in findings:
            findings[fingerprint] = FixBriefFinding(
                fingerprint=fingerprint,
                status="deferred",
                severity=severity,
                path=redact_known_secret_patterns(row.path),
                start_line=row.line,
                end_line=row.end_line,
                message=redact_secrets(row.body),
                evidence=[],
                remediation=None,
            )

    return FixBrief(
        schema_version="1.0.0",
        change_id=packet.change_id,
        reviewed_head_sha=packet.reviewed_head_sha,
        findings=sorted(findings.values(), key=lambda row: (row.status, row.fingerprint)),
    )


def write_run_fix_brief(
    packet_path: Path, *, packet: MergeEvidencePacket, state: ToolState
) -> None:
    """Write the brief for a completed review when provenance is available.

    Args:
        packet_path: Path of the just-written evidence packet.
        packet: The assembled review evidence packet.
        state: Final review state supplying placement and lifecycle.
    """
    path = fix_brief_path(packet_path)
    brief = _assemble_fix_brief(packet, state)
    if brief is not None:
        encoded = (brief.model_dump_json(indent=2) + "\n").encode("utf-8")
        if len(encoded) > _MAX_BRIEF_BYTES:
            msg = "fix brief exceeds its size limit"
            raise ValueError(msg)
        write_bytes_atomically(path, encoded)
