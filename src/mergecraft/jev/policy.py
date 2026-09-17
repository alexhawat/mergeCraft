"""Confidence-gated ordering and the one-way ratchet (D3, D5, D6, D7).

There is no suppression path and no skip-the-reviewer path. On an
untrusted tier the ratchet may only raise suspicion or severity.

Exports:
    JevError: Structured failure (``invalid_confidence``).
    bucket_confidence: Map a calibrated float onto the three-value ordinal.
    order_units: Order by ``(triage.choice, triage.confidence, severity.score)``.
    assessment_from_response: Parse a recorded ``unit/v1`` body.
    apply_ratchet: One-way ratchet at the trust boundary.
    predict_jev_action: Shadow prediction; never skip or suppress.
    record_jev_prediction: Persist through ``evidence.shadow``.
    iter_thresholds: Pack-versioned floors with corpus row ids (D15).
    unit_battery: One residual-hunk call through the existing client.
    dispatch_residual_units: Battery + ratchet + order over residual hunks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.jev.types import (
    CERTAIN_CONFIDENCE_FLOOR,
    LIKELY_CONFIDENCE_FLOOR,
    PINNED_MODEL,
    SEVERITY_BY_SCORE,
    UNIT_PACK_ID,
    UNIT_THRESHOLD_CORPUS_IDS,
    ChoiceAnswer,
    HunkUnit,
    JevError,
    JevPrediction,
    JevThreshold,
    PolicyVerdict,
    ScoreAnswer,
    SystemOneResponse,
    UnitAssessment,
    parse_system_one_response,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

    from mergecraft.evidence.packet import MergeEvidencePacket
    from mergecraft.jev.client import AsyncJevClient

_CHOICE_RANK: dict[str, int] = {"clean": 0, "suspicious": 1, "defective": 2}
_REVIEW_ACTION: str = "require_human_review"
_ESCALATE_ACTION: str = "escalate"


def bucket_confidence(value: float | None) -> str:
    """Bucket a calibrated float onto ``certain`` / ``likely`` / ``possible`` (D3).

    Args:
        value: Confidence in ``[0, 1]``. ``None`` is rejected.

    Returns:
        str: Taxonomy ordinal.

    Raises:
        JevError: When the value is missing or outside ``[0, 1]``.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise JevError("confidence must be a number in [0, 1]", code="invalid_confidence")
    number = float(value)
    if number < 0.0 or number > 1.0:
        raise JevError("confidence must be a number in [0, 1]", code="invalid_confidence")
    certain, likely = _confidence_floors()
    if number >= certain:
        return "certain"
    if number >= likely:
        return "likely"
    return "possible"


def order_units(units: Sequence[UnitAssessment]) -> list[UnitAssessment]:
    """Order units by choice, then confidence, then severity (highest first).

    Args:
        units: Parsed unit assessments.

    Returns:
        list[UnitAssessment]: A new list; input is not mutated.
    """
    return sorted(
        units,
        key=lambda item: (
            _CHOICE_RANK.get(item.choice, -1),
            item.confidence,
            item.severity_score,
        ),
        reverse=True,
    )


def assessment_from_response(
    body: dict[str, Any] | SystemOneResponse,
    *,
    unit_id: str = "",
    pack_id: str = UNIT_PACK_ID,
    lane: str | None = None,
) -> UnitAssessment:
    """Parse a recorded or live ``unit/v1`` response into an assessment.

    Args:
        body: Response body mapping or already-parsed ``SystemOneResponse``.
        unit_id: Stable unit id to stamp on the assessment.
        pack_id: Pack version this assessment came from.
        lane: Optional blast-radius lane for the shadow row.

    Returns:
        UnitAssessment: Triage choice, gating confidence, and severity.

    Raises:
        JevError: When triage or severity answers are missing or the wrong shape.
    """
    response = body if isinstance(body, SystemOneResponse) else parse_system_one_response(body)
    triage = response.answers.get("triage")
    severity = response.answers.get("severity")
    if not isinstance(triage, ChoiceAnswer) or not isinstance(severity, ScoreAnswer):
        raise JevError("unit response is missing triage or severity", code="invalid_response")
    return UnitAssessment(
        unit_id=unit_id,
        choice=triage.choice,
        confidence=triage.confidence,
        severity_score=severity.score,
        severity=_severity_label(severity),
        pack_id=pack_id,
        lane=lane,
    )


