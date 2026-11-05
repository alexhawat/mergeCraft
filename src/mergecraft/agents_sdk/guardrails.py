"""Output guardrails for Agents SDK review findings."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from mergecraft.agents_sdk.types import ReviewFinding, ReviewFindingsReport
from mergecraft.analyzers.redact import redact_secrets

if TYPE_CHECKING:
    from agents.guardrail import GuardrailFunctionOutput

    from agents import Agent, RunContextWrapper

_SECRET_PROBE = re.compile(
    r"(?i)(ghp_[a-zA-Z0-9]{20,}|sk-[a-zA-Z0-9]{10,}|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----)"
)


def _normalize_repo_path(path: str) -> str:
    cleaned = path.replace("\\", "/").lstrip("./")
    return PurePosixPath(cleaned).as_posix()


def path_in_change_set(path: str, allowed_paths: frozenset[str]) -> bool:
    """Return whether ``path`` is the same as or under an allowed changed path."""
    if not allowed_paths:
        return True
    normalized = _normalize_repo_path(path)
    for allowed in allowed_paths:
        root = _normalize_repo_path(allowed)
        if normalized == root or normalized.startswith(f"{root}/"):
            return True
    return False


def finding_looks_like_secret(finding: ReviewFinding) -> bool:
    blob = " ".join(part for part in (finding.message, finding.suggested_fix or "") if part)
    if _SECRET_PROBE.search(blob):
        return True
    redacted = redact_secrets(blob)
    return redacted != blob and "<redacted>" in redacted


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
    return ReviewFindingsReport(findings=kept, summary=report.summary), violations


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
        if violations:
            return GuardrailFunctionOutput(
                output_info={"violations": violations},
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
