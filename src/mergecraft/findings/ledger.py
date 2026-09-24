"""Cross-round finding ledger — open-PR memory in the sticky progress comment (RC4, D4).

Persistence is GitHub-only: HTML markers in the progress comment survive ephemeral
Action checkouts. Post-merge issue filing stays in :mod:`mergecraft.findings.sweep`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote

from loguru import logger

from mergecraft.findings.lifecycle import LifecycleRecord, LifecycleState, validate_lifecycle_state

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

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
# Agent prose: the block must end at a real terminator. Falling back to ``\Z``
# here meant a marker the agent merely quoted — plausible in a repo that reviews
# its own reviewer — swallowed every finding after it. A bare marker with no
# terminator is removed on its own by the ``replace`` in the stripper below.
_DETERMINISTIC_RECORD_BLOCK_RE = re.compile(
    rf"{re.escape(DETERMINISTIC_RECORD_MARKER)}[\s\S]*?"
    r"(?=\n<!-- mergecraft-ledger:|\n\*via mergecraft\*)",
)
# Our own progress comment, where the record legitimately ends the body.
_DETERMINISTIC_RECORD_BLOCK_EOF_RE = re.compile(
    rf"{re.escape(DETERMINISTIC_RECORD_MARKER)}[\s\S]*?"
    r"(?=\n<!-- mergecraft-ledger:|\n\*via mergecraft\*|\Z)",
)
_RECORD_SLOT = "\x00mergecraft-deterministic-record\x00"

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
    """Return whether ``body`` looks like the mergeCraft sticky progress comment.

    This is a body-only shape test: it answers "could this text be our
    comment?", not "is this comment ours?". Author trust is decided by the
    selector (:func:`_select_sticky_progress_comment`), which applies the
    interim bot-author rule before this shape check counts for anything.
    """
    lowered = body.lower()
    return (
        DETERMINISTIC_RECORD_MARKER in body
        or LEDGER_MARKER_PREFIX in body
        or LEDGER_MARKER_V2_PREFIX in body
        or _PROGRESS_HEADING in body
        or _VIA_MERGECRAFT_MARKER in lowered
    )


def _is_trusted_sticky_author(comment: Mapping[str, object]) -> bool:
    """Interim sticky trust rule: only a Bot-authored comment may be the sticky.

    A PR participant can quote the heading, the footer or a ledger marker, so a
    body shape test alone lets a human win selection — after which a later write
    fails for want of permission and the real ledger is never persisted.

    **Residual (LG-D3, closes with plan 51 HS1).** Accepting any ``user.type ==
    "Bot"`` still admits a bot that is not ours: another App installed on the
    repo, and ``github-actions[bot]`` from **any** workflow run — including one a
    same-repo collaborator adds on their own branch under ``pull_request``. The
    shared authorship helper (``review/authorship.py``, plan 40) narrows this to
    the run's expected-publisher set for App-published runs; job-token-only
    consumers keep the residual. This plan does not import that helper because
    both plans run in the same batch.
    """
    user = comment.get("user")
    if not isinstance(user, Mapping):
        return False
    return str(user.get("type") or "") == "Bot"


def _select_sticky_progress_comment(
    comments: Sequence[Mapping[str, object]],
    *,
    return_body: bool,
) -> str | dict[str, Any] | None:
    """Select the sticky progress comment; ledger markers win over heading heuristics.

    Only a trusted (bot-authored) comment is considered; an untrusted comment
    that carries a sticky shape is skipped with a warning naming its id, so a
    forged marker is visible in the run log rather than silently trusted. The
    ledger-marker preference is applied after that author filter (LG-D4).
    """
    progress_body = ""
    progress: dict[str, Any] | None = None
    for comment in comments:
        body = str(comment.get("body") or "")
        if not is_sticky_progress_comment(body):
            continue
        if not _is_trusted_sticky_author(comment):
            logger.warning(
                "finding ledger: ignoring comment {} as a sticky progress comment: "
                "author is not a bot",
                comment.get("id"),
            )
            continue
        if LEDGER_MARKER_PREFIX in body or LEDGER_MARKER_V2_PREFIX in body:
            return body if return_body else dict(comment)
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
            tool_state.last_progress_body = body_with_ledger
            return

        sticky = await fetch_sticky_progress_comment(
            ctx.scm,
            ctx.repo.owner,
            ctx.repo.name,
            int(issue_number),
        )
        if sticky is not None:
            # A selected sticky is always updated. Guarding on a non-empty body
            # meant a sticky the selector returned without content fell through
            # to ``create``, a duplicate; a blank comment is not a sticky but a
            # selected one must still be written to.
            existing_body = str(sticky.get("body") or "")
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
            tool_state.last_progress_body = merged
            return

        result = await ctx.scm.create_issue_comment(
            ctx.repo.owner,
            ctx.repo.name,
            int(issue_number),
            body_with_footer,
        )
        tool_state.progress_comment = ProgressComment(id=str(result["id"]), type="issue")
        tool_state.last_progress_body = body_with_ledger
    except Exception as err:
        logger.info("finding ledger: could not persist progress comment: {}", err)


def _strip_deterministic_record_markers(body: str) -> str:
    """Remove forged or stale deterministic-record markers from agent prose."""
    without_block = _DETERMINISTIC_RECORD_BLOCK_RE.sub("", body)
    return without_block.replace(DETERMINISTIC_RECORD_MARKER, "").strip()


def merge_deterministic_record_into_comment(body: str, *, record_block: str) -> str:
    """Insert or replace the deterministic record block in a progress comment.

    When the comment already carries a record, the new one replaces it **in
    place** so any surrounding prose keeps its position. The replacement is
    staged through a sentinel because the rendered block itself opens with
    ``DETERMINISTIC_RECORD_MARKER``; substituting it directly would leave the
    freshly-inserted block matching the same pattern as the stale ones being
    cleared.
    """
    block = record_block.strip()
    if DETERMINISTIC_RECORD_MARKER in body:
        staged = _DETERMINISTIC_RECORD_BLOCK_EOF_RE.sub(_RECORD_SLOT, body, count=1)
        staged = _DETERMINISTIC_RECORD_BLOCK_EOF_RE.sub("", staged)
        staged = staged.replace(DETERMINISTIC_RECORD_MARKER, "")
        if _PROGRESS_HEADING not in staged:
            staged = f"{_PROGRESS_HEADING}\n\n{staged.lstrip()}"
        return f"{staged.replace(_RECORD_SLOT, block).strip()}\n"
    cleaned = _DETERMINISTIC_RECORD_BLOCK_EOF_RE.sub("", body)
    cleaned = cleaned.replace(DETERMINISTIC_RECORD_MARKER, "").strip()
    if not cleaned:
        return f"{_PROGRESS_HEADING}\n\n{block}\n"
    if _PROGRESS_HEADING not in cleaned:
        cleaned = f"{_PROGRESS_HEADING}\n\n{cleaned}"
    parts = cleaned.split("\n", 1)
    if parts[0].strip() == _PROGRESS_HEADING:
        tail = parts[1].strip() if len(parts) > 1 else ""
        if tail:
            return f"{_PROGRESS_HEADING}\n\n{block}\n\n{tail}\n"
        return f"{_PROGRESS_HEADING}\n\n{block}\n"
    return f"{block}\n\n{cleaned}\n"


_INCONCLUSIVE_OUTCOME = "inconclusive"
# The two approval-shaped positive values G0 item 4 forbids when no credentialed
# reviewer ran. Only these are demoted; every other outcome / diagnostic is left
# intact so the reconciliation cannot mask a real failure (F11 / #775).
_APPROVAL_SHAPED_OUTCOME = "passed"
# The coarse step-summary table renders `success` where the record renders
# `passed`; both are the approval-shaped positive the posture must demote.
_APPROVAL_SHAPED_OUTCOME_LABELS: tuple[str, ...] = (_APPROVAL_SHAPED_OUTCOME, "success")
_APPROVAL_SHAPED_DIAGNOSTIC = "approved"
# #775 — posture lines. G0 item 4 fixes the mapping: `inconclusive` is mergeCraft's
# internal outcome (GitHub's check conclusion stays `neutral`, which it already is).
# When no credentialed reviewer ran, the record may not read as an approval.
# The note states no outcome: the reconciled `Outcome:` line is the only outcome
# claim in the record (LG-D8), so `inconclusive` is not asserted here.
_NO_CREDENTIALED_REVIEWER_NOTE = (
    "no credentialed reviewer ran; the analyzers that ran and were withheld are "
    "listed above, and this record is not an approval"
)
_TERMINAL_REQUEST_CHANGES_NOTE = (
    "the reviewer's terminal verdict was `request_changes`; this record is not an approval"
)


def _credential_gap_with_verdict_note(model: str) -> str:
    """Name the skipped roster slot(s) and the model behind a recorded verdict.

    Rendered when a roster reviewer slot was skipped for missing credentials
    **and** a typed terminal verdict was recorded: the record may not claim no
    reviewer ran, so it names the producer of the verdict instead (LG-D7). The
    note states no outcome — the reconciled ``Outcome:`` line is the only outcome
    claim (LG-D8) — and keeps the not-an-approval posture.
    """
    if model:
        producer = f"the recorded terminal verdict was produced by `{model}`"
    else:
        producer = "the recorded terminal verdict was produced by a model not recorded here"
    return (
        "the roster reviewer slot(s) above were skipped for missing credentials and "
        f"{producer}; this record is not an approval"
    )


def _record_value(value: Any) -> str:
    """Render a ``StrEnum`` / plain value as its wire string (empty when unset)."""
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def _credential_gap_present(credential_degradations: Sequence[str] | None) -> bool:
    """Return whether any roster reviewer slot was skipped for missing credentials."""
    return any(str(line).strip() for line in (credential_degradations or ()))


def _terminal_request_changes(packet: Any, decision: Any) -> bool:
    """Return whether the run's recorded terminal verdict was ``request_changes``.

    ``decide_approval`` (agents/gates.py) wraps the agent's terminal verdict in a
    ``neutral`` structural conclusion and names it in the decision reason; the
    typed ``packet.agent_terminal_verdict`` is the authoritative copy, and the
    reason is the fallback for a packet assembled without it (F12 / #775).
    """
    terminal = getattr(packet, "agent_terminal_verdict", None)
    if _record_value(terminal).strip().lower() == "request_changes":
        return True
    reason = str(getattr(decision, "reason", "") or "").lower()
    return "request_changes" in reason


def _typed_terminal_verdict(packet: Any) -> str:
    """Return the typed terminal verdict recorded on the packet (empty when unset).

    ``_terminal_request_changes`` also honours the decision reason as a fallback,
    but the reason is a derived summary. The record may only say "no credentialed
    reviewer ran" when **no** typed terminal verdict was recorded (LG-D7), so the
    renderer keys that distinction on the authoritative typed field, not the
    reason.
    """
    return _record_value(getattr(packet, "agent_terminal_verdict", None)).strip()


def record_is_not_an_approval(
    *, packet: Any, credential_degradations: Sequence[str] | None = None
) -> bool:
    """Return whether the record must demote its approval-shaped positive claims.

    The two signals are a skipped credentialed reviewer slot and a
    ``request_changes`` terminal verdict. Both surfaces — the embedded
    deterministic record and the coarse step-summary header table — must agree,
    so this single predicate is the authority for both (#775 / G-D9).
    """
    decision = getattr(packet, "decision", None)
    return _credential_gap_present(credential_degradations) or _terminal_request_changes(
        packet, decision
    )


def reconcile_outcome(*, value: Any, not_an_approval: bool, positive: str | Sequence[str]) -> str:
    """Demote an approval-shaped positive value to ``inconclusive``.

    ``positive`` is the surface's approval-shaped label(s): the deterministic
    record renders ``passed``, while the coarse step-summary table renders
    ``success``. Only those positives are demoted; a genuine negative outcome or
    diagnostic is left intact so the reconciliation never hides a real failure
    (F11 / #775).
    """
    rendered = _record_value(value)
    positives = (positive,) if isinstance(positive, str) else tuple(positive)
    if not_an_approval and rendered in positives:
        return _INCONCLUSIVE_OUTCOME
    return rendered


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
    publication_entrypoint: str | None = None,
    inline_comments_demoted: bool = False,
    comment_fallback_applied: bool = False,
    review_body_truncated: bool = False,
    credential_degradations: Sequence[str] | None = None,
    agent_sandbox_decision: Any | None = None,
    action_pin_sha: str | None = None,
    image_source_sha: str | None = None,
    review_skills: Sequence[str] | None = None,
    review_mcp_servers: Sequence[str] | None = None,
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
    run_health = getattr(packet, "run_health", None)
    if run_health is not None:
        run_findings = [
            row if isinstance(row, Finding) else Finding.model_validate(row)
            for row in list(getattr(run_health, "findings", []) or [])
        ]
    else:
        run_findings = [finding for finding in findings if finding.scope == "run"]
    deterministic_checks = list(getattr(packet, "deterministic_checks", []) or [])

    # #775 / G-D9 — reconcile the record so a positive claim (`Outcome: passed`,
    # `Verdict diagnostic: approved`) is never rendered beside a signal that the
    # review could not produce an approval. The two negative signals are a
    # skipped credentialed reviewer slot and a `request_changes` terminal
    # verdict; either maps the internal outcome to `inconclusive` (GitHub
    # `neutral`, per G0 item 4). Only the approval-shaped positive values are
    # demoted — a genuine `failed` / `infra_error` / `timed_out` outcome (or a
    # negative diagnostic such as `provider_failure`) is left intact, so the
    # reconciliation never hides a real failure.
    credential_gap = _credential_gap_present(credential_degradations)
    terminal_request_changes = _terminal_request_changes(packet, decision)
    typed_terminal_verdict = _typed_terminal_verdict(packet)
    not_an_approval = record_is_not_an_approval(
        packet=packet, credential_degradations=credential_degradations
    )
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
        outcome = reconcile_outcome(
            value=run_outcome,
            not_an_approval=not_an_approval,
            positive=_APPROVAL_SHAPED_OUTCOME,
        )
        header_lines.append(f"- **Outcome:** `{outcome}`")
    if verdict_diagnostic is not None:
        diagnostic = reconcile_outcome(
            value=verdict_diagnostic,
            not_an_approval=not_an_approval,
            positive=_APPROVAL_SHAPED_DIAGNOSTIC,
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
    pin = (action_pin_sha or "").strip()
    source = (image_source_sha or "").strip()
    if pin:
        header_lines.append(f"- **Action pin:** `{pin}`")
    if source:
        header_lines.append(f"- **Image source:** `{source}`")
    if pin and source and pin == source:
        header_lines.append(
            "- **Pin lag:** action pin equals baked image source — pinning S "
            "still deploys the digest already stored at S (#641)"
        )
    if review_skills:
        header_lines.append(
            "- **Review skills (injected):** " + ", ".join(f"`{item}`" for item in review_skills)
        )
    if review_mcp_servers:
        header_lines.append(
            "- **Review MCP:** " + ", ".join(f"`{item}`" for item in review_mcp_servers)
        )
    if publication_entrypoint:
        header_lines.append(f"- **Publication path:** `{publication_entrypoint}`")
    if inline_comments_demoted:
        header_lines.append("- **Inline recovery:** demoted inline comments into the review body")
    if comment_fallback_applied:
        header_lines.append(
            "- **Publication recovery:** normal 422 recovery was exhausted; the review "
            "landed as a last-resort bare COMMENT with no inline comments"
        )
    if review_body_truncated:
        header_lines.append(
            "- **Body truncated:** review body exceeded GitHub's 65536-character cap"
        )

    pre_merge_lines = ["", "### Pre-merge checks", ""]
    if credential_gap and typed_terminal_verdict:
        # LG-D7 — a reviewer ran and recorded a typed verdict; the record names
        # the skipped roster slot(s) (the `Credential gap` lines below name them)
        # and the model that produced the verdict, and states no outcome (LG-D8).
        # Keyed on the typed verdict, not the decision-reason fallback: only a
        # recorded typed verdict proves a reviewer ran.
        pre_merge_lines.append(
            f"- **Review integrity:** {_credential_gap_with_verdict_note(model)}"
        )
    elif credential_gap:
        pre_merge_lines.append(f"- **Review integrity:** {_NO_CREDENTIALED_REVIEWER_NOTE}")
    elif terminal_request_changes:
        pre_merge_lines.append(f"- **Review integrity:** {_TERMINAL_REQUEST_CHANGES_NOTE}")
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
    if agent_sandbox_decision is not None:
        # #619 Task 7 — the resolved sandbox decision (lane B D1/D2,
        # ``config/trust_policy.py::resolve_agent_sandbox_decision``) already
        # reaches the manifest via ``agent_sandbox_manifest_fields`` but never
        # the sticky progress comment a human actually reads. Duck-typed
        # (``getattr``) like the rest of this function's inputs — a plain
        # ``AgentSandboxDecision`` or an equivalent shim both render.
        configured_tier = getattr(agent_sandbox_decision, "configured_tier", "") or "unknown"
        head_status = getattr(agent_sandbox_decision, "head_status", "") or "unknown"
        override = "granted" if getattr(agent_sandbox_decision, "honour", False) else "refused"
        pre_merge_lines.append(
            f"- **Agent sandbox:** `{configured_tier}` tier, head `{head_status}` — "
            f"override {override}"
        )
    if credential_degradations:
        for line in credential_degradations:
            stripped = line.strip()
            if stripped:
                pre_merge_lines.append(f"- **Credential gap:** {stripped}")

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
    if rejection_reason:
        # The agent's terminal verdict was refused (scope, schema, semantic or
        # policy). This used to be an ``elif`` on ``decision is None``, which the
        # packet pipeline never produces — ``decide_approval`` always returns a
        # ``PacketDecision`` — so a refused run rendered identically to a clean
        # one. The structural decision and the refusal are separate facts.
        verdict_lines += [
            "",
            f"**No agent verdict recorded — reason:** `{rejection_reason}`",
        ]

    return (
        "\n".join(
            header_lines + pre_merge_lines + finding_lines + run_health_lines + verdict_lines
        ).rstrip()
        + "\n"
    )


async def upsert_sticky_progress_comment(ctx: ToolContext, record_block: str) -> None:
    """Upsert the sticky progress comment with the deterministic record (D6).

    The record is written over the snapshot the last writer stored, so any
    ledger record added after that snapshot is re-merged here before the footer
    is appended. The snapshot keeps the learnings delta; this merge keeps the
    records; both are pure and need no extra API call (LG-D1).
    """
    from mergecraft.mcp.comment import add_footer
    from mergecraft.mcp.tool_state import ProgressComment, primary_repo_state
    from mergecraft.utils import gha_log

    tool_state = ctx.tool_state
    if tool_state.progress_comment is False:
        return

    issue_number = primary_repo_state(tool_state).issue_number or tool_state.pr_number
    if issue_number is None:
        return

    book = tool_state.finding_ledger
    records = book.records() if book is not None else []

    try:
        base_body = str(tool_state.last_progress_body or "").strip()
        body_with_record = merge_deterministic_record_into_comment(
            base_body,
            record_block=record_block,
        )
        # Re-merge only when the run's in-memory ledger has records: an empty
        # ledger must not strip markers a prior run persisted.
        body_with_ledger = body_with_record
        if records:
            body_with_ledger = merge_ledger_into_comment(body_with_record, records=records)

        if isinstance(tool_state.progress_comment, ProgressComment):
            await ctx.scm.update_issue_comment(
                ctx.repo.owner,
                ctx.repo.name,
                int(tool_state.progress_comment.id),
                add_footer(ctx, body_with_ledger),
            )
            tool_state.last_progress_body = body_with_ledger
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
            if records:
                merged = merge_ledger_into_comment(merged, records=records)
            await ctx.scm.update_issue_comment(
                ctx.repo.owner,
                ctx.repo.name,
                int(sticky["id"]),
                add_footer(ctx, merged),
            )
            tool_state.progress_comment = ProgressComment(
                id=str(sticky["id"]),
                type="issue",
            )
            tool_state.last_progress_body = merged
            return

        result = await ctx.scm.create_issue_comment(
            ctx.repo.owner,
            ctx.repo.name,
            int(issue_number),
            add_footer(ctx, body_with_ledger),
        )
        tool_state.progress_comment = ProgressComment(id=str(result["id"]), type="issue")
        tool_state.last_progress_body = body_with_ledger
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
