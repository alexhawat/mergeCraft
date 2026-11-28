"""The report document an Agents SDK pull-request review hands to whoever publishes it.

A workflow that reviews with the Agents SDK usually has no GitHub token, so it
cannot post the review itself. It writes this document instead (as a file, or
as the ``mergecraft-agents-sdk-review`` workflow artifact), and a publisher that
holds the GitHub login, such as a self-hosted CI service, turns it into the
pull request's review message. The document is the contract between the two:
``AGENTS_SDK_REVIEW_SCHEMA`` names its version and ``AgentsSdkReviewReport``
validates it. ``render_review_markdown`` renders it in the shape of a mergeCraft
review for hosts that show markdown, such as a job summary.

Everything in the document came from a model reading pull-request content, so a
publisher must treat it as untrusted text: ``render_review_markdown`` escapes
Markdown and HTML, neutralises mentions and caps its length.
"""

# No ``from __future__ import annotations``: Pydantic resolves the field types
# below at class creation, so the imported types are needed at runtime anyway.
import re
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.agents_sdk.guardrails import filter_guarded_findings
from mergecraft.agents_sdk.types import ReviewFinding, ReviewFindingsReport
from mergecraft.findings.severity import BLOCKING_SEVERITIES, severity_rank

AGENTS_SDK_REVIEW_SCHEMA: Final = "mergecraft.agents-sdk-review.v1"
# The workflow artifact name and the JSON file inside it.
AGENTS_SDK_REVIEW_ARTIFACT = "mergecraft-agents-sdk-review"
AGENTS_SDK_REVIEW_FILENAME = f"{AGENTS_SDK_REVIEW_ARTIFACT}.json"

ReviewStatus = Literal["reviewed", "skipped", "error"]

_MAX_MARKDOWN_CHARS = 60_000
_MARKDOWN_PUNCTUATION = re.compile(r"([\\`*_{}\[\]()#+.!|~>=$-])")


