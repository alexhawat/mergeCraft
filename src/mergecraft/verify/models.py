"""Versioned behaviour-verification input and report contract.

The JSON Schema is derived from these models. Markdown is a view of the
JSON, not a second source of truth. Credentials are names only — never values.

Exports:
    VERIFICATION_SCHEMA_VERSION: Pinned report schema version (``1.0.0``).
    VERIFY_STATUSES: Closed verify-mode report statuses.
    REPRODUCE_STATUSES: Closed reproduce-mode report statuses.
    CRITERION_STATUSES: Closed per-criterion statuses.
    AuthSpec: Auth strategy for a run (env / manual / mock).
    Viewport: Pixel viewport.
    BlockedDetails: First-class blocked payload; ``missing`` is non-empty.
    VerificationStep: One recorded action.
    CriterionResult: Per-criterion status and evidence paths.
    ReportArtifacts: Screenshot, log, and nullable video/trace paths.
    VerificationInput: Union input from issues 61, 62, and 63.
    VerificationReport: Versioned report artifact (not a Finding).
    verification_report_schema: JSON Schema derived from ``VerificationReport``.
    is_successful: True only for verify ``pass`` or reproduce ``reproduced``.
    load_verification_input: YAML file → ``VerificationInput``.
    render_verification_markdown: Markdown view of a report's JSON.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from pathlib import Path

VERIFICATION_SCHEMA_VERSION: Final[str] = "1.0.0"

VERIFY_STATUSES: Final[frozenset[str]] = frozenset(
    {"pass", "fail", "partial", "blocked", "skipped"}
)
REPRODUCE_STATUSES: Final[frozenset[str]] = frozenset(
    {"reproduced", "not_reproduced", "partial", "blocked"}
)
CRITERION_STATUSES: Final[frozenset[str]] = frozenset({"pass", "fail", "unverified"})

VerificationMode = Literal["verify", "reproduce"]
AuthStrategy = Literal["env", "manual", "mock"]
CriterionStatus = Literal["pass", "fail", "unverified"]
ReportStatus = Literal[
    "pass",
    "fail",
    "partial",
    "blocked",
    "skipped",
    "reproduced",
    "not_reproduced",
]


class AuthSpec(BaseModel):
    """How the run obtains credentials — strategy only, never secret values."""

    model_config = ConfigDict(extra="forbid")

    strategy: AuthStrategy


class Viewport(BaseModel):
    """Pixel width and height for the browser window."""

    model_config = ConfigDict(extra="forbid")

    width: int
    height: int


class BlockedDetails(BaseModel):
    """Named inputs that prevented the run from executing."""

    model_config = ConfigDict(extra="forbid")

    missing: list[str] = Field(min_length=1)


class VerificationStep(BaseModel):
    """One recorded browser action and its observed result."""

    model_config = ConfigDict(extra="forbid")

    action: str
    target: str
    result: str


class CriterionResult(BaseModel):
    """One acceptance criterion with a closed status and evidence paths."""

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    status: CriterionStatus
    evidence: list[str]


class ReportArtifacts(BaseModel):
    """Paths and summaries written beside the report JSON.

    ``video`` is unused in this schema version. ``trace`` is present when the
    driver records one.
    """

    model_config = ConfigDict(extra="forbid")

    screenshots: list[str]
    video: str | None = None
    trace: str | None = None
    logs: list[str]
    network_summary: str | None = None


class VerificationInput(BaseModel):
    """Input for a reproduce or verify run — union of issues 61, 62, and 63."""

    model_config = ConfigDict(extra="forbid")

    mode: VerificationMode
    repo_path: str
    startup_command: str
    base: str
    base_url: str
    issue_or_pr: str
    acceptance_criteria: list[str]
    auth: AuthSpec
    credential_env_names: list[str]
    artifacts_dir: str
    viewport: Viewport
    device_targets: list[str]
    allowed_network: list[str]
    forbidden_network: list[str]
    prior_screenshots: list[str]
    repro_notes: str
    yaml_input: str | None = None


class VerificationReport(BaseModel):
    """Versioned behaviour-verification report. Not a ``Finding``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    mode: VerificationMode
    target: str
    target_url: str
    status: ReportStatus
    steps: list[VerificationStep]
    acceptance_criteria: list[CriterionResult]
    observed: str
    expected: str
    observed_mismatches: list[str]
    skipped_or_unverified: list[str]
    artifacts: ReportArtifacts
    console_errors: list[str]
    application_logs: list[str]
    suggested_next_fix: str
    blocked: BlockedDetails | None = None
    timestamp: str
    credential_names: list[str]

    @model_validator(mode="after")
    def _status_and_blocked_contract(self) -> Self:
        if self.mode == "verify" and self.status not in VERIFY_STATUSES:
            msg = f"status {self.status!r} is not valid for verify mode"
            raise ValueError(msg)
        if self.mode == "reproduce" and self.status not in REPRODUCE_STATUSES:
            msg = f"status {self.status!r} is not valid for reproduce mode"
            raise ValueError(msg)
        if self.status == "blocked" and self.blocked is None:
            msg = "blocked is required when status is blocked"
            raise ValueError(msg)
        return self


