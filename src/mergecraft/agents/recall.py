"""Read-only recall pass subagent — the verifier's mirror (RC10, D1, D7).

Receives the full diff and the orchestrator's draft finding list; may only
return findings absent from that list. Output is forced into the deferred lane
regardless of claimed severity (D1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.findings.dedup import dedupe_findings, dedupe_findings_with_indices

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mergecraft.agents.registry import AgentBinding
    from mergecraft.analyzers.finding import Finding
    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import ToolState

__all__ = [
    "RECALL_SYSTEM_PROMPT",
    "RecallPassPlan",
    "build_recall_pass_brief",
    "filter_novel_recall_findings",
    "plan_recall_pass",
    "recall_denied_tool_names",
]

RECALL_SYSTEM_PROMPT = (
    "You are a read-only recall subagent — the verifier's mirror. Your only job "
    "is to find actionable defects in the diff that the orchestrator's draft "
    "finding list missed.\n\n"
    "HARD CONSTRAINTS (non-negotiable):\n"
    "- Read-only tools only. Do NOT mutate repository state, publish reviews, "
    "record verdicts, or call terminal-protocol tools.\n"
    "- Your dispatch includes the authoritative diff and the draft findings the "
    "orchestrator already plans to publish. You may return only findings that "
    "are absent from that draft — paraphrases and overlaps with an existing draft "
    "row are forbidden.\n"
    "- Every finding must cite concrete code: file path, line number(s), and "
    "quoted evidence from the diff or files you read.\n"
    "- Do NOT re-raise findings the draft already covers, praise, style nits, or "
    "speculative claims you cannot anchor.\n"
    "- Do NOT spawn further subagents. You are a leaf reviewer.\n\n"
    "Return typed findings at the boundary when your harness supports structured "
    "output; otherwise end with a `---typed-findings---` JSON array of findings "
    "not already represented in the draft list."
)


class RecallPassPlan(BaseModel):
    """Budgeted recall dispatch the orchestrator should run after aggregation."""

    model_config = ConfigDict(extra="forbid")

    budget: int
    timeout_s: int
    brief: str


def _format_draft_row(row: Mapping[str, object]) -> str:
    path = str(row.get("path") or "")
    line = row.get("line", row.get("start_line", ""))
    severity = str(row.get("severity") or "Minor")
    body = str(row.get("body") or row.get("message") or "").strip()
    return f"- **{severity}** `{path}:{line}` — {body}"


def build_recall_pass_brief(
    *,
    diff_text: str,
    draft_findings: Sequence[Mapping[str, object]],
) -> str:
    """Build the recall dispatch brief from the diff and draft findings."""
    lines = [
        "Recall pass — find defects absent from the draft list.",
        "",
        "### Diff",
        "",
        diff_text.strip() or "(empty diff)",
        "",
        "### Draft findings already planned for publication",
        "",
    ]
    if draft_findings:
        lines.extend(_format_draft_row(row) for row in draft_findings)
    else:
        lines.append("(none — the orchestrator has not drafted any findings yet.)")
    lines.extend(
        [
            "",
            "Return only novel findings with file:line citations and quoted evidence.",
        ]
    )
    return "\n".join(lines)


def plan_recall_pass(
    *,
    diff_text: str,
    draft_findings: Sequence[Mapping[str, object]],
    binding: AgentBinding,
    settings: RepoSettings,
    tool_state: ToolState,
) -> RecallPassPlan:
    """Return round-scaled recall dispatch limits and brief for one orchestrator run."""
    from mergecraft.mcp.convergence_runtime import build_recall_dispatch_plan

    return build_recall_dispatch_plan(
        diff_text=diff_text,
        draft_findings=draft_findings,
        binding=binding,
        settings=settings,
        tool_state=tool_state,
    )


def filter_novel_recall_findings(
    draft: Sequence[Finding],
    recalled: Sequence[Finding],
) -> list[Finding]:
    """Return recalled findings that are not duplicates of the draft list."""
    if not recalled:
        return []
    from mergecraft.findings.dedup import location_key

    draft_rows = dedupe_findings_with_indices(list(draft)).findings
    occupied = {location_key(finding) for finding in draft_rows}
    candidates = [finding for finding in recalled if location_key(finding) not in occupied]
    return dedupe_findings(candidates)


def recall_denied_tool_names(ctx: ToolContext) -> list[str]:
    """Denied tools for the recall subagent — same containment as reviewer."""
    return subagent_denied_tool_names(ctx)
