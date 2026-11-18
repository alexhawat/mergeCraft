"""Cross-round finding state and the HTML markers that carry it across runs.

Module: mergecraft.findings.ledger_model
Depends: mergecraft.findings.lifecycle, mergecraft.findings.lifecycle_transitions, loguru

Exports:
    Classes:
        FindingLedger — Store lifecycle records keyed by review-taxonomy fingerprint.
    Functions:
        ensure_finding_ledger — Initialize the run's ledger on first use.
        ledger_round_index — Read the run's active one-based review round.
        merge_ledger_into_comment — Replace ledger markers within the review size budget.
        record_deferred_from_analyzer_run — Record analyzer overflow.
        record_over_budget_verifications — Record findings skipped by the verifier budget.
        record_published_findings_in_ledger — Record findings published inline.
        record_withdrawn_in_ledger — Mirror verifier withdrawals into the ledger.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote

from loguru import logger

from mergecraft.findings.lifecycle import LifecycleRecord, LifecycleState, validate_lifecycle_state
from mergecraft.findings.lifecycle_transitions import (
    assert_lifecycle_transition,
    lifecycle_transition_allowed,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from mergecraft.mcp.tool_state import AnalyzerRunState, ToolState


LEDGER_MARKER_PREFIX: str = "<!-- mergecraft-ledger:v1:"
LEDGER_MARKER_V2_PREFIX: str = "<!-- mergecraft-ledger:v2:"
LEDGER_SCHEMA_VERSION: str = "v2"

_LEDGER_MARKER_RE = re.compile(r"<!-- mergecraft-ledger:v1:([0-9a-f]+):([a-z-]+)(?::([^>]*?))? -->")
_LEDGER_MARKER_V2_RE = re.compile(r"<!-- mergecraft-ledger:v2:([0-9a-f]+):([a-z-]+):([^>]+) -->")
# Every ledger marker version starts with this; the stripper removes any left over.
_LEDGER_MARKER_FAMILY_PREFIX = "<!-- mergecraft-ledger:"
# A parsed row may carry a ``recorded_at`` this far past the reader's clock.
_RECORDED_AT_CLOCK_SKEW = timedelta(minutes=5)
# GitHub caps a review body at 65,536 characters. The ledger block gets at most
# this share of it; the deterministic record, prose and learnings delta share
# the rest. Past it the oldest rows are omitted (``merge_ledger_into_comment``).
LEDGER_BLOCK_MAX_CHARS = 30_000
_LEDGER_OMISSION_NOTE_RE = re.compile(
    r"\n*_\d+ older finding-ledger rows omitted to fit GitHub's review body limit; "
    r"earlier reviews still carry them\._\n?"
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
        prior = self._records.get(fingerprint)
        assert_lifecycle_transition(prior.state if prior is not None else None, state)
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

    def record_if_allowed(
        self,
        fingerprint: str,
        state: LifecycleState,
        *,
        source: str,
        round_index: int,
        reason: str | None = None,
    ) -> LifecycleRecord | None:
        """Record ``state`` unless the transition is illegal; then keep the prior row.

        Runtime writers use this because the ledger is hydrated from earlier
        runs: a fingerprint withdrawn in a previous round must not abort this
        round's publish or verify call when the agent raises it again.
        """
        prior = self._records.get(fingerprint)
        prior_state = prior.state if prior is not None else None
        if not lifecycle_transition_allowed(prior_state, state):
            logger.warning(
                "finding ledger: skipping illegal transition {!r} -> {!r} for {} (source={})",
                prior_state,
                state,
                fingerprint,
                source,
            )
            return None
        return self.record(
            fingerprint, state, source=source, round_index=round_index, reason=reason
        )

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
        """Insert ``record`` or replace the stored row unless the stored row is newer.

        ``recorded_at`` has one-second resolution, and callers fold rows in
        publication order (oldest review first, the live in-memory ledger last),
        so on a tie the later row is the newer state and wins.
        """
        prior = self._records.get(record.fingerprint)
        if prior is None:
            self._records[record.fingerprint] = record
            return record
        prior_at = prior.recorded_at or ""
        new_at = record.recorded_at or ""
        if new_at >= prior_at:
            self._records[record.fingerprint] = record
            return record
        return prior

    def render_ledger_block(self) -> str:
        """Serialize all records to HTML ledger markers."""
        lines = [line for record in self.records() for line in _marker_lines(record)]
        return "\n".join(lines)

    @classmethod
    def from_comment_body(cls, body: str, *, now: datetime | None = None) -> FindingLedger:
        """Parse ledger markers from a progress-comment or review body.

        A v2 row whose ``recorded_at`` does not parse, or lies more than
        ``_RECORDED_AT_CLOCK_SKEW`` after ``now`` (default: the current time),
        is skipped.
        """
        reference = now or datetime.now(UTC)
        records: dict[str, LifecycleRecord] = {}
        for match in _LEDGER_MARKER_V2_RE.finditer(body):
            fingerprint, raw_state, encoded_meta = (
                match.group(1),
                match.group(2),
                match.group(3),
            )
            record = _record_from_v2_marker(fingerprint, raw_state, encoded_meta, now=reference)
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


def _parse_recorded_at(raw: str) -> datetime | None:
    """Return ``raw`` as an aware UTC datetime, or ``None`` when it is not ISO 8601."""
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _record_from_v2_marker(
    fingerprint: str,
    raw_state: str,
    encoded_meta: str,
    *,
    now: datetime,
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
    if recorded_at:
        stamp = _parse_recorded_at(str(recorded_at))
        if stamp is None:
            logger.warning(
                "finding ledger: skipping v2 marker with invalid recorded_at for fingerprint {}",
                fingerprint,
            )
            return None
        if stamp > now + _RECORDED_AT_CLOCK_SKEW:
            logger.warning(
                "finding ledger: skipping v2 marker with future recorded_at for fingerprint {}",
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


def _strip_ledger_markers(body: str) -> str:
    """Remove every ledger marker and marker prefix from ``body``, to a fixed point.

    Removing one marker can join the text around it into another, so the
    passes repeat until nothing changes. The result contains no ledger marker
    prefix at all, so no marker parses from it and none can form with text
    appended after it.
    """
    current = body
    while True:
        stripped = _LEDGER_MARKER_V2_RE.sub("", _LEDGER_MARKER_RE.sub("", current))
        stripped = stripped.replace(_LEDGER_MARKER_FAMILY_PREFIX, "")
        if stripped == current:
            return stripped
        current = stripped


def _ledger_omission_note(omitted: int) -> str:
    return (
        f"_{omitted} older finding-ledger rows omitted to fit GitHub's review body limit; "
        "earlier reviews still carry them._"
    )


def _budget_ledger_records(
    records: Sequence[LifecycleRecord], *, max_chars: int
) -> tuple[list[LifecycleRecord], int]:
    """Keep the newest rows whose markers fit in ``max_chars``; return ``(kept, omitted)``.

    Rows are ranked by ``recorded_at`` (newest first, fingerprint as the tie
    break) and kept greedily, so the rows this round wrote always survive. The
    rows left out are older, and the ledger is folded across every earlier
    review, so a row omitted here is still read from the review that wrote it.
    Kept rows are returned in the input order.
    """
    sized = [(record, sum(len(line) + 1 for line in _marker_lines(record))) for record in records]
    if sum(size for _, size in sized) <= max_chars:
        return list(records), 0
    ranked = sorted(
        sized, key=lambda item: (item[0].recorded_at or "", item[0].fingerprint), reverse=True
    )
    keep: set[str] = set()
    used = 0
    for record, size in ranked:
        if used + size > max_chars:
            continue
        keep.add(record.fingerprint)
        used += size
    kept = [record for record in records if record.fingerprint in keep]
    return kept, len(records) - len(kept)


def merge_ledger_into_comment(
    body: str,
    *,
    records: Iterable[LifecycleRecord],
    max_chars: int = LEDGER_BLOCK_MAX_CHARS,
) -> str:
    """Strip prior ledger markers and append the supplied record set.

    The marker block is bounded by ``max_chars`` so a long-lived ledger cannot
    push the review past GitHub's body limit on its own. Past the budget the
    oldest rows are left out (see :func:`_budget_ledger_records`) and one visible
    note says how many; a previous note is replaced, never stacked.
    """
    cleaned = _LEDGER_OMISSION_NOTE_RE.sub("", _strip_ledger_markers(body)).rstrip()
    kept, omitted = _budget_ledger_records(list(records), max_chars=max_chars)
    markers = [line for record in kept for line in _marker_lines(record)]
    if not markers:
        return cleaned
    block = "\n".join(markers)
    if omitted:
        logger.warning(
            "finding ledger: {} older rows omitted from this review to stay within its "
            "{}-character ledger budget",
            omitted,
            max_chars,
        )
        block = f"{block}\n\n{_ledger_omission_note(omitted)}"
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
        book.record_if_allowed(
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
            ledger.record_if_allowed(
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
            ledger.record_if_allowed(
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
        ledger.record_if_allowed(
            fingerprint,
            "withdrawn",
            source="verifier-drop",
            round_index=resolved_round,
        )


def ensure_finding_ledger(tool_state: ToolState) -> FindingLedger:
    if tool_state.finding_ledger is None:
        tool_state.finding_ledger = FindingLedger()
    return tool_state.finding_ledger


__all__ = [
    "LEDGER_BLOCK_MAX_CHARS",
    "LEDGER_MARKER_PREFIX",
    "LEDGER_MARKER_V2_PREFIX",
    "LEDGER_SCHEMA_VERSION",
    "FindingLedger",
    "ensure_finding_ledger",
    "ledger_round_index",
    "merge_ledger_into_comment",
    "record_deferred_from_analyzer_run",
    "record_over_budget_verifications",
    "record_published_findings_in_ledger",
    "record_withdrawn_in_ledger",
]
