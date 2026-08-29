"""Cross-round finding ledger — open-PR memory in the sticky progress comment (RC4, D4).

Persistence is GitHub-only: HTML markers in the progress comment survive ephemeral
Action checkouts. Post-merge issue filing stays in :mod:`mergecraft.findings.sweep`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote

from loguru import logger

from mergecraft.findings.lifecycle import LifecycleRecord, LifecycleState, validate_lifecycle_state

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import AnalyzerRunState, ToolState
    from mergecraft.scm.protocol import ScmProvider

LEDGER_MARKER_PREFIX: str = "<!-- mergecraft-ledger:v1:"
LEDGER_MARKER_V2_PREFIX: str = "<!-- mergecraft-ledger:v2:"
LEDGER_SCHEMA_VERSION: str = "v2"
DETERMINISTIC_RECORD_MARKER: str = "<!-- mergecraft-deterministic-record:v1 -->"

_PROGRESS_HEADING = "## mergeCraft progress"
_VIA_MERGECRAFT_MARKER = "*via mergecraft*"

_LEDGER_MARKER_RE = re.compile(r"<!-- mergecraft-ledger:v1:([0-9a-f]+):([a-z-]+)(?::([^>]*?))? -->")
_LEDGER_MARKER_V2_RE = re.compile(r"<!-- mergecraft-ledger:v2:([0-9a-f]+):([a-z-]+):([^>]+) -->")
_DETERMINISTIC_RECORD_BLOCK_RE = re.compile(
    rf"{re.escape(DETERMINISTIC_RECORD_MARKER)}[\s\S]*?"
    r"(?=\n<!-- mergecraft-ledger:|\n\*via mergecraft\*|\Z)",
)

_ISSUE_COMMENT_PAGE_SIZE = 100
# GitHub issue comments are paginated at 100/page; cap total scanned comments
# at 1000 (10 pages) to bound API cost on very chatty PRs.
_MAX_ISSUE_COMMENT_PAGES = 10


@dataclass
class FindingLedger:
    """In-run ledger keyed by review-taxonomy fingerprint."""

    _records: dict[str, LifecycleRecord] = field(default_factory=dict)

    def record(
        self,
        fingerprint: str,
        state: LifecycleState,
        *,
        source: str,
        round_index: int,
        reason: str | None = None,
        recorded_at: str | None = None,
    ) -> LifecycleRecord:
        """Upsert one lifecycle transition for ``fingerprint``."""
        stamp = recorded_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
        record = LifecycleRecord(
            fingerprint=fingerprint,
            state=state,
            reason=reason,
            round_index=round_index,
            recorded_at=stamp,
            source=source,
        )
        self._records[fingerprint] = record
        return record

    def promote(
        self,
        fingerprint: str,
        *,
        reason: str,
        recorded_at: str,
        round_index: int | None = None,
    ) -> LifecycleRecord:
        """Promote a deferred finding back to ``open`` with an audit trail (convention 4)."""
        prior = self._records.get(fingerprint)
        resolved_round = round_index
        if resolved_round is None:
            resolved_round = (
                prior.round_index if prior is not None and prior.round_index is not None else 1
            )
        return self.record(
            fingerprint,
            "open",
            source=(prior.source if prior is not None and prior.source else "promotion"),
            round_index=resolved_round,
            reason=reason,
            recorded_at=recorded_at,
        )

    def records(self) -> list[LifecycleRecord]:
        """Return ledger records in stable fingerprint order."""
        return [self._records[key] for key in sorted(self._records)]

    def get_record(self, fingerprint: str) -> LifecycleRecord | None:
        """Return the ledger row for ``fingerprint``, if present."""
        return self._records.get(fingerprint)

    def upsert_if_newer(self, record: LifecycleRecord) -> LifecycleRecord:
        """Insert ``record`` or replace the stored row when it is newer."""
        prior = self._records.get(record.fingerprint)
        if prior is None:
            self._records[record.fingerprint] = record
            return record
        prior_at = prior.recorded_at or ""
        new_at = record.recorded_at or ""
        if new_at > prior_at:
            self._records[record.fingerprint] = record
            return record
        return prior

    def render_ledger_block(self) -> str:
        """Serialize all records to HTML ledger markers."""
        lines = [line for record in self.records() for line in _marker_lines(record)]
        return "\n".join(lines)

    @classmethod
    def from_comment_body(cls, body: str) -> FindingLedger:
        """Parse ledger markers from a progress-comment body."""
        records: dict[str, LifecycleRecord] = {}
        for match in _LEDGER_MARKER_V2_RE.finditer(body):
            fingerprint, raw_state, encoded_meta = (
                match.group(1),
                match.group(2),
                match.group(3),
            )
            record = _record_from_v2_marker(fingerprint, raw_state, encoded_meta)
            if record is not None:
                records[fingerprint] = record
        for match in _LEDGER_MARKER_RE.finditer(body):
            fingerprint, raw_state, encoded_path = match.group(1), match.group(2), match.group(3)
            if fingerprint in records:
                continue
            record = _record_from_v1_marker(fingerprint, raw_state, encoded_path)
            if record is not None:
                records[fingerprint] = record
        return cls(_records=records)


def ledger_round_index(tool_state: ToolState) -> int:
    """Return the active 1-based review round for ledger ``record_*`` call sites."""
    return max(int(tool_state.review_round_index or 1), 1)


def is_sticky_progress_comment(body: str) -> bool:
    """Return whether ``body`` looks like the mergeCraft sticky progress comment."""
    lowered = body.lower()
    return (
        DETERMINISTIC_RECORD_MARKER in body
        or LEDGER_MARKER_PREFIX in body
        or LEDGER_MARKER_V2_PREFIX in body
        or _PROGRESS_HEADING in body
        or _VIA_MERGECRAFT_MARKER in lowered
    )


def _select_sticky_progress_comment(
    comments: Sequence[Mapping[str, object]],
    *,
    return_body: bool,
) -> str | dict[str, Any] | None:
    """Select the sticky progress comment; ledger markers win over heading heuristics."""
    progress_body = ""
    progress: dict[str, Any] | None = None
    for comment in comments:
        body = str(comment.get("body") or "")
        if LEDGER_MARKER_PREFIX in body or LEDGER_MARKER_V2_PREFIX in body:
            return body if return_body else dict(comment)
        if is_sticky_progress_comment(body):
            if return_body:
                progress_body = body
            else:
                progress = dict(comment)
    return progress_body if return_body else progress


def sticky_progress_comment_body(comments: Sequence[Mapping[str, object]]) -> str:
    """Select the sticky progress comment body from issue comments (ledger wins)."""
    selected = _select_sticky_progress_comment(comments, return_body=True)
    return selected if isinstance(selected, str) else ""


def sticky_progress_comment(comments: Sequence[Mapping[str, object]]) -> dict[str, Any] | None:
    """Select the sticky progress comment from issue comments (ledger markers win)."""
    selected = _select_sticky_progress_comment(comments, return_body=False)
    return selected if isinstance(selected, dict) else None


async def _list_issue_comments_paginated(
    scm: ScmProvider,
    owner: str,
    repo: str,
    issue_number: int,
) -> list[dict[str, Any]]:
    """Fetch issue comments across pages, capped at ``_MAX_ISSUE_COMMENT_PAGES``."""
    collected: list[dict[str, Any]] = []
    for page in range(1, _MAX_ISSUE_COMMENT_PAGES + 1):
        comments = await scm.list_issue_comments(
            owner,
            repo,
            issue_number,
            params={"per_page": _ISSUE_COMMENT_PAGE_SIZE, "page": page},
        )
        collected.extend(comments)
        if len(comments) < _ISSUE_COMMENT_PAGE_SIZE:
            break
    return collected


async def fetch_sticky_progress_comment(
    scm: ScmProvider,
    owner: str,
    repo: str,
    issue_number: int,
    *,
    known_comment_id: int | None = None,
) -> dict[str, Any] | None:
    """Load the sticky progress comment dict by id or from paginated issue comments."""
    if known_comment_id is not None:
        comment = await scm.get_issue_comment(owner, repo, known_comment_id)
        return dict(comment)
    comments = await _list_issue_comments_paginated(scm, owner, repo, issue_number)
    return sticky_progress_comment(comments)


async def fetch_sticky_progress_comment_body(
    scm: ScmProvider,
    owner: str,
    repo: str,
    issue_number: int,
    *,
    known_comment_id: int | None = None,
) -> str:
    """Load the sticky progress comment body by id or from paginated issue comments."""
    sticky = await fetch_sticky_progress_comment(
        scm,
        owner,
        repo,
        issue_number,
        known_comment_id=known_comment_id,
    )
    return str(sticky.get("body") or "") if sticky is not None else ""


def _record_from_v1_marker(
    fingerprint: str,
    raw_state: str,
    encoded_path: str | None,
) -> LifecycleRecord | None:
    try:
        state = validate_lifecycle_state(raw_state)
    except ValueError:
        logger.warning(
            "finding ledger: skipping marker with unknown state {} for fingerprint {}",
            raw_state,
            fingerprint,
        )
        return None
    reason = None
    if encoded_path:
        reason = f"path:{unquote(encoded_path)}"
    return LifecycleRecord(
        fingerprint=fingerprint,
        state=state,
        reason=reason,
    )


def _record_from_v2_marker(
    fingerprint: str,
    raw_state: str,
    encoded_meta: str,
) -> LifecycleRecord | None:
    try:
        state = validate_lifecycle_state(raw_state)
    except ValueError:
        logger.warning(
            "finding ledger: skipping v2 marker with unknown state {} for fingerprint {}",
            raw_state,
            fingerprint,
        )
        return None
    try:
        payload = json.loads(unquote(encoded_meta))
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning(
            "finding ledger: skipping v2 marker with invalid metadata for fingerprint {}",
            fingerprint,
        )
        return None
    if not isinstance(payload, dict):
        return None
    reason = payload.get("reason")
    round_index = payload.get("round_index")
    recorded_at = payload.get("recorded_at")
    source = payload.get("source")
    try:
        resolved_round = int(round_index) if round_index is not None else None
    except (TypeError, ValueError):
        logger.warning(
            "finding ledger: skipping v2 marker with invalid round_index for fingerprint {}",
            fingerprint,
        )
        return None
    return LifecycleRecord(
        fingerprint=fingerprint,
        state=state,
        reason=str(reason) if reason else None,
        round_index=resolved_round,
        recorded_at=str(recorded_at) if recorded_at else None,
        source=str(source) if source else None,
    )


def _marker_lines(record: LifecycleRecord) -> list[str]:
    metadata: dict[str, object] = {}
    if record.round_index is not None:
        metadata["round_index"] = record.round_index
    if record.recorded_at:
        metadata["recorded_at"] = record.recorded_at
    if record.source:
        metadata["source"] = record.source
    if record.reason:
        metadata["reason"] = record.reason
    if metadata:
        encoded = quote(json.dumps(metadata, separators=(",", ":"), sort_keys=True), safe="")
        return [f"{LEDGER_MARKER_V2_PREFIX}{record.fingerprint}:{record.state}:{encoded} -->"]
    # v1 fallback for records without metadata (should not happen on new writes).
    path_suffix = ""
    if record.reason and record.reason.startswith("path:"):
        path_suffix = f":{quote(record.reason.removeprefix('path:'), safe='')}"
    return [f"{LEDGER_MARKER_PREFIX}{record.fingerprint}:{record.state}{path_suffix} -->"]


def merge_ledger_into_comment(body: str, *, records: Iterable[LifecycleRecord]) -> str:
    """Strip prior ledger markers and append the supplied record set."""
    cleaned = _LEDGER_MARKER_V2_RE.sub("", _LEDGER_MARKER_RE.sub("", body)).rstrip()
    markers = [line for record in records for line in _marker_lines(record)]
    if not markers:
        return cleaned
    block = "\n".join(markers)
    if not cleaned:
        return block + "\n"
    return f"{cleaned}\n\n{block}\n"


def record_over_budget_verifications(
    book: FindingLedger,
    *,
    skipped_over_budget: Sequence[str],
    round_index: int = 1,
) -> None:
    """Record fingerprints the verifier budget skipped as ``unpublished``."""
    for fingerprint in skipped_over_budget:
        book.record(
            fingerprint,
            "unpublished",
            source="verification-budget",
            round_index=round_index,
        )


def record_deferred_from_analyzer_run(
    tool_state: ToolState,
    run_state: AnalyzerRunState,
    *,
    round_index: int | None = None,
) -> None:
    """Record analyzer overflow findings as ``deferred``."""
    resolved_round = ledger_round_index(tool_state) if round_index is None else round_index
    ledger = ensure_finding_ledger(tool_state)
    withdrawn = tool_state.withdrawn_fingerprints
    for row in run_state.deferred_findings:
        fingerprint = str(row.get("fingerprint") or "").strip()
        if fingerprint and fingerprint not in withdrawn:
            path = str(row.get("path") or "").strip()
            ledger.record(
                fingerprint,
                "deferred",
                source="overflow",
                round_index=resolved_round,
                reason=f"path:{path}" if path else None,
            )


def record_published_findings_in_ledger(
    tool_state: ToolState,
    findings: Sequence[dict[str, Any]],
    *,
    round_index: int | None = None,
) -> None:
    """Record inline/published findings as ``open`` in the cross-round ledger (RC4)."""
    from mergecraft.review_taxonomy import finding_fingerprint

    resolved_round = ledger_round_index(tool_state) if round_index is None else round_index
    ledger = ensure_finding_ledger(tool_state)
    for row in findings:
        fingerprint = str(row.get("fingerprint") or "").strip()
        if not fingerprint:
            path = str(row.get("path") or "")
            body = str(row.get("body") or row.get("message") or "")
            if path and body:
                fingerprint = finding_fingerprint(path=path, body=body)
        if fingerprint:
            ledger.record(
                fingerprint,
                "open",
                source="inline",
                round_index=resolved_round,
            )


def record_withdrawn_in_ledger(tool_state: ToolState, *, round_index: int | None = None) -> None:
    """Mirror ``ToolState.withdrawn_fingerprints`` into the ledger (X2)."""
    resolved_round = ledger_round_index(tool_state) if round_index is None else round_index
    ledger = ensure_finding_ledger(tool_state)
    for fingerprint in tool_state.withdrawn_fingerprints:
        ledger.record(
            fingerprint,
            "withdrawn",
            source="verifier-drop",
            round_index=resolved_round,
        )


def ensure_finding_ledger(tool_state: ToolState) -> FindingLedger:
    if tool_state.finding_ledger is None:
        tool_state.finding_ledger = FindingLedger()
    return tool_state.finding_ledger


async def hydrate_finding_ledger_from_progress_comment(ctx: ToolContext) -> FindingLedger:
    """Load the ledger from the sticky progress comment when one is known (D4)."""
    tool_state = ctx.tool_state
    if tool_state.finding_ledger_loaded:
        return ensure_finding_ledger(tool_state)

    from mergecraft.mcp.tool_state import ProgressComment, primary_repo_state

    ledger = FindingLedger()
    progress = tool_state.progress_comment
    issue_number = primary_repo_state(tool_state).issue_number or tool_state.pr_number
    try:
        if isinstance(progress, ProgressComment):
            comment = await ctx.scm.get_issue_comment(
                ctx.repo.owner,
                ctx.repo.name,
                int(progress.id),
            )
            ledger = FindingLedger.from_comment_body(str(comment.get("body") or ""))
        elif issue_number is not None:
            body = await fetch_sticky_progress_comment_body(
                ctx.scm,
                ctx.repo.owner,
                ctx.repo.name,
                int(issue_number),
            )
            if body:
                ledger = FindingLedger.from_comment_body(body)
    except Exception as err:
        logger.info("finding ledger: could not read progress comment: {}", err)

    existing = tool_state.finding_ledger
    if existing is not None:
        # When both in-memory and hydrated rows share a fingerprint, keep the
        # newer ``recorded_at`` stamp — progress comments can lag live session
        # updates during the same Action run.
        for record in existing.records():
            ledger.upsert_if_newer(record)

    tool_state.finding_ledger = ledger
    tool_state.finding_ledger_loaded = True
    return ledger


async def persist_finding_ledger_to_progress_comment(ctx: ToolContext) -> None:
    """Persist the in-memory ledger into the sticky progress comment (RC4, M9)."""
    from mergecraft.mcp.comment import add_footer
    from mergecraft.mcp.tool_state import ProgressComment, primary_repo_state
    from mergecraft.utils.learnings import (
        ensure_learnings_review_delta,
        merge_learnings_delta_into_review_body,
    )

    tool_state = ctx.tool_state
    if tool_state.progress_comment is False:
        return

    ledger = ensure_finding_ledger(tool_state)
    if not ledger.records():
        return

    issue_number = primary_repo_state(tool_state).issue_number or tool_state.pr_number
    if issue_number is None:
        return

    try:
        base_body = str(tool_state.last_progress_body or "").strip()
        if not base_body:
            base_body = f"{_PROGRESS_HEADING}\n\nReview published."

        await ensure_learnings_review_delta(tool_state)
        body_with_delta = merge_learnings_delta_into_review_body(tool_state, base_body)
        body_with_ledger = merge_ledger_into_comment(body_with_delta, records=ledger.records())
        body_with_footer = add_footer(ctx, body_with_ledger)

        if isinstance(tool_state.progress_comment, ProgressComment):
            await ctx.scm.update_issue_comment(
                ctx.repo.owner,
                ctx.repo.name,
                int(tool_state.progress_comment.id),
                body_with_footer,
            )
            return

        sticky = await fetch_sticky_progress_comment(
            ctx.scm,
            ctx.repo.owner,
            ctx.repo.name,
            int(issue_number),
        )
        if sticky is not None:
            existing_body = str(sticky.get("body") or "")
            if existing_body:
                merged = merge_ledger_into_comment(existing_body, records=ledger.records())
                body_with_footer = add_footer(ctx, merged)
                await ctx.scm.update_issue_comment(
                    ctx.repo.owner,
                    ctx.repo.name,
                    int(sticky["id"]),
                    body_with_footer,
                )
                tool_state.progress_comment = ProgressComment(
                    id=str(sticky["id"]),
                    type="issue",
                )
                return

        result = await ctx.scm.create_issue_comment(
            ctx.repo.owner,
            ctx.repo.name,
            int(issue_number),
            body_with_footer,
        )
        tool_state.progress_comment = ProgressComment(id=str(result["id"]), type="issue")
    except Exception as err:
        logger.info("finding ledger: could not persist progress comment: {}", err)


def _strip_deterministic_record_markers(body: str) -> str:
    """Remove forged or stale deterministic-record markers from agent prose."""
    without_block = _DETERMINISTIC_RECORD_BLOCK_RE.sub("", body)
    return without_block.replace(DETERMINISTIC_RECORD_MARKER, "").strip()


def merge_deterministic_record_into_comment(body: str, *, record_block: str) -> str:
    """Insert or replace the deterministic record block in a progress comment."""
    cleaned = _DETERMINISTIC_RECORD_BLOCK_RE.sub("", body).replace(DETERMINISTIC_RECORD_MARKER, "")
    cleaned = cleaned.strip()
    block = record_block.strip()
    if not cleaned:
        return f"{_PROGRESS_HEADING}\n\n{block}\n"
    if _PROGRESS_HEADING not in cleaned:
        cleaned = f"{_PROGRESS_HEADING}\n\n{cleaned}"
    if DETERMINISTIC_RECORD_MARKER in cleaned:
        return f"{_DETERMINISTIC_RECORD_BLOCK_RE.sub(block, cleaned, count=1).rstrip()}\n"
    parts = cleaned.split("\n", 1)
    if parts[0].strip() == _PROGRESS_HEADING:
        tail = parts[1].strip() if len(parts) > 1 else ""
        if tail:
            return f"{_PROGRESS_HEADING}\n\n{block}\n\n{tail}\n"
        return f"{_PROGRESS_HEADING}\n\n{block}\n"
    return f"{block}\n\n{cleaned}\n"


def render_deterministic_review_block(
    *,
    packet: Any,
    rejection_reason: str | None = None,
    run_url: str | None = None,
    run_outcome: Any | None = None,
    verdict_diagnostic: Any | None = None,
    analyzer_summary: str | None = None,
    agent_summary: str | None = None,
    trust_tier: str | None = None,
    attempt_count: int | None = None,
    token_summary: str | None = None,
) -> str:
    """Render the authoritative deterministic review record (D6/D7).

    Pure leaf: no I/O. Both the sticky progress comment and the review-body
    preamble render from this single function so the two surfaces cannot drift.
    """
    from mergecraft.analyzers.finding import Finding

    decision = getattr(packet, "decision", None)
    agent_meta = getattr(packet, "agent", None)
    self_assessment = getattr(packet, "self_assessment", None)
    findings_raw = list(getattr(packet, "findings", []) or [])
    findings = [
        row if isinstance(row, Finding) else Finding.model_validate(row) for row in findings_raw
    ]
    change_findings = [finding for finding in findings if finding.scope != "run"]
    run_findings = [finding for finding in findings if finding.scope == "run"]
    deterministic_checks = list(getattr(packet, "deterministic_checks", []) or [])

    model = ""
    if agent_meta is not None:
        executed = str(getattr(agent_meta, "executed_model", "") or "").strip()
        model = executed or str(getattr(agent_meta, "model", "") or "").strip()

    reviewed_sha = ""
    if self_assessment is not None and getattr(self_assessment, "sha", None):
        reviewed_sha = str(self_assessment.sha)

    header_lines = [
        DETERMINISTIC_RECORD_MARKER,
        "### mergeCraft run record",
        "",
    ]
    if run_outcome is not None:
        header_lines.append(f"- **Outcome:** `{run_outcome}`")
    if verdict_diagnostic is not None:
        diagnostic = (
            verdict_diagnostic.value
            if hasattr(verdict_diagnostic, "value")
            else str(verdict_diagnostic)
        )
        header_lines.append(f"- **Verdict diagnostic:** `{diagnostic}`")
    if decision is not None:
        header_lines.append(f"- **Decision:** `{decision.verdict}` — {decision.reason}")
    if model:
        header_lines.append(f"- **Model:** `{model}`")
    if attempt_count is not None:
        header_lines.append(f"- **Attempts:** {attempt_count}")
    if token_summary:
        header_lines.append(f"- **Tokens:** {token_summary}")
    if run_url:
        header_lines.append(f"- **Run:** {run_url}")
    if reviewed_sha:
        header_lines.append(f"- **Reviewed SHA:** `{reviewed_sha}`")

    pre_merge_lines = ["", "### Pre-merge checks", ""]
    if analyzer_summary:
        pre_merge_lines.append(f"- **Analyzers:** {analyzer_summary}")
    elif agent_meta is not None and getattr(agent_meta, "dispatched_lens_ids", None):
        lens_ids = ", ".join(agent_meta.dispatched_lens_ids)
        pre_merge_lines.append(f"- **Analyzers:** dispatched lenses: {lens_ids}")
    else:
        pre_merge_lines.append("- **Analyzers:** not recorded on packet")

    if deterministic_checks:
        check_bits = [
            f"{check.name} ({check.status})"
            for check in deterministic_checks
            if getattr(check, "name", None)
        ]
        pre_merge_lines.append(
            f"- **Static checks:** {', '.join(check_bits) if check_bits else 'none recorded'}"
        )
    else:
        pre_merge_lines.append("- **Static checks:** none recorded")

    pre_merge_lines.append("- **CI intelligence:** see packet findings")
    pre_merge_lines.append(f"- **Trust tier:** `{trust_tier or 'unknown'}`")

    finding_lines = ["", "### Change-scoped findings", ""]
    if change_findings:
        for finding in change_findings:
            location = f"`{finding.path}` — " if finding.path else ""
            finding_lines.append(f"- **{finding.severity}** · {location}{finding.message}")
    else:
        finding_lines.append("_No change-scoped findings recorded._")

    run_health_lines: list[str] = []
    if run_findings:
        run_health_lines = [
            "",
            "<details>",
            "<summary>Run health</summary>",
            "",
        ]
        for finding in run_findings:
            run_health_lines.append(f"- **{finding.severity}** · {finding.message}")
        run_health_lines.append("")
        run_health_lines.append("</details>")

    verdict_lines: list[str] = []
    if decision is not None:
        summary = (agent_summary or "").strip()
        if summary:
            verdict_lines = [
                "",
                "### Agent summary",
                "",
                f"> {summary.replace(chr(10), chr(10) + '> ')}",
            ]
    elif rejection_reason:
        verdict_lines = [
            "",
            f"**No verdict recorded — reason:** `{rejection_reason}`",
        ]

    return (
        "\n".join(
            header_lines + pre_merge_lines + finding_lines + run_health_lines + verdict_lines
        ).rstrip()
        + "\n"
    )


async def upsert_sticky_progress_comment(ctx: ToolContext, record_block: str) -> None:
    """Upsert the sticky progress comment with the deterministic record (D6)."""
    from mergecraft.mcp.comment import add_footer
    from mergecraft.mcp.tool_state import ProgressComment, primary_repo_state
    from mergecraft.utils import gha_log

    tool_state = ctx.tool_state
    if tool_state.progress_comment is False:
        return

    issue_number = primary_repo_state(tool_state).issue_number or tool_state.pr_number
    if issue_number is None:
        return

    try:
        base_body = str(tool_state.last_progress_body or "").strip()
        body_with_record = merge_deterministic_record_into_comment(
            base_body,
            record_block=record_block,
        )
        body_with_footer = add_footer(ctx, body_with_record)

        if isinstance(tool_state.progress_comment, ProgressComment):
            await ctx.scm.update_issue_comment(
                ctx.repo.owner,
                ctx.repo.name,
                int(tool_state.progress_comment.id),
                body_with_footer,
            )
            tool_state.last_progress_body = body_with_footer
            return

        sticky = await fetch_sticky_progress_comment(
            ctx.scm,
            ctx.repo.owner,
            ctx.repo.name,
            int(issue_number),
        )
        if sticky is not None:
            existing_body = str(sticky.get("body") or "")
            merged = merge_deterministic_record_into_comment(
                existing_body,
                record_block=record_block,
            )
            body_with_footer = add_footer(ctx, merged)
            await ctx.scm.update_issue_comment(
                ctx.repo.owner,
                ctx.repo.name,
                int(sticky["id"]),
                body_with_footer,
            )
            tool_state.progress_comment = ProgressComment(
                id=str(sticky["id"]),
                type="issue",
            )
            tool_state.last_progress_body = body_with_footer
            return

        result = await ctx.scm.create_issue_comment(
            ctx.repo.owner,
            ctx.repo.name,
            int(issue_number),
            body_with_footer,
        )
        tool_state.progress_comment = ProgressComment(id=str(result["id"]), type="issue")
        tool_state.last_progress_body = body_with_footer
    except Exception as err:
        message = f"deterministic record: could not persist progress comment: {err}"
        logger.info(message)
        gha_log.warning(message)


__all__ = [
    "DETERMINISTIC_RECORD_MARKER",
    "LEDGER_MARKER_PREFIX",
    "LEDGER_MARKER_V2_PREFIX",
    "LEDGER_SCHEMA_VERSION",
    "FindingLedger",
    "ensure_finding_ledger",
    "fetch_sticky_progress_comment",
    "fetch_sticky_progress_comment_body",
    "hydrate_finding_ledger_from_progress_comment",
    "is_sticky_progress_comment",
    "ledger_round_index",
    "merge_deterministic_record_into_comment",
    "merge_ledger_into_comment",
    "persist_finding_ledger_to_progress_comment",
    "record_deferred_from_analyzer_run",
    "record_over_budget_verifications",
    "record_published_findings_in_ledger",
    "record_withdrawn_in_ledger",
    "render_deterministic_review_block",
    "sticky_progress_comment_body",
    "upsert_sticky_progress_comment",
]
