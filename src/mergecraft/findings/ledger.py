"""Cross-round finding ledger — open-PR memory in the sticky progress comment (RC4, D4).

Persistence is GitHub-only: HTML markers in the progress comment survive ephemeral
Action checkouts. Post-merge issue filing stays in :mod:`mergecraft.findings.sweep`.
"""

from __future__ import annotations

import re
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

LEDGER_MARKER_PREFIX: str = "<!-- mergecraft-ledger:v1:"
LEDGER_SCHEMA_VERSION: str = "v1"

_LEDGER_MARKER_RE = re.compile(r"<!-- mergecraft-ledger:v1:([0-9a-f]+):([a-z-]+)(?::([^>]*?))? -->")


def files_github_issues() -> bool:
    """Return whether the ledger files GitHub issues (D5 — always false)."""
    return False


def persist_to_progress_comment(book: FindingLedger) -> None:
    """Record-only hook: the ledger never writes issues; persistence is via the progress comment."""
    _ = book


_LEDGER_STATES: frozenset[str] = frozenset(
    {
        "open",
        "resolved-by-change",
        "stale",
        "disputed",
        "waived",
        "deferred",
        "unpublished",
        "withdrawn",
    }
)


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

    def render_ledger_block(self) -> str:
        """Serialize all records to HTML ledger markers."""
        lines = [line for record in self.records() for line in _marker_lines(record)]
        return "\n".join(lines)

    @classmethod
    def from_comment_body(cls, body: str) -> FindingLedger:
        """Parse ledger markers from a progress-comment body."""
        records: dict[str, LifecycleRecord] = {}
        for match in _LEDGER_MARKER_RE.finditer(body):
            fingerprint, raw_state, encoded_path = match.group(1), match.group(2), match.group(3)
            try:
                state = validate_lifecycle_state(raw_state)
            except ValueError:
                logger.warning(
                    "finding ledger: skipping marker with unknown state {} for fingerprint {}",
                    raw_state,
                    fingerprint,
                )
                continue
            reason = None
            if encoded_path:
                reason = f"path:{unquote(encoded_path)}"
            records[fingerprint] = LifecycleRecord(
                fingerprint=fingerprint,
                state=state,
                reason=reason,
            )
        return cls(_records=records)


def ledger_round_index(tool_state: ToolState) -> int:
    """Return the active 1-based review round for ledger ``record_*`` call sites."""
    return max(int(getattr(tool_state, "review_round_index", 1) or 1), 1)


def _marker_lines(record: LifecycleRecord) -> list[str]:
    # Marker format: <!-- mergecraft-ledger:v1:{fingerprint}:{state} -->
    # Optional 4th segment URL-encodes a cited path for deferred promotion (v1.1).
    path_suffix = ""
    if record.reason and record.reason.startswith("path:"):
        path_suffix = f":{quote(record.reason.removeprefix('path:'), safe='')}"
    return [f"{LEDGER_MARKER_PREFIX}{record.fingerprint}:{record.state}{path_suffix} -->"]


def merge_ledger_into_comment(body: str, *, records: Iterable[LifecycleRecord]) -> str:
    """Strip prior ledger markers and append the supplied record set."""
    cleaned = _LEDGER_MARKER_RE.sub("", body).rstrip()
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
    for row in run_state.deferred_findings:
        fingerprint = str(row.get("fingerprint") or "").strip()
        if fingerprint:
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

    from mergecraft.mcp.tool_state import ProgressComment

    ledger = FindingLedger()
    progress = tool_state.progress_comment
    if isinstance(progress, ProgressComment):
        try:
            comment = await ctx.scm.get_issue_comment(
                ctx.repo.owner,
                ctx.repo.name,
                int(progress.id),
            )
            ledger = FindingLedger.from_comment_body(str(comment.get("body") or ""))
        except Exception as err:
            logger.info("finding ledger: could not read progress comment: {}", err)

    tool_state.finding_ledger = ledger
    tool_state.finding_ledger_loaded = True
    return ledger


__all__ = [
    "LEDGER_MARKER_PREFIX",
    "LEDGER_SCHEMA_VERSION",
    "FindingLedger",
    "ensure_finding_ledger",
    "files_github_issues",
    "hydrate_finding_ledger_from_progress_comment",
    "ledger_round_index",
    "merge_ledger_into_comment",
    "persist_to_progress_comment",
    "record_deferred_from_analyzer_run",
    "record_over_budget_verifications",
    "record_published_findings_in_ledger",
    "record_withdrawn_in_ledger",
]
