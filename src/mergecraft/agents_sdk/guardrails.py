"""Output guardrails for Agents SDK review findings."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from mergecraft.agents_sdk.types import ReviewFinding, ReviewFindingsReport
from mergecraft.analyzers.redact import _SECRET_PATTERNS, redact_secrets
from mergecraft.redaction_sentinel import REDACTION_SENTINEL

if TYPE_CHECKING:
    from agents.guardrail import GuardrailFunctionOutput

    from agents import Agent, RunContextWrapper

def _normalize_repo_path(path: str) -> str | None:
    cleaned = path.replace("\\", "/").strip()
    while cleaned.startswith("./"):
        cleaned = cleaned.removeprefix("./")
    if not cleaned or cleaned.startswith("/"):
        return None
    parts: list[str] = []
    for part in PurePosixPath(cleaned).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        return None
    return PurePosixPath(*parts).as_posix()


def path_in_change_set(path: str, allowed_paths: frozenset[str]) -> bool:
    """Return whether ``path`` is the same as or under an allowed changed path."""
    if not allowed_paths:
        return True
    normalized = _normalize_repo_path(path)
    if normalized is None:
        return False
    for allowed in allowed_paths:
        root = _normalize_repo_path(allowed)
        if root is None:
            continue
        if normalized == root or normalized.startswith(f"{root}/"):
            return True
    return False


def _text_contains_secret_pattern(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def _redact_text(text: str) -> str:
    return redact_secrets(text)


def finding_looks_like_secret(finding: ReviewFinding) -> bool:
    blob = " ".join(
        part for part in (finding.message, finding.suggested_fix or "") if part
    )
    if _text_contains_secret_pattern(blob):
        return True
    redacted = _redact_text(blob)
    return redacted != blob and REDACTION_SENTINEL in redacted


def _sanitize_summary(summary: str) -> str:
    if not summary:
        return summary
    if _text_contains_secret_pattern(summary):
        return REDACTION_SENTINEL
    redacted = _redact_text(summary)
    return redacted if redacted != summary else summary


def filter_guarded_findings(
    report: ReviewFindingsReport,
    *,
    allowed_paths: frozenset[str],
) -> tuple[ReviewFindingsReport, list[str]]:
    """Drop findings outside the change set or containing secret-like strings."""
    kept: list[ReviewFinding] = []
    violations: list[str] = []
    for row in report.findings:
        if not path_in_change_set(row.file, allowed_paths):
            violations.append(f"finding references path outside change set: {row.file!r}")
            continue
        if finding_looks_like_secret(row):
            violations.append(f"finding message looks secret-like for {row.file!r}")
            continue
        kept.append(row)
    summary = _sanitize_summary(report.summary)
    if summary != report.summary and report.summary.strip():
        violations.append("summary contained secret-like strings and was redacted")
    return ReviewFindingsReport(findings=kept, summary=summary), violations


def review_output_guardrail(
    allowed_paths: frozenset[str],
) -> Any:
    """Build an Agents SDK output guardrail bound to ``allowed_paths``."""
    from agents.guardrail import GuardrailFunctionOutput

    from agents import output_guardrail

    @output_guardrail(name="mergecraft_review_scope_and_secrets")
    async def _guard(
        _ctx: RunContextWrapper[Any],
        _agent: Agent[Any],
        output: ReviewFindingsReport,
    ) -> GuardrailFunctionOutput:
        _, violations = filter_guarded_findings(output, allowed_paths=allowed_paths)
        blocking = [item for item in violations if "redacted" not in item]
        if blocking:
            return GuardrailFunctionOutput(
                output_info={"violations": blocking},
                tripwire_triggered=True,
            )
        return GuardrailFunctionOutput(output_info={}, tripwire_triggered=False)

    return _guard


__all__ = [
    "filter_guarded_findings",
    "finding_looks_like_secret",
    "path_in_change_set",
    "review_output_guardrail",
]
