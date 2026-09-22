"""Golden-flywheel ingest with mandatory provenance (#738, M5).

Production false positives and human dismissals are ingested into the
**existing** structural eval bank (``evals/cases``, the store
:func:`mergecraft.evals.store.add_case` writes and ``eval replay-bank``
reads). The ingest does not build a second harness, a second bank, or a
second provenance vocabulary: it writes the same ``provenance`` string
:func:`mergecraft.evals.adjudication.tier_for_provenance` already reads, and
that reader decides what the label may claim.

The policy (R-D6) is enforced at the write, not by convention:

- **Refuse without provenance.** A candidate with an empty or unrecognised
  ``provenance`` is *dropped* — no case file, no label, tier ``none``. An
  unknown string never resolves to a privileged tier.
- **Never mint ``human``.** ``human`` is written only when the candidate
  carries an independent :class:`~mergecraft.evals.adjudication.AdjudicationRecord`
  from the existing :func:`~mergecraft.evals.adjudication.adjudicate_label`
  writer; a bare ``human`` string, or one backed by a model-tier record, is
  refused. An ``agent-seeded`` candidate is never silently upgraded.
- **Structural only, never calibration** (R-D7). Ingested cases join
  ``run_structural_replay`` as structural replay cases and carry no detection
  or calibration block; one ingested ``agent-seeded`` row makes a corpus-wide
  calibration claim ineligible.
- **Fail closed per candidate.** One bad row is dropped and the batch
  continues.

Module: mergecraft.evals.flywheel
Depends: datetime, pathlib, typing, loguru, pydantic, mergecraft.evals.*

Exports:
    FlywheelCandidate: One production signal proposed for ingest.
    IngestOutcome: The accepted ``Case`` path plus the persisted provenance.
    FlywheelIngestReport: The batch outcome of one ingest run.
    ingest_flywheel: Ingest a batch into the structural bank, fail-closed.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — Pydantic field type on IngestOutcome
from typing import TYPE_CHECKING, Any, Final, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergecraft.evals.adjudication import (
    AdjudicationRecord,
    IndependenceTier,
    provenance_for,
    tier_for_provenance,
)
from mergecraft.evals.ids import CASE_ID_RE
from mergecraft.evals.store import DEFAULT_BANK_DIR, Case, add_case
from mergecraft.utils.learnings import LearningProvenance

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.tracing import NullTracer, Tracer

#: The one legacy corpus string the reader maps but cannot distinguish from an
#: unknown string — both resolve to tier ``none``. It is the only provenance the
#: ingest writes without an adjudication record, and it never upgrades a label.
AGENT_SEEDED_PROVENANCE: Final[str] = "agent-seeded"

#: Logfire span kinds: one point span per candidate, one summary per run.
INGEST_SPAN_KIND: Final[str] = "mergecraft.eval.ingest"
INGEST_SUMMARY_SPAN_KIND: Final[str] = "mergecraft.eval.ingest.summary"

#: The named, single-line refusal reason for a candidate whose ``case_id`` is
#: not a safe filename token. It is a stable string (not a pydantic dump) so a
#: caller can branch on it; the id that failed is logged separately.
INVALID_CASE_ID_REASON: Final[str] = "case_id is not a valid identifier"

TrustTier = Literal["trusted", "untrusted"]


class FlywheelCandidate(BaseModel):
    """One production signal proposed for ingest into the structural bank.

    ``provenance`` is the explicit label the candidate claims (``human``,
    ``jev-adjudicated``, ``llm-adjudicated`` or ``agent-seeded``); it defaults
    to the empty string so an unprovenanced candidate can be *refused* rather
    than defaulted into a tier. ``adjudication`` carries the writer's record
    for the adjudicated strings — it is what makes a ``human`` claim real.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    failure_mode: str = Field(min_length=1)
    expected_finding: str = Field(min_length=1)
    expected_decision: str = Field(min_length=1)
    provenance: str = ""
    adjudication: AdjudicationRecord | None = None
    recorded_findings: list[dict[str, Any]] | None = None
    run_succeeded: bool = True
    trust_tier: str = "trusted"
    body: str = ""
    pr_number: int | None = None
    run_id: str = Field(min_length=1)
    author_login: str = Field(min_length=1)
    author_association: str | None = None

    @field_validator("case_id")
    @classmethod
    def _validate_case_id(cls, value: str) -> str:
        """Reject a case id that is not a safe filename token.

        The id becomes the case file stem in the bank, so a value carrying
        path separators or traversal segments would escape ``bank_dir``. This
        is the construction-time guard; :func:`_classify` re-checks it so a
        post-construction mutation cannot reach the writer either.
        """
        if not CASE_ID_RE.match(value):
            msg = f"case_id {value!r} is not a valid identifier"
            raise ValueError(msg)
        return value


