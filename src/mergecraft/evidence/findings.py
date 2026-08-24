"""Public loader for the findings the approval gate and evidence packet share.

``report_status_checks`` posts check-runs; ``build_run_packet`` assembles the
packet. Both must see the same agent, analyzer, and CI set, so loading lives
here rather than in either layer. Merge, key, and row-validate live in
:mod:`mergecraft.evidence.merge` so this module and ``ci.evidence`` do not
import each other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.ci.evidence import ci_evidence_findings
from mergecraft.evidence.merge import merge_findings, typed_findings_from_rows

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.mcp.context import ToolContext


def load_run_findings(
    ctx: ToolContext,
    extra: list[Finding] | None = None,
) -> list[Finding]:
    """Return agent, analyzer, and CI findings the gate and packet both read.

    Validation errors are logged at debug and skipped. Deduplicates on
    :func:`mergecraft.evidence.merge.finding_dedupe_key` (fingerprint when present, otherwise
    tool/rule/path/line/message), keeping the more severe row on a collision.
    CI SARIF recorded on tool state is included so the approval check and
    the packet cannot diverge on #464 evidence.
    """
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
]
