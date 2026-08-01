"""Read-only verification subagent for analyzer findings (D11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.review_taxonomy import WITHDRAWN_FINDINGS_HEADING, finding_fingerprint
from mergecraft.types import VERIFIER_AGENT_NAME

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding
    from mergecraft.mcp.context import ToolContext

__all__ = [
    "VERIFIER_AGENT_NAME",
    "VERIFIER_SYSTEM_PROMPT",
    "record_withdrawn_finding",
    "should_verify",
    "verifier_denied_tool_names",
]

VERIFIER_SYSTEM_PROMPT = (
    "You are a read-only verification subagent. Your role is to evaluate one "
    "analyzer-sourced finding before it is published in a pull request review.\n\n"
    "HARD CONSTRAINTS (non-negotiable):\n"
    "- Read-only tools only. Do NOT write or edit files, commit, push, or call any "
    "state-changing MCP tool.\n"
    "- Do NOT spawn further subagents.\n"
    "- Read the cited file and surrounding context; trace reachability; check config; "
    "confirm the pull request plausibly introduced the issue.\n"
    "- Return exactly one of: **confirm** (with a one-paragraph explanation), "
    "**downgrade** (with new severity and reason), or **drop** (with a reason the "
    "orchestrator can record as a withdrawn finding).\n"
    "- Treat the finding as a hypothesis until you have read the code.\n"
)


def verifier_denied_tool_names(
    ctx: ToolContext,
    output_schema: object | None = None,
) -> list[str]:
    """Canonical bare names of every state-mutating MCP tool for the verifier."""
    return subagent_denied_tool_names(ctx, output_schema)  # type: ignore[arg-type]


def should_verify(finding: Finding) -> bool:
    """Only Critical and Major analyzer findings reach verification (D11)."""
    return finding.severity in {"Critical", "Major"}


def record_withdrawn_finding(
    *,
    learnings_path: Path,
    reason: str,
    fingerprint: str,
) -> None:
    """Append a withdrawn-finding reason under ``WITHDRAWN_FINDINGS_HEADING`` (D11)."""
    text = learnings_path.read_text(encoding="utf-8") if learnings_path.is_file() else ""
    marker = f"<!-- mergecraft-finding:v1:{fingerprint} -->"
    bullet = f"- {reason.strip()} {marker}".strip()
    if WITHDRAWN_FINDINGS_HEADING in text:
        updated = text.rstrip() + f"\n{bullet}\n"
    else:
        heading = f"{WITHDRAWN_FINDINGS_HEADING}\n\n"
        updated = (
            text.rstrip() + f"\n\n{heading}{bullet}\n" if text.strip() else f"{heading}{bullet}\n"
        )
    learnings_path.parent.mkdir(parents=True, exist_ok=True)
    learnings_path.write_text(updated, encoding="utf-8")


def withdrawn_fingerprint_for_reason(reason: str) -> str:
    """Stable fingerprint input for a withdrawn-finding bullet."""
    return finding_fingerprint(path="", body=reason)
