"""Terminal review publication state — single vocabulary for receipt vs flags (#SM1).

Replaces contradictory combinations of ``terminal_publication_failed``,
``terminal_publication_mismatch``, ``publication_incomplete``, sticky-only,
and related receipt fields with one closed ``TerminalPublicationState`` whose
mapping to outcome classifier inputs is total.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from mergecraft.run_outcome import RunOutcome

if TYPE_CHECKING:
    from mergecraft.agents.shared import AgentResult
    from mergecraft.mcp.tool_state import ToolState

_REVIEW_MODE_NAMES = frozenset({"Review", "IncrementalReview"})


class TerminalPublicationState(StrEnum):
    """Where a review-mode run stands relative to GitHub publication."""

    not_applicable = "not_applicable"
    sticky_progress_only = "sticky_progress_only"
    submission_missing = "submission_missing"
    publish_failed = "publish_failed"
    verdict_mismatch = "verdict_mismatch"
    no_receipt = "no_receipt"
    unproven_receipt = "unproven_receipt"
    published_incomplete = "published_incomplete"
    published_ok = "published_ok"


@dataclass(frozen=True, slots=True)
class TerminalPublicationResolution:
    """Classifier inputs derived from :class:`TerminalPublicationState`."""

    state: TerminalPublicationState
    terminal_publication_failed: bool
    terminal_publication_receipt: bool | None
    terminal_publication_mismatch: tuple[str, str] | None
    terminal_publication_unproven: bool
    publication_incomplete_fingerprints: tuple[str, ...]


def _is_review_mode(mode: str | None) -> bool:
    if not mode:
        return False
    return mode in _REVIEW_MODE_NAMES


def resolve_terminal_publication(
    tool_state: ToolState,
    *,
    result: AgentResult,
    verdict_protocol: Literal["shadow", "enforce"] | None,
    mode: str | object | None,
) -> TerminalPublicationResolution:
    """Derive the canonical publication state for this run (fail-closed)."""
    mode_name = ""
    if mode is not None:
        mode_name = mode if isinstance(mode, str) else getattr(mode, "name", str(mode))

    sticky = bool(getattr(tool_state, "review_publication_sticky_only", False))
    if sticky:
        return TerminalPublicationResolution(
            state=TerminalPublicationState.sticky_progress_only,
            terminal_publication_failed=False,
            terminal_publication_receipt=None,
            terminal_publication_mismatch=None,
            terminal_publication_unproven=False,
            publication_incomplete_fingerprints=(),
        )

    if (
        not _is_review_mode(mode_name)
        or verdict_protocol == "shadow"
        or not result.terminal_submission_received
    ):
        return TerminalPublicationResolution(
            state=TerminalPublicationState.not_applicable,
            terminal_publication_failed=False,
            terminal_publication_receipt=None,
            terminal_publication_mismatch=None,
            terminal_publication_unproven=False,
            publication_incomplete_fingerprints=(),
        )

    if tool_state.terminal_publication_failed:
        return TerminalPublicationResolution(
            state=TerminalPublicationState.publish_failed,
            terminal_publication_failed=True,
            terminal_publication_receipt=False,
            terminal_publication_mismatch=None,
            terminal_publication_unproven=False,
            publication_incomplete_fingerprints=(),
        )

    review = tool_state.review
    mismatch: tuple[str, str] | None = None
    if tool_state.terminal_publication_mismatch:
        submission = tool_state.terminal_submission
        published = review.verdict if review is not None else None
        recorded = submission.verdict if submission is not None else None
        mismatch = (published or "an unknown verdict", recorded or "an unknown verdict")
        return TerminalPublicationResolution(
            state=TerminalPublicationState.verdict_mismatch,
            terminal_publication_failed=False,
            terminal_publication_receipt=True,
            terminal_publication_mismatch=mismatch,
            terminal_publication_unproven=False,
            publication_incomplete_fingerprints=(),
        )

    receipt_verdict = review is not None and review.verdict is not None
    unproven = review is not None and review.verdict is None and review.reviewed_sha is not None
    incomplete = tuple(sorted(tool_state.publication_incomplete))

    if not receipt_verdict:
        state = (
            TerminalPublicationState.unproven_receipt
            if unproven
            else TerminalPublicationState.no_receipt
        )
        return TerminalPublicationResolution(
            state=state,
            terminal_publication_failed=False,
            terminal_publication_receipt=False,
            terminal_publication_mismatch=None,
            terminal_publication_unproven=unproven,
            publication_incomplete_fingerprints=incomplete,
        )

    if incomplete:
        return TerminalPublicationResolution(
            state=TerminalPublicationState.published_incomplete,
            terminal_publication_failed=False,
            terminal_publication_receipt=True,
            terminal_publication_mismatch=None,
            terminal_publication_unproven=False,
            publication_incomplete_fingerprints=incomplete,
        )

    return TerminalPublicationResolution(
        state=TerminalPublicationState.published_ok,
        terminal_publication_failed=False,
        terminal_publication_receipt=True,
        terminal_publication_mismatch=None,
        terminal_publication_unproven=False,
        publication_incomplete_fingerprints=(),
    )


def apply_terminal_publication_flags(
    tool_state: ToolState,
    state: TerminalPublicationState,
    *,
    mismatch: tuple[str, str] | None = None,
    publication_incomplete: tuple[str, ...] = (),
) -> None:
    """Set legacy flags from a canonical publication state (mutually exclusive)."""
    tool_state.terminal_publication_state = state.value
    tool_state.review_publication_sticky_only = (
        state is TerminalPublicationState.sticky_progress_only
    )
    tool_state.terminal_publication_failed = state is TerminalPublicationState.publish_failed
    tool_state.terminal_publication_mismatch = state is TerminalPublicationState.verdict_mismatch
    tool_state.publication_incomplete = list(publication_incomplete)
    if state is TerminalPublicationState.verdict_mismatch and mismatch is not None:
        _ = mismatch  # mismatch detail lives on ReviewRecord; flag only signals presence


# Total map: publication state -> run outcome contribution when enforce applies.
# ``submission_missing`` is handled separately via ``terminal_submission_received``.
PUBLICATION_STATE_TABLE: dict[TerminalPublicationState, RunOutcome | None] = {}


def _init_publication_table() -> None:
    global PUBLICATION_STATE_TABLE
    PUBLICATION_STATE_TABLE = {
        TerminalPublicationState.not_applicable: None,
        TerminalPublicationState.sticky_progress_only: None,
        TerminalPublicationState.submission_missing: RunOutcome.inconclusive,
        TerminalPublicationState.publish_failed: RunOutcome.inconclusive,
        TerminalPublicationState.verdict_mismatch: RunOutcome.inconclusive,
        TerminalPublicationState.no_receipt: RunOutcome.inconclusive,
        TerminalPublicationState.unproven_receipt: RunOutcome.inconclusive,
        TerminalPublicationState.published_incomplete: None,
        TerminalPublicationState.published_ok: None,
    }


_init_publication_table()


__all__ = [
    "PUBLICATION_STATE_TABLE",
    "TerminalPublicationResolution",
    "TerminalPublicationState",
    "apply_terminal_publication_flags",
    "resolve_terminal_publication",
]