def verification_report_schema() -> dict[str, Any]:
    """Return the JSON Schema derived from ``VerificationReport``.

    Returns:
        dict[str, Any]: Schema object from ``VerificationReport.model_json_schema()``.

    Examples:
        >>> schema = verification_report_schema()
        >>> schema["type"]
        'object'
    """
    return VerificationReport.model_json_schema()


def is_successful(report: VerificationReport) -> bool:
    """Return True only for verify ``pass`` or reproduce ``reproduced``.

    Args:
        report (VerificationReport): A validated report.

    Returns:
        bool: True when the report is a successful outcome for its mode.

    Examples:
        >>> is_successful(VerificationReport.model_validate({
        ...     "schema_version": "1.0.0",
        ...     "mode": "verify",
        ...     "target": "x",
        ...     "target_url": "http://127.0.0.1/",
        ...     "status": "pass",
        ...     "steps": [],
        ...     "acceptance_criteria": [],
        ...     "observed": "",
        ...     "expected": "",
        ...     "observed_mismatches": [],
        ...     "skipped_or_unverified": [],
        ...     "artifacts": {"screenshots": [], "logs": []},
        ...     "console_errors": [],
        ...     "application_logs": [],
        ...     "suggested_next_fix": "",
        ...     "timestamp": "2026-09-18T00:00:00+00:00",
        ...     "credential_names": [],
        ... }))
        True
    """
    if report.mode == "verify":
        return report.status == "pass"
    return report.status == "reproduced"


def load_verification_input(path: Path) -> VerificationInput:
    """Load and validate a YAML verification input document.

    Args:
        path (Path): Path to a YAML mapping matching ``VerificationInput``.

    Returns:
        VerificationInput: Validated input. ``yaml_input`` stays unset unless
        the document names it.

    Raises:
        ValueError: When the file is not a YAML mapping.
        pydantic.ValidationError: When the mapping fails the input contract.

    Examples:
        >>> from pathlib import Path
        >>> isinstance(load_verification_input, object)
        True
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "verification input must be a YAML mapping"
        raise ValueError(msg)
    return VerificationInput.model_validate(raw)


def render_verification_markdown(report: VerificationReport) -> str:
    """Render a Markdown view of the report JSON — no invented fields.

    Args:
        report (VerificationReport): A validated report.

    Returns:
        str: Markdown whose heading is ``## Behavior verification`` or
        ``## Reproduction attempt``, including status, criteria text, and
        any ``blocked.missing`` names.

    Examples:
        >>> text = render_verification_markdown(VerificationReport.model_validate({
        ...     "schema_version": "1.0.0",
        ...     "mode": "verify",
        ...     "target": "x",
        ...     "target_url": "http://127.0.0.1/",
        ...     "status": "fail",
        ...     "steps": [],
        ...     "acceptance_criteria": [{
        ...         "id": "c1",
        ...         "text": "Clear button removes the image",
        ...         "status": "fail",
        ...         "evidence": [],
        ...     }],
        ...     "observed": "still there",
        ...     "expected": "gone",
        ...     "observed_mismatches": [],
        ...     "skipped_or_unverified": [],
        ...     "artifacts": {"screenshots": [], "logs": []},
        ...     "console_errors": [],
        ...     "application_logs": [],
        ...     "suggested_next_fix": "",
        ...     "timestamp": "2026-09-18T00:00:00+00:00",
        ...     "credential_names": [],
        ... }))
        >>> "## Behavior verification" in text
        True
    """
    heading = (
        "## Reproduction attempt" if report.mode == "reproduce" else "## Behavior verification"
    )
    payload = report.model_dump(mode="json")
    lines: list[str] = [heading, ""]
    for key, value in payload.items():
        rendered = (
            json.dumps(value, ensure_ascii=False, indent=2)
            if isinstance(value, dict | list)
            else str(value)
        )
        if "\n" in rendered:
            lines.extend((f"**{key}:**", "", rendered, ""))
        else:
            lines.extend((f"**{key}:** {rendered}", ""))
    return "\n".join(lines).rstrip() + "\n"
