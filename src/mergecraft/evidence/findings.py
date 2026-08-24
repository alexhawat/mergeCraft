"""Public loader for the findings the approval gate and evidence packet share.

``report_status_checks`` posts check-runs; ``build_run_packet`` assembles the
packet. Both must see the same agent, analyzer, and CI set, so loading lives
here rather than in either layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.analyzers.finding import Finding, FindingValidationError

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def typed_findings_from_rows(raw: list[Any]) -> list[Finding]:
    """Validate dict rows as ``Finding`` objects, skipping malformed ones."""
    typed: list[Finding] = []
    for row in raw:
        if isinstance(row, Finding):
            typed.append(row)
            continue
        if not isinstance(row, dict):
            continue
        try:
            typed.append(Finding.model_validate(row))
        except FindingValidationError as err:
            logger.debug("findings loader: dropping malformed finding row: {}", err)
    return typed


def _dedupe_key(finding: Finding) -> str:
    """Stable identity for merge: fingerprint, else tool/rule/path/line/message."""
    fingerprint = finding.fingerprint.strip() if finding.fingerprint else ""
    if fingerprint:
        return fingerprint
    return "|".join(
        (
            finding.tool,
            finding.rule_id,
            finding.path,
            str(finding.start_line or 0),
            finding.message,
        )
    )


def merge_findings(*groups: list[Finding]) -> list[Finding]:
    """Concatenate finding groups, dropping duplicate identity keys."""
    unique: list[Finding] = []
    seen: set[str] = set()
    for group in groups:
        for finding in group:
            key = _dedupe_key(finding)
            if key in seen:
                continue
            seen.add(key)
            unique.append(finding)
    return unique


def load_run_findings(
    ctx: ToolContext,
    extra: list[Finding] | None = None,
) -> list[Finding]:
    """Return agent, analyzer, and CI findings the gate and packet both read.

    Validation errors are logged at debug and skipped. Deduplicates on
    :func:`_dedupe_key` (fingerprint when present, otherwise
    tool/rule/path/line/message). CI SARIF recorded on tool state is included
    so the approval check and the packet cannot diverge on #464 evidence.
    """
    from mergecraft.ci.evidence import ci_evidence_findings

    raw: list[Any] = []
    agent_rows = getattr(ctx.tool_state, "agent_findings", None)
    if agent_rows:
        raw.extend(list(agent_rows))
    run_state = getattr(ctx.tool_state, "analyzer_run", None)
    if run_state is not None:
        raw.extend(list(getattr(run_state, "findings", []) or []))
    return merge_findings(
        typed_findings_from_rows(raw),
        ci_evidence_findings(ctx.tool_state),
        list(extra or []),
    )


__all__ = [
    "load_run_findings",
    "merge_findings",
    "typed_findings_from_rows",
]