def apply_ratchet(
    *,
    prior: PolicyVerdict | UnitAssessment | JevPrediction | None,
    incoming: PolicyVerdict | UnitAssessment | JevPrediction,
    trust_tier: str,
) -> JevPrediction:
    """Apply the one-way ratchet. Escalation is kept; de-escalation is discarded.

    Args:
        prior: Existing verdict, if any.
        incoming: Fresh Jev answers (or a steered payload).
        trust_tier: ``trusted`` or ``untrusted``.

    Returns:
        JevPrediction: Escalation-only result. Never skip, suppress, or clear.
    """
    incoming_verdict = _as_verdict(incoming)
    prior_verdict = _as_verdict(prior) if prior is not None else None
    choice = incoming_verdict.choice
    confidence = incoming_verdict.confidence
    severity = incoming_verdict.severity
    severity_score = incoming_verdict.severity_score
    discarded = False

    if prior_verdict is not None:
        if _choice_rank(incoming_verdict.choice) < _choice_rank(prior_verdict.choice):
            choice = prior_verdict.choice
            confidence = prior_verdict.confidence
            discarded = True
        if incoming_verdict.severity_score < prior_verdict.severity_score:
            severity = prior_verdict.severity
            severity_score = prior_verdict.severity_score
            discarded = True

    if trust_tier == "untrusted" and choice == "clean":
        choice = "suspicious"
        discarded = True

    return _prediction_from_verdict(
        incoming,
        choice=choice,
        confidence=confidence,
        severity=severity,
        severity_score=severity_score,
        trust_tier=trust_tier,
        discarded_deescalation=discarded,
        recorded=discarded or trust_tier == "untrusted",
    )


def predict_jev_action(
    assessment: UnitAssessment | PolicyVerdict | JevPrediction,
    *,
    trust_tier: str,
    prior: PolicyVerdict | UnitAssessment | JevPrediction | None = None,
) -> JevPrediction:
    """Predict the Jev gate action. The reviewer is never skipped (D7).

    Args:
        assessment: Incoming unit assessment or verdict.
        trust_tier: ``trusted`` or ``untrusted``.
        prior: Optional prior verdict; severity and suspicion never fall.

    Returns:
        JevPrediction: ``enforced`` is always ``False`` in this plan (D6).
    """
    _ = _jev_gate_mode()
    return apply_ratchet(prior=prior, incoming=assessment, trust_tier=trust_tier)


def record_jev_prediction(
    packet: MergeEvidencePacket,
    prediction: JevPrediction,
    *,
    output_path: Path,
    run_id: str,
    change_id: str,
) -> Any:
    """Record one Jev prediction through the existing shadow recorder (D6).

    Args:
        packet: Merge-evidence packet (source of truth; not mutated).
        prediction: ``predict_jev_action`` result.
        output_path: JSONL shadow log.
        run_id: Run identifier.
        change_id: Change identifier.

    Returns:
        ShadowRecord: The row that was appended.
    """
    from mergecraft.evidence.shadow import record_shadow_prediction

    metadata = {
        "model": PINNED_MODEL,
        "pack_id": prediction.pack_id,
        "raw_confidence": prediction.confidence,
        "unit_id": prediction.unit_id,
    }
    record = record_shadow_prediction(
        packet,
        change_id=change_id,
        run_id=run_id,
        policy_id="jev",
        output_path=output_path,
        prediction=prediction,
        metadata=metadata,
    )
    logger.info(
        "jev shadow unit_id={} pack_id={} action={} enforced=false",
        prediction.unit_id,
        prediction.pack_id,
        prediction.action,
    )
    return record


def iter_thresholds() -> Iterator[JevThreshold]:
    """Yield pack-versioned thresholds that name their J1 corpus rows (D15)."""
    yield JevThreshold(
        pack_id=UNIT_PACK_ID,
        name="certain",
        value=CERTAIN_CONFIDENCE_FLOOR,
        corpus_ids=UNIT_THRESHOLD_CORPUS_IDS,
    )
    yield JevThreshold(
        pack_id=UNIT_PACK_ID,
        name="likely",
        value=LIKELY_CONFIDENCE_FLOOR,
        corpus_ids=UNIT_THRESHOLD_CORPUS_IDS,
    )


async def unit_battery(
    unit: HunkUnit,
    *,
    client: AsyncJevClient,
    trust_tier: str = "trusted",
) -> UnitAssessment:
    """Ask the ``unit/v1`` battery about one residual hunk.

    Args:
        unit: Hunk unit to classify.
        client: Pinned Jev client (recorded transport in CI).
        trust_tier: ``trusted`` or ``untrusted``.

    Returns:
        UnitAssessment: Parsed triage, confidence, and severity.

    Raises:
        JevError: When the client skips or returns no answers.
    """
    from mergecraft.jev.questions import unit_pack

    pack = unit_pack()
    result = await client.call(
        state={"path": unit.path, "hunk": unit.content, "unit_id": unit.unit_id},
        pack_id=pack.pack_id,
        unit_id=unit.unit_id,
        trust_tier=trust_tier,
        ratchet_applied=trust_tier == "untrusted",
        questions=pack.as_system_one(),
    )
    if result.skipped or result.response is None:
        raise JevError("unit battery produced no answers", code="invalid_response")
    return assessment_from_response(
        result.response,
        unit_id=unit.unit_id,
        pack_id=pack.pack_id,
    )


