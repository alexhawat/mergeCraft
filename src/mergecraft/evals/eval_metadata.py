"""Packet-side eval metadata rows (#44, W12)."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergecraft.evals.ids import CASE_ID_RE
from mergecraft.evals.store import Case, CaseStatus  # noqa: TC001
from mergecraft.evals.verdict_vocab import EXPECTED_VERDICT_VALUES


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class EvalMetadata(BaseModel):
    """Lightweight packet-side summary of one replay run (#44, W12).

    The ``MergeEvidencePacket.evals`` section is a list of these — one
    per case the run promoted / replayed / attached to the verdict. The
    record is the *packet-side* summary: it carries enough to attribute
    a verdict to a case in the bank, but it does **not** carry the full
    :class:`Case` model. The full case lives under
    ``evals/cases/<case_id>.md``; the packet field is the breadcrumb.

    The shape intentionally omits ``LearningProvenance`` — provenance is
    a *case-side* record, not a packet-side one. The packet reader can
    look the case up by ``case_id`` if it needs the provenance chain.

    Attributes:
        case_id: The case this metadata row describes.
        run_id: The run that produced the verdict (mirrors the packet's
            top-level run attribution).
        title: Short, operator-readable case title.
        category: The failure category (``rejected`` / ``reverted`` /
            any operator-defined value).
        failure_mode: The recorded failure mode.
        expected_finding: The finding the packet should have produced.
        expected_decision: The verdict the case asserts the packet
            should have produced.
        replay_decision: The verdict the replay engine produced for
            this case (``passed`` / ``regression`` / ``blocked``).
        replay_at: The UTC timestamp the replay ran.
        status: The case-status equivalent (``passed`` /
            ``regression`` / ``blocked``) for ergonomic filtering — the
            packet reader does not need to compare expected and current
            verdicts to know whether the case has drifted.

    Examples:
        >>> from datetime import datetime, timezone
        >>> meta = EvalMetadata(
        ...     case_id="synthetic-001",
        ...     run_id="run-123",
        ...     title="missed a fabricated deletion",
        ...     category="missed_finding",
        ...     failure_mode="missed_finding",
        ...     expected_finding="src/mergecraft/foo.py:42",
        ...     expected_decision="block",
        ...     replay_decision="block",
        ...     replay_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ...     status="passed",
        ... )
        >>> meta.case_id
        'synthetic-001'
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    failure_mode: str = Field(min_length=1)
    expected_finding: str = Field(min_length=1)
    expected_decision: str = Field(min_length=1)
    replay_decision: CaseStatus
    replay_at: datetime
    status: CaseStatus

    @field_validator("case_id")
    @classmethod
    def _validate_case_id(cls, value: str) -> str:
        """Enforce the locked identifier shape.

        The shape mirrors the bank file-system naming convention so a
        ``case_id`` is a safe filename the reader can resolve.
        """
        if not CASE_ID_RE.match(value):
            msg = f"case id {value!r} is not a valid identifier"
            raise ValueError(msg)
        return value

    @field_validator("expected_decision")
    @classmethod
    def _validate_decision(cls, value: str) -> str:
        """Reject ``expected_decision`` values outside the verdict vocabulary.

        The vocabulary mirrors the packet's ``Decision.verdict`` field.
        ``EvalMetadata`` keeps the same vocabulary as the case store
        so the packet does not silently fall out of sync with the bank.
        """
        if value not in EXPECTED_VERDICT_VALUES:
            msg = (
                f"expected_decision {value!r} is not in the verdict vocabulary "
                f"{sorted(EXPECTED_VERDICT_VALUES)}"
            )
            raise ValueError(msg)
        return value


# ── packet-side summary (W12.2) ────────────────────────────────────────


def build_eval_metadata(
    case: Case,
    *,
    replay_decision: CaseStatus,
    run_id: str,
    replay_at: datetime | None = None,
) -> EvalMetadata:
    """Build an :class:`EvalMetadata` row from a :class:`Case` + replay outcome.

    Pure data-shaping helper. The packet emits one row per case the run
    replayed or attached to the verdict; this helper is the
    single-entry-point the I/O shell uses to populate the
    ``MergeEvidencePacket.evals`` section.

    Args:
        case: The case the replay ran against.
        replay_decision: The replay's outcome (``passed`` /
            ``regression`` / ``blocked``).
        run_id: The run id that produced the replay (mirrors the
            packet's top-level run attribution).
        replay_at: The UTC timestamp the replay ran. Defaults to "now".

    Returns:
        An :class:`EvalMetadata` row carrying the lightweight
        summary. The full case continues to live under
        ``evals/cases/<case_id>.md``; this row is the packet-side
        breadcrumb.

    Examples:
        >>> from datetime import datetime, timezone
        >>> from mergecraft.utils.learnings import LearningProvenance
        >>> prov = LearningProvenance(
        ...     run_id="run-1", pr_number=1, source_field="eval_bank",
        ...     author_login="alice", author_association="OWNER",
        ...     trust_tier="trusted",
        ...     timestamp=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ... )
        >>> case = Case(
        ...     id="synthetic-001", title="t", category="missed_finding",
        ...     submitted_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ...     run_id="run-1", pr_number=1, failure_mode="missed_finding",
        ...     expected_finding="x", expected_decision="block",
        ...     replay_command="mergecraft eval replay synthetic-001",
        ...     provenance=prov, body="",
        ... )
        >>> meta = build_eval_metadata(
        ...     case, replay_decision="passed", run_id="run-1",
        ... )
        >>> meta.status
        'passed'
    """
    ts = replay_at if replay_at is not None else _now_utc()
    return EvalMetadata(
        case_id=case.id,
        run_id=run_id,
        title=case.title,
        category=case.category,
        failure_mode=case.failure_mode,
        expected_finding=case.expected_finding,
        expected_decision=case.expected_decision,
        replay_decision=replay_decision,
        replay_at=ts,
        status=replay_decision,
    )


__all__ = ["EvalMetadata", "build_eval_metadata"]