class IngestOutcome(BaseModel):
    """The result of considering one candidate for ingest.

    ``path`` is the written case file when ``ingested`` is true and ``None`` on
    a drop: a refused candidate leaves no file and no label behind.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str
    ingested: bool
    reason: str = ""
    provenance: str = ""
    tier: IndependenceTier = "none"
    path: Path | None = None


class FlywheelIngestReport(BaseModel):
    """The batch outcome of one ingest run.

    ``ingested`` / ``rejected`` are derived from ``outcomes`` so a caller can
    read the partitions or the counts without re-filtering or risking the two
    disagreeing.
    """

    model_config = ConfigDict(extra="forbid")

    outcomes: list[IngestOutcome] = Field(default_factory=list)

    @property
    def ingested(self) -> list[IngestOutcome]:
        """The outcomes that were written into the bank."""
        return [outcome for outcome in self.outcomes if outcome.ingested]

    @property
    def rejected(self) -> list[IngestOutcome]:
        """The outcomes that were dropped, leaving no case file."""
        return [outcome for outcome in self.outcomes if not outcome.ingested]

    @property
    def ingested_count(self) -> int:
        """How many candidates were written."""
        return len(self.ingested)

    @property
    def rejected_count(self) -> int:
        """How many candidates were dropped."""
        return len(self.rejected)


def _classify(candidate: FlywheelCandidate) -> tuple[bool, str, str, IndependenceTier]:
    """Decide whether one candidate may be written, and at what tier.

    Returns ``(accepted, reason, stored_provenance, tier)``. A refusal always
    carries tier ``none`` and a reason that names what was missing — never a
    minted label.
    """
    if not CASE_ID_RE.match(candidate.case_id):
        # Structural precondition, checked before any ``Case`` is built: the
        # id becomes the case file stem, so a traversal-shaped id must be
        # refused here — with a named reason, not the pydantic dump that
        # ``Case`` construction would otherwise raise. This also catches a
        # post-construction mutation that bypassed the field validator.
        return False, INVALID_CASE_ID_REASON, "", "none"
    declared = candidate.provenance.strip()
    if not declared:
        return (
            False,
            "candidate carries no provenance — refusing to ingest a label (R-D6)",
            "",
            "none",
        )
    if declared == AGENT_SEEDED_PROVENANCE:
        # Structural seed: written as-is at tier ``none``. The declared string
        # is what is persisted, so an attached record cannot upgrade it.
        return True, "", AGENT_SEEDED_PROVENANCE, "none"
    tier = tier_for_provenance(declared)
    if tier == "none":
        return (
            False,
            f"provenance {declared!r} is not a recognised label — dropped, never minted (R-D6)",
            declared,
            "none",
        )
    record = candidate.adjudication
    if record is None:
        return (
            False,
            f"provenance {declared!r} requires an adjudication record — dropping (R-D6)",
            declared,
            "none",
        )
    if provenance_for(record) != declared:
        return (
            False,
            f"provenance {declared!r} is not backed by a matching adjudication record — "
            "dropping (R-D6)",
            declared,
            "none",
        )
    if record.independence != tier:
        return (
            False,
            f"provenance {declared!r} is not backed by a record at the {tier!r} tier — "
            "dropping (R-D6)",
            declared,
            "none",
        )
    return True, "", declared, tier


def _trust_tier(candidate: FlywheelCandidate) -> TrustTier:
    """Narrow the candidate's trust tier, failing closed on an unknown value."""
    raw = candidate.trust_tier
    if raw not in {"trusted", "untrusted"}:
        msg = f"trust tier {raw!r} is not 'trusted' or 'untrusted'"
        raise ValueError(msg)
    return "untrusted" if raw == "untrusted" else "trusted"