class ReviewUsage(BaseModel):
    """Model usage the Agents SDK reported for the review run."""

    model_config = ConfigDict(extra="forbid")

    requests: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class AgentsSdkReviewReport(BaseModel):
    """One pull-request review, ready for a publisher (schema ``AGENTS_SDK_REVIEW_SCHEMA``)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # Required, with no default: a document without its version marker is rejected
    # rather than read as v1. ``build_review_report`` supplies it.
    # Read and written as ``schema``, set as ``schema_id`` in Python: separate
    # validation and serialization aliases keep the constructor keyword the field
    # name for both mypy's Pydantic plugin and pyright.
    schema_id: Literal["mergecraft.agents-sdk-review.v1"] = Field(
        validation_alias="schema", serialization_alias="schema"
    )
    status: ReviewStatus
    reason: str | None = Field(
        default=None, description="Why the review was skipped or failed; null when reviewed."
    )
    pull_request: int | None = Field(default=None, ge=1)
    base_sha: str | None = None
    head_sha: str | None = Field(
        default=None, description="The commit reviewed; a publisher binds the message to it."
    )
    model: str | None = None
    summary: str = ""
    findings: list[ReviewFinding] = Field(default_factory=list)
    dropped: list[str] = Field(
        default_factory=list,
        description="Why the guardrails removed findings (outside the change set, secret-like).",
    )
    changed_files: list[str] = Field(
        default_factory=list, description="Files whose diff the reviewer was given."
    )
    omitted_files: list[str] = Field(
        default_factory=list,
        description="Changed files listed to the reviewer without content (generated, lockfiles).",
    )
    usage: ReviewUsage | None = None

    def blocking_findings(self) -> list[ReviewFinding]:
        """Findings at Major severity or above (mergeCraft gate convention)."""
        return [row for row in self.findings if row.severity in BLOCKING_SEVERITIES]

    def passed(self) -> bool:
        """Whether the review completed (or had nothing to review) without blocking findings."""
        return self.status != "error" and not self.blocking_findings()

    def to_json(self) -> str:
        """The document as JSON, with the ``schema`` key publishers look for."""
        return self.model_dump_json(by_alias=True, indent=2)


def build_review_report(
    output: ReviewFindingsReport,
    *,
    allowed_paths: frozenset[str],
    model: str | None = None,
    pull_request: int | None = None,
    base_sha: str | None = None,
    head_sha: str | None = None,
    omitted_files: list[str] | None = None,
    usage: ReviewUsage | None = None,
) -> AgentsSdkReviewReport:
    """Apply the review guardrails to an agent's output and wrap it as a report document.

    Findings outside ``allowed_paths`` or that look like secrets are removed and
    listed in ``dropped``, the same rules as ``filter_guarded_findings``.
    """
    guarded, dropped = filter_guarded_findings(output, allowed_paths=allowed_paths)
    return AgentsSdkReviewReport(
        schema_id=AGENTS_SDK_REVIEW_SCHEMA,
        status="reviewed",
        pull_request=pull_request,
        base_sha=base_sha,
        head_sha=head_sha,
        model=model,
        summary=guarded.summary,
        findings=guarded.findings,
        dropped=dropped,
        changed_files=sorted(allowed_paths),
        omitted_files=sorted(omitted_files or []),
        usage=usage,
    )


def _literal(value: object, *, block: bool = False) -> str:
    """Render untrusted text as text: no Markdown structure, HTML, links or mentions."""
    text = (
        str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("@", "@​")
    )
    text = _MARKDOWN_PUNCTUATION.sub(r"\\\1", text)
    lines = re.split(r"\r\n|\r|\n", text)
    if not block:
        return " ".join(line.strip() for line in lines if line.strip())
    # Leading indentation would turn lines into code blocks or list continuations.
    return "\n".join(line.lstrip(" \t") for line in lines)


def _location(finding: ReviewFinding) -> str:
    return _literal(f"{finding.file}:{finding.line}" if finding.line else finding.file)


def _outcome(report: AgentsSdkReviewReport) -> str:
    if report.status == "error":
        return "review failed"
    if report.status == "skipped":
        return "skipped"
    blocking = len(report.blocking_findings())
    if blocking:
        return f"changes requested: {blocking} blocking of {len(report.findings)} findings"
    if report.findings:
        return f"passed with {len(report.findings)} non-blocking findings"
    return "passed: no findings"


def render_review_markdown(report: AgentsSdkReviewReport) -> str:
    """Render the report as a mergeCraft review message, with every field escaped."""
    usage = report.usage
    tokens = (
        f"{usage.input_tokens} input · {usage.output_tokens} output · {usage.requests} model requests"
        if usage
        else "not recorded"
    )
    commit = f"`{_literal(report.head_sha)[:40]}`" if report.head_sha else "not recorded"
    lines = [
        "### mergeCraft review (OpenAI Agents SDK)",
        "",
        f"- Outcome: **{_outcome(report)}**",
        "- Failure threshold: Major and above",
        f"- Reviewed commit: {commit}",
        f"- Model: {_literal(report.model or 'not recorded')}",
        f"- Tokens: {tokens}",
        f"- Scope: {len(report.changed_files)} files reviewed · "
        f"{len(report.omitted_files)} generated files listed without content",
    ]
    if report.reason:
        lines.append(f"- Reason: {_literal(report.reason)}")
    lines += ["", "#### Findings", ""]
    ordered = sorted(report.findings, key=lambda f: -severity_rank(f.severity))
    for finding in ordered:
        lines += [
            f"##### {finding.severity} — {_location(finding)}",
            "",
            _literal(finding.message, block=True),
            "",
        ]
        if finding.suggested_fix:
            lines += [f"- Suggested fix: {_literal(finding.suggested_fix)}", ""]
    if not ordered:
        lines += [
            "No findings. This alone is not an approval."
            if report.status == "reviewed"
            else "No review was completed, so there are no findings to show.",
            "",
        ]
    if report.dropped:
        lines += [f"{len(report.dropped)} findings were dropped by the guardrails:"]
        lines += [f"- {_literal(reason)}" for reason in report.dropped[:50]]
        lines.append("")
    lines += ["#### Summary", "", _literal(report.summary or "(no summary)", block=True), ""]
    lines.append("Findings are a model's claims; check each one.")
    body = "\n".join(lines)
    if len(body) > _MAX_MARKDOWN_CHARS:
        body = body[: _MAX_MARKDOWN_CHARS - 100] + "\n\nReview truncated."
    return body


__all__ = [
    "AGENTS_SDK_REVIEW_ARTIFACT",
    "AGENTS_SDK_REVIEW_FILENAME",
    "AGENTS_SDK_REVIEW_SCHEMA",
    "AgentsSdkReviewReport",
    "ReviewStatus",
    "ReviewUsage",
    "build_review_report",
    "render_review_markdown",
]
