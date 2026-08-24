"""Public loader for the findings the approval gate and evidence packet share.

``report_status_checks`` posts check-runs; ``build_run_packet`` assembles the
packet. Both must see the same agent, analyzer, and CI set, so loading lives
here rather than in either layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import ValidationError

from mergecraft.analyzers.finding import Finding, FindingValidationError
from mergecraft.review_taxonomy import FINDING_SEVERITIES

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_SEVERITY_RANK: dict[str, int] = {name: index for index, name in enumerate(FINDING_SEVERITIES)}


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
        except (FindingValidationError, ValidationError, ValueError) as err:
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


def _severity_rank(finding: Finding) -> int:
    """Lower is more severe. Unknown grades sort after the taxonomy."""
    return _SEVERITY_RANK.get(finding.severity, len(_SEVERITY_RANK))


def merge_findings(*groups: list[Finding]) -> list[Finding]:
    """Concatenate finding groups, keeping the more severe duplicate identity.

    First-seen order is preserved. When fingerprints (or fallback keys)
    collide, Major/Critical wins over Minor/Trivial so a CI blocker is not
    dropped behind a less severe agent copy.
    """
    unique: dict[str, Finding] = {}
    order: list[str] = []
    for group in groups:
        for finding in group:
            key = _dedupe_key(finding)
            existing = unique.get(key)
            if existing is None:
                unique[key] = finding
                order.append(key)
                continue
            if _severity_rank(finding) < _severity_rank(existing):
                unique[key] = finding
    return [unique[key] for key in order]


def load_run_findings(
    ctx: ToolContext,
    extra: list[Finding] | None = None,
) -> list[Finding]:
    """Return agent, analyzer, and CI findings the gate and packet both read.

    Validation errors are logged at debug and skipped. Deduplicates on
    :func:`_dedupe_key` (fingerprint when present, otherwise
    tool/rule/path/line/message), keeping the more severe row on a collision.
    CI SARIF recorded on tool state is included so the approval check and
    the packet cannot diverge on #464 evidence.
    """
    from mergecraft.ci.evidence import ci_evidence_findings

    state = ctx.tool_state
    raw: list[Any] = list(state.agent_findings)
    run_state = state.analyzer_run
    if run_state is not None:
        raw.extend(list(run_state.findings))
    return merge_findings(
        typed_findings_from_rows(raw),
        ci_evidence_findings(state),
        list(extra or []),
    )


__all__ = [
    "load_run_findings",
    "merge_findings",
    "typed_findings_from_rows",
]