def _build_case(candidate: FlywheelCandidate, stored_provenance: str) -> Case:
    """Build the durable ``Case`` for an accepted candidate.

    The persisted ``label_provenance`` is the string the ingest resolved, so
    ``tier_for_provenance`` — not the ingest — decides what the label means.
    """
    now = datetime.now(UTC)
    trust_tier = _trust_tier(candidate)
    provenance = LearningProvenance(
        run_id=candidate.run_id,
        pr_number=candidate.pr_number,
        source_field="flywheel_ingest",
        author_login=candidate.author_login,
        author_association=candidate.author_association,
        trust_tier=trust_tier,
        timestamp=now,
    )
    return Case(
        id=candidate.case_id,
        title=candidate.title,
        category=candidate.category,
        submitted_at=now,
        run_id=candidate.run_id,
        pr_number=candidate.pr_number,
        failure_mode=candidate.failure_mode,
        expected_finding=candidate.expected_finding,
        expected_decision=candidate.expected_decision,
        replay_command=f"mergecraft eval replay {candidate.case_id}",
        provenance=provenance,
        body=candidate.body,
        recorded_findings=candidate.recorded_findings,
        run_succeeded=candidate.run_succeeded,
        trust_tier=candidate.trust_tier,
        label_provenance=stored_provenance,
    )


def _ingest_one(candidate: FlywheelCandidate, bank_dir: Path) -> IngestOutcome:
    """Accept or drop one candidate. Any failure drops that candidate only."""
    accepted, reason, stored_provenance, tier = _classify(candidate)
    if not accepted:
        logger.debug("flywheel ingest refused {}: {}", candidate.case_id, reason)
        return IngestOutcome(
            case_id=candidate.case_id,
            ingested=False,
            reason=reason,
            provenance=stored_provenance,
            tier=tier,
            path=None,
        )
    try:
        case = _build_case(candidate, stored_provenance)
        path = add_case(bank_dir, case)
    except Exception as exc:  # fail closed per candidate, never abort the batch
        logger.warning("flywheel ingest failed for {}: {}", candidate.case_id, exc)
        return IngestOutcome(
            case_id=candidate.case_id,
            ingested=False,
            reason=f"ingest failed: {exc}",
            provenance=stored_provenance,
            tier="none",
            path=None,
        )
    logger.info("» flywheel case {} ingested at tier {}", candidate.case_id, tier)
    return IngestOutcome(
        case_id=candidate.case_id,
        ingested=True,
        reason="",
        provenance=stored_provenance,
        tier=tier,
        path=path,
    )


def _emit_ingest_span(tracer: Tracer | NullTracer | None, outcome: IngestOutcome) -> None:
    """Emit one ``mergecraft.eval.ingest`` point span. Never throws."""
    if tracer is None:
        return
    try:
        with tracer.start_span(INGEST_SPAN_KIND) as span:
            span.set_attribute("mergecraft.eval.ingest.case_id", outcome.case_id)
            span.set_attribute("mergecraft.eval.ingest.provenance", outcome.provenance)
            span.set_attribute("mergecraft.eval.ingest.tier", outcome.tier)
            span.set_attribute("mergecraft.eval.ingest.ingested", outcome.ingested)
    except Exception as exc:  # tracing must never fail an ingest
        logger.warning("flywheel ingest span failed: {}", exc)


def _emit_summary_span(tracer: Tracer | NullTracer | None, report: FlywheelIngestReport) -> None:
    """Emit one ``mergecraft.eval.ingest.summary`` span. Never throws."""
    if tracer is None:
        return
    try:
        with tracer.start_span(INGEST_SUMMARY_SPAN_KIND) as span:
            span.set_attribute("mergecraft.eval.ingest.count", report.ingested_count)
            span.set_attribute("mergecraft.eval.ingest.rejected", report.rejected_count)
    except Exception as exc:  # tracing must never fail an ingest
        logger.warning("flywheel ingest summary span failed: {}", exc)


