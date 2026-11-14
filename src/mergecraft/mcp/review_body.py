"""Format review bodies and inline finding metadata.

Module: mergecraft.mcp.review_body
Depends: mergecraft.findings.ledger, mergecraft.mcp.tool_state

Exports:
    Functions:
        comment_fingerprint — Find the stable fingerprint of an inline comment.
        comment_fingerprints — Collect fingerprints for proposed inline comments.
        format_analyzer_inline_body — Format an analyzer finding for an inline comment.
        merge_deterministic_preamble_into_review_body — Insert the server-owned record.
        merge_review_body_with_deterministic_preamble — Render and insert the record.
        prepend_short_id — Stamp an inline comment with its publication short ID.
        publish_fingerprint_batch — Collect fingerprints for publication.
        publish_fingerprint_paths — Map published fingerprints to paths.
        rebuild_review_body_with_deterministic_preamble — Refresh the record after demotion.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import FINDING_SHORT_ID_PREFIX
from mergecraft.mcp.tool_state import loaded_review_skills_for_ledger
from mergecraft.review_taxonomy import finding_fingerprint

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.verdict import VerdictDiagnostic
    from mergecraft.run_outcome import RunOutcome

__all__ = [
    "comment_fingerprint",
    "comment_fingerprints",
    "format_analyzer_inline_body",
    "merge_deterministic_preamble_into_review_body",
    "merge_review_body_with_deterministic_preamble",
    "prepend_short_id",
    "publish_fingerprint_batch",
    "publish_fingerprint_paths",
    "rebuild_review_body_with_deterministic_preamble",
]


def merge_deterministic_preamble_into_review_body(
    *,
    agent_body: str,
    deterministic_block: str,
) -> str:
    """Prepend the server-owned deterministic record; agent copies cannot win (D7)."""
    from mergecraft.findings.ledger import (
        DETERMINISTIC_RECORD_MARKER,
        REVIEW_BODY_MARKER,
        strip_deterministic_record_markers,
    )

    cleaned_agent = strip_deterministic_record_markers(agent_body)
    block = deterministic_block.strip()
    if not block.startswith(DETERMINISTIC_RECORD_MARKER):
        block = f"{DETERMINISTIC_RECORD_MARKER}\n{block}"
    if cleaned_agent:
        return f"{block.rstrip()}\n{REVIEW_BODY_MARKER}\n\n{cleaned_agent.strip()}\n"
    return f"{block.rstrip()}\n{REVIEW_BODY_MARKER}\n"


def merge_review_body_with_deterministic_preamble(
    ctx: ToolContext,
    *,
    agent_body: str,
    packet: Any,
) -> str:
    """Render the deterministic preamble after demotion state is known (D7 / #572)."""
    deterministic_block = _deterministic_review_block(ctx, packet=packet)
    return merge_deterministic_preamble_into_review_body(
        agent_body=agent_body,
        deterministic_block=deterministic_block,
    )


def rebuild_review_body_with_deterministic_preamble(
    ctx: ToolContext,
    *,
    body: str,
    packet: Any,
) -> str:
    """Re-render the deterministic preamble on an existing review body."""
    from mergecraft.findings.ledger import strip_deterministic_record_markers

    agent_body = strip_deterministic_record_markers(body)
    return merge_review_body_with_deterministic_preamble(
        ctx,
        agent_body=agent_body,
        packet=packet,
    )


def _review_action_pin_sha() -> str | None:
    from mergecraft.build_metadata import resolve_action_pin_sha

    return resolve_action_pin_sha()


def _review_image_source_sha() -> str | None:
    from mergecraft.build_metadata import resolve_build_commit

    return resolve_build_commit()


def _deterministic_review_block(
    ctx: ToolContext,
    *,
    packet: Any,
    rejection_reason: str | None = None,
    run_outcome: RunOutcome | None = None,
    verdict_diagnostic: VerdictDiagnostic | str | None = None,
) -> str:
    from mergecraft.findings.ledger import render_deterministic_review_block
    from mergecraft.utils.run_bounds import token_summary_from_usage
    from mergecraft.utils.status_checks import github_run_url

    tool_state = ctx.tool_state
    analyzer_run = tool_state.analyzer_run
    analyzer_summary = analyzer_run.pre_merge_summary if analyzer_run is not None else None
    # The terminal summary remains in the review body below the server-owned
    # record; rendering it here would publish the same summary twice.
    attempt_count = len(tool_state.usage_entries) if tool_state.usage_entries else None
    token_summary = token_summary_from_usage(
        tool_state.usage_entries or [],
        budget_tracker=ctx.budget_tracker,
    )
    from mergecraft.agents.curated_model_catalog import cost_summary_from_usage_entries

    cost_summary = cost_summary_from_usage_entries(
        tool_state.usage_entries or [],
        budget_tracker=ctx.budget_tracker,
    )
    return render_deterministic_review_block(
        packet=packet,
        rejection_reason=rejection_reason,
        run_url=github_run_url(ctx),
        run_outcome=run_outcome,
        verdict_diagnostic=verdict_diagnostic,
        analyzer_summary=analyzer_summary,
        agent_summary=None,
        trust_tier=ctx.trust_tier,
        attempt_count=attempt_count,
        token_summary=token_summary,
        cost_summary=cost_summary,
        llm_review_timing=tool_state.llm_review_timing,
        publication_entrypoint=tool_state.review_publication_entrypoint,
        inline_comments_demoted=tool_state.review_inline_comments_demoted,
        comment_fallback_applied=tool_state.review_comment_fallback_applied,
        review_body_truncated=tool_state.review_body_truncated,
        credential_degradations=list(tool_state.credential_degradations),
        agent_sandbox_decision=tool_state.agent_sandbox_decision,
        action_pin_sha=_review_action_pin_sha(),
        image_source_sha=_review_image_source_sha(),
        review_skills=loaded_review_skills_for_ledger(tool_state),
        review_mcp_servers=list(tool_state.review_mcp_names),
    )


def format_analyzer_inline_body(
    finding: Finding,
    *,
    short_id: str | None = None,
    effort: str = "Quick win",
    verification_note: str | None = None,
) -> str:
    """Format an analyzer-sourced inline comment with tool citation and confidence (W7.6)."""
    tag = f"_{finding.category}_ | _{finding.severity}_ | _{effort}_ | _{finding.confidence}_"
    citation = f"`{finding.tool}` `{finding.rule_id}`"
    lines: list[str] = []
    if short_id:
        lines.append(f"**{short_id}**")
    lines.extend([tag, "", f"{finding.message}", "", f"Source: {citation}."])
    if verification_note:
        lines.extend(["", verification_note.strip()])
    return "\n".join(lines)


_SHORT_ID_LINE_RE = re.compile(
    rf"^\*\*{re.escape(FINDING_SHORT_ID_PREFIX)}[0-9a-f]{{6,}}\*\*\s*\n?",
    re.MULTILINE,
)


def _body_without_short_id_line(body: str) -> str:
    """Strip a leading publication short-id line before content fingerprinting."""
    return _SHORT_ID_LINE_RE.sub("", body, count=1).lstrip()


def comment_fingerprint(comment: dict[str, Any]) -> str:
    """Return the stable fingerprint for one inline comment row."""
    explicit = str(comment.get("fingerprint") or "").strip()
    if explicit:
        return explicit
    finding = comment.get("finding")
    if isinstance(finding, dict):
        nested = str(finding.get("fingerprint") or "").strip()
        if nested:
            return nested
    path = str(comment.get("path", ""))
    body = str(comment.get("body") or "")
    return finding_fingerprint(path=path, body=_body_without_short_id_line(body))


def comment_fingerprints(comments: list[dict[str, Any]]) -> list[str]:
    """Return the stable fingerprints of the proposed inline comments."""
    return [comment_fingerprint(comment) for comment in comments]


def _analyzer_publish_fingerprints(ctx: ToolContext) -> list[str]:
    """Return analyzer-run finding fingerprints merged into the review body."""
    analyzer_run = ctx.tool_state.analyzer_run
    if analyzer_run is None:
        return []
    fingerprints: list[str] = []
    for row in analyzer_run.findings:
        if isinstance(row, dict):
            fp = str(row.get("fingerprint", "")).strip()
            if fp:
                fingerprints.append(fp)
    return fingerprints


def publish_fingerprint_batch(
    comments: list[dict[str, Any]],
    ctx: ToolContext,
) -> list[str]:
    """Collect inline and body-appended fingerprints for one publish batch."""
    return comment_fingerprints(comments) + _analyzer_publish_fingerprints(ctx)


def publish_fingerprint_paths(
    comments: list[dict[str, Any]],
    ctx: ToolContext,
) -> dict[str, str]:
    """Map each publish-batch fingerprint to a path, so a skip warning can name it."""
    paths: dict[str, str] = {}
    for comment in comments:
        fingerprint = comment_fingerprint(comment)
        if fingerprint:
            paths.setdefault(fingerprint, str(comment.get("path") or "unknown"))
    analyzer_run = ctx.tool_state.analyzer_run
    if analyzer_run is not None:
        for row in analyzer_run.findings:
            if not isinstance(row, dict):
                continue
            fingerprint = str(row.get("fingerprint", "")).strip()
            if fingerprint:
                paths.setdefault(fingerprint, str(row.get("path") or "unknown"))
    return paths


def _body_has_short_id_line(body: str) -> bool:
    first_line = body.lstrip().split("\n", 1)[0]
    return bool(
        re.fullmatch(
            rf"\*\*{re.escape(FINDING_SHORT_ID_PREFIX)}[0-9a-f]{{6,}}\*\*",
            first_line,
        )
    )


def prepend_short_id(body: str, short_id: str) -> str:
    """Stamp or refresh the publication short-id line with batch-resolved ``short_id``."""
    marker = f"**{short_id}**"
    if not body.strip():
        return marker
    if _body_has_short_id_line(body):
        content = _body_without_short_id_line(body)
        if content.strip():
            return f"{marker}\n\n{content}"
        return marker
    title_match = re.match(
        rf"^\*\*{re.escape(FINDING_SHORT_ID_PREFIX)}[0-9a-f]{{6,}}\*\*(\s*\([^)]+\))\s*\n?",
        body.lstrip(),
    )
    if title_match:
        rest = body.lstrip()[title_match.end() :].lstrip()
        first_line = f"{marker}{title_match.group(1)}"
        if rest:
            return f"{first_line}\n\n{rest}"
        return first_line
    return f"{marker}\n\n{body}"