async def dispatch_residual_units(
    units: Sequence[HunkUnit],
    analyzer_findings: Sequence[Any],
    *,
    client: AsyncJevClient,
    trust_tier: str,
    prior_by_unit: Mapping[str, PolicyVerdict] | None = None,
) -> list[JevPrediction]:
    """Run the unit battery only on analyzer-residual hunks, then order them.

    Args:
        units: Segmented hunks.
        analyzer_findings: Analyzer findings that already own a hunk.
        client: Pinned Jev client.
        trust_tier: ``trusted`` or ``untrusted``.
        prior_by_unit: Optional priors for the ratchet.

    Returns:
        list[JevPrediction]: Ordered residual predictions. Never suppresses.
    """
    from mergecraft.jev.segment import residual_units

    residual = residual_units(list(units), list(analyzer_findings))
    assessments: list[UnitAssessment] = []
    predictions: list[JevPrediction] = []
    for unit in residual:
        assessment = await unit_battery(unit, client=client, trust_tier=trust_tier)
        prior = None if prior_by_unit is None else prior_by_unit.get(unit.unit_id)
        prediction = predict_jev_action(assessment, trust_tier=trust_tier, prior=prior)
        assessments.append(
            UnitAssessment(
                unit_id=unit.unit_id,
                choice=prediction.choice,
                confidence=prediction.confidence,
                severity_score=prediction.severity_score,
                severity=prediction.severity,
                pack_id=prediction.pack_id,
                lane=prediction.lane,
            )
        )
        predictions.append(prediction)
    ordered = order_units(assessments)
    by_id = {item.unit_id: item for item in predictions}
    return [by_id[item.unit_id] for item in ordered]


def _confidence_floors() -> tuple[float, float]:
    certain = CERTAIN_CONFIDENCE_FLOOR
    likely = LIKELY_CONFIDENCE_FLOOR
    for threshold in iter_thresholds():
        if threshold.name == "certain":
            certain = threshold.value
        elif threshold.name == "likely":
            likely = threshold.value
    return certain, likely


def _jev_gate_mode() -> str:
    from mergecraft.config.settings import default_settings

    return default_settings().gates.jev


def _choice_rank(choice: str) -> int:
    return _CHOICE_RANK.get(choice, 0)


def _severity_label(answer: ScoreAnswer) -> str:
    key = int(answer.score) if float(answer.score).is_integer() else None
    if key is not None and key in answer.legend:
        return answer.legend[key]
    if key is not None and key in SEVERITY_BY_SCORE:
        return SEVERITY_BY_SCORE[key]
    return "Trivial"


def _as_verdict(
    value: PolicyVerdict | UnitAssessment | JevPrediction,
) -> PolicyVerdict:
    severity = getattr(value, "severity", None) or _score_to_severity(float(value.severity_score))
    return PolicyVerdict(
        choice=value.choice,
        confidence=float(value.confidence),
        severity=str(severity),
        severity_score=float(value.severity_score),
    )


def _score_to_severity(score: float) -> str:
    key = int(score) if float(score).is_integer() else 0
    return SEVERITY_BY_SCORE.get(key, "Trivial")


def _action_for(choice: str) -> str:
    if choice == "defective":
        return _ESCALATE_ACTION
    return _REVIEW_ACTION


def _prediction_from_verdict(
    incoming: PolicyVerdict | UnitAssessment | JevPrediction,
    *,
    choice: str,
    confidence: float,
    severity: str,
    severity_score: float,
    trust_tier: str,
    discarded_deescalation: bool,
    recorded: bool,
) -> JevPrediction:
    action = _action_for(choice)
    pack_id = str(getattr(incoming, "pack_id", UNIT_PACK_ID) or UNIT_PACK_ID)
    unit_id = getattr(incoming, "unit_id", None)
    lane = getattr(incoming, "lane", None)
    concluded_clean = trust_tier != "untrusted" and choice == "clean"
    return JevPrediction(
        action=action,
        skip_reviewer=False,
        suppressed=False,
        enforced=False,
        choice=choice,
        confidence=confidence,
        severity=severity,
        severity_score=severity_score,
        unit_id=str(unit_id) if unit_id else None,
        pack_id=pack_id,
        lane=str(lane) if lane else None,
        discarded_deescalation=discarded_deescalation,
        concluded_clean=concluded_clean,
        cleared=False,
        recorded=recorded,
        trust_tier=trust_tier,
        outcome=action,
        diagnostic=pack_id,
        metadata={
            "model": PINNED_MODEL,
            "pack_id": pack_id,
            "raw_confidence": confidence,
            "unit_id": unit_id,
        },
    )


__all__ = [
    "JevError",
    "apply_ratchet",
    "assessment_from_response",
    "bucket_confidence",
    "dispatch_residual_units",
    "iter_thresholds",
    "order_units",
    "predict_jev_action",
    "record_jev_prediction",
    "unit_battery",
]