def _case_id_for_fingerprint(fingerprint: str) -> str:
    """Stable bank id for a dismissal fingerprint.

    Fingerprints carry path separators, which are not legal case ids. The
    digest keeps the id stable without putting the path into the filename.
    """
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:20]
    return f"fp-{digest}"


def candidates_from_dismissal_signals(
    records: list[dict[str, str]],
    *,
    run_id: str,
    author_login: str,
    author_association: str | None = None,
) -> list[FlywheelCandidate]:
    """Turn recorded dismissal signals into flywheel candidates.

    ``records`` is the shape :func:`mergecraft.findings.materiality.dismissal_eval_records`
    writes. A row without a fingerprint or a known reason code is refused
    rather than stored as an unprovenanced label.
    """
    from mergecraft.findings.materiality import DISMISSAL_REASON_CODES

    candidates: list[FlywheelCandidate] = []
    for record in records:
        fingerprint = str(record.get("fingerprint", "")).strip()
        reason_code = str(record.get("reason_code", "")).strip()
        if not fingerprint or reason_code not in DISMISSAL_REASON_CODES:
            msg = "dismissal signal needs a fingerprint and a known reason_code"
            raise ValueError(msg)
        candidates.append(
            FlywheelCandidate(
                case_id=_case_id_for_fingerprint(fingerprint),
                title=f"Dismissed finding ({reason_code})",
                category=reason_code,
                failure_mode=reason_code,
                expected_finding=fingerprint,
                expected_decision="neutral",
                provenance=AGENT_SEEDED_PROVENANCE,
                body=f"Recorded dismissal {reason_code} for {fingerprint}.",
                run_id=run_id,
                author_login=author_login,
                author_association=author_association,
            )
        )
    return candidates


def ingest_flywheel(
    candidates: Sequence[FlywheelCandidate],
    *,
    bank_dir: Path = DEFAULT_BANK_DIR,
    tracer: Tracer | NullTracer | None = None,
) -> FlywheelIngestReport:
    """Ingest a batch of flywheel candidates into the structural bank.

    Each candidate is accepted or dropped independently — one bad row never
    aborts the batch. ``bank_dir`` defaults to :data:`DEFAULT_BANK_DIR`, the
    bank ``eval replay-bank`` already reads, so no new CI check is needed
    (R-D10).

    Args:
        candidates: The proposed cases, each carrying its own ``provenance``.
        bank_dir: The structural bank to write into.
        tracer: Optional tracer; one ``mergecraft.eval.ingest`` span is emitted
            per candidate and one ``mergecraft.eval.ingest.summary`` per run.

    Returns:
        FlywheelIngestReport: The accepted and dropped outcomes, with counts.

    Examples:
        >>> from pathlib import Path
        >>> candidate = FlywheelCandidate(
        ...     case_id="synthetic-flywheel-001",
        ...     title="Production false positive",
        ...     category="false_positive",
        ...     failure_mode="false_positive",
        ...     expected_finding="src/mergecraft/foo.py:42",
        ...     expected_decision="neutral",
        ...     provenance="agent-seeded",
        ...     run_id="flywheel-1",
        ...     author_login="alexhawat",
        ...     author_association="OWNER",
        ... )
        >>> report = ingest_flywheel([candidate], bank_dir=Path("/tmp/bank"))
        >>> report.ingested_count
        1
    """
    outcomes = [_ingest_one(candidate, bank_dir) for candidate in candidates]
    for outcome in outcomes:
        _emit_ingest_span(tracer, outcome)
    report = FlywheelIngestReport(outcomes=outcomes)
    _emit_summary_span(tracer, report)
    return report


__all__ = [
    "AGENT_SEEDED_PROVENANCE",
    "INGEST_SPAN_KIND",
    "INGEST_SUMMARY_SPAN_KIND",
    "FlywheelCandidate",
    "FlywheelIngestReport",
    "IngestOutcome",
    "candidates_from_dismissal_signals",
    "ingest_flywheel",
]
