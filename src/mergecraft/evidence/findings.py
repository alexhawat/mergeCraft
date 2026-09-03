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
from mergecraft.evidence.merge import merge_findings, typed_findings_from_rows_with_drops

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.mcp.context import ToolContext


def load_run_findings(
    ctx: ToolContext,
    extra: list[Finding] | None = None,
) -> list[Finding]:
    """Return agent, analyzer, and CI findings the gate and packet both read.

    Thin wrapper over :func:`load_run_findings_with_drops` for callers that
    never needed the drop count.
    """
    findings, _dropped = load_run_findings_with_drops(ctx, extra)
    return findings


def load_run_findings_with_drops(
    ctx: ToolContext,
    extra: list[Finding] | None = None,
) -> tuple[list[Finding], int]:
    """Return the gate/packet findings, plus how many stored rows were dropped.

    Identical to :func:`load_run_findings` except it also returns the number
    of ``agent_findings`` / analyzer rows that failed ``Finding`` validation
    and were discarded (see :func:`mergecraft.evidence.merge.typed_findings_from_rows_with_drops`).
    A dropped row is logged at ``warning`` there; the count is surfaced here
    so :mod:`mergecraft.evidence.run_packet` can record a run-health finding
    when the packet is known to be missing data (#623).

    Deduplicates on :func:`mergecraft.evidence.merge.finding_dedupe_key`
    (fingerprint when present, otherwise tool/rule/path/line/message),
    keeping the more severe row on a collision. CI SARIF recorded on tool
    state is included so the approval check and the packet cannot diverge on
    #464 evidence.
    """
    state = ctx.tool_state
    raw: list[Any] = list(state.agent_findings)
    run_state = state.analyzer_run
    if run_state is not None:
        raw.extend(list(run_state.findings))
    typed, dropped = typed_findings_from_rows_with_drops(raw)
    merged = merge_findings(
        typed,
        ci_evidence_findings(state),
        list(extra or []),
    )
    return merged, dropped


__all__ = [
    "load_run_findings",
    "load_run_findings_with_drops",
]
