"""Cross-round finding ledger — open-PR memory in the sticky progress comment (RC4, D4).

Persistence is GitHub-only: HTML markers in the progress comment survive ephemeral
Action checkouts. Post-merge issue filing stays in :mod:`mergecraft.findings.sweep`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from loguru import logger

from mergecraft.findings.lifecycle import LifecycleRecord, LifecycleState

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import AnalyzerRunState, ToolState

LEDGER_MARKER_PREFIX: str = "<!-- mergecraft-ledger:v1:"
LEDGER_SCHEMA_VERSION: str = "v1"

_LEDGER_MARKER_RE = re.compile(r"<!-- mergecraft-ledger:v1:([0-9a-f]+):([a-z-]+) -->")


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
    ) -> LifecycleRecord:
        """Promote a deferred finding back to ``open`` with an audit trail (convention 4)."""
        prior = self._records.get(fingerprint)
        return self.record(
            fingerprint,
            "open",
            source=(prior.source if prior is not None and prior.source else "promotion"),
            round_index=(
                prior.round_index if prior is not None and prior.round_index is not None else 1
            ),
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
            fingerprint, raw_state = match.group(1), match.group(2)
            if raw_state not in _LEDGER_STATES:
                continue
            state = cast("LifecycleState", raw_state)  # validated against _LEDGER_STATES
            records[fingerprint] = LifecycleRecord(fingerprint=fingerprint, state=state)
        return cls(_records=records)


def _marker_lines(record: LifecycleRecord) -> list[str]:
    return [f"{LEDGER_MARKER_PREFIX}{record.fingerprint}:{record.state} -->"]


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
    round_index: int = 1,
) -> None:
    """Record analyzer overflow findings as ``deferred``."""
    ledger = ensure_finding_ledger(tool_state)
    for row in run_state.deferred_findings:
        fingerprint = str(row.get("fingerprint") or "").strip()
        if fingerprint:
            ledger.record(
                fingerprint,
                "deferred",
                source="overflow",
                round_index=round_index,
            )


def record_withdrawn_in_ledger(tool_state: ToolState, *, round_index: int = 1) -> None:
    """Mirror ``ToolState.withdrawn_fingerprints`` into the ledger (X2)."""
    ledger = ensure_finding_ledger(tool_state)
    for fingerprint in tool_state.withdrawn_fingerprints:
        ledger.record(
            fingerprint,
            "withdrawn",
            source="verifier-drop",
            round_index=round_index,
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
    "merge_ledger_into_comment",
    "persist_to_progress_comment",
    "record_deferred_from_analyzer_run",
    "record_over_budget_verifications",
    "record_withdrawn_in_ledger",
]
