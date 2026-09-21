"""Shadow mode for gate calibration (#50, W10).

The thermostat's record-and-predict machinery sits here. The
``decide_action`` function in :mod:`mergecraft.agents.gates` is the gate
itself; this module is what ``shadow`` mode does with that decision.

The contract:

* **Predict** — :func:`predict_action` is a pure read of the packet
  via the policy. Same input, same output, no side effects. The
  shadow record is the same value with provenance attached.
* **Record** — :func:`record_shadow_prediction` writes one row per
  run to a JSON-Lines file. The file is the audit trail of what the
  gate *would have done*.
* **Enforce** — :func:`enforce_action` is ``predict_action`` with a
  guarantee that the run actually applies the action. The decision
  reaches the packet without re-deriving evidence.
* **Disagree** — :func:`disagree_with_outcome` is the structural
  comparison of the predicted action against the human final outcome.
  The disagreement report groups by lane and rule.

Two design properties are load-bearing:

**No parallel evidence path.** This module consumes the packet — it
never re-builds a finding list, never re-runs the trajectory auditor,
never re-classifies blast radius. The packet is the source of truth.

**No second gate path.** ``enforce_action`` records the gate's
*decision*; it does not run a second gate. The run_packet I/O shell
is the only place that applies the action as a gate.

Exports:
    ShadowTarget: A pinned shadow target identity (label, model, prompt version).
    ShadowRecord: One recorded shadow prediction.
    predict_action: Pure read of the gate against a packet.
    record_shadow_prediction: Persist a row to disk.
    enforce_action: Apply the gate's decision as a final action.
    disagree_with_outcome: Compare a prediction against an outcome.
    load_shadow_records: Read a JSON-Lines shadow log.
    disagreement_report: Group a set of records by lane and rule.

A second target is a second :class:`ShadowTarget` value recorded through the
*same* recorder — never a second JSONL writer. The recorder stamps the target
identity onto the row and emits one ``mergecraft.shadow.prediction`` span when
a tracer is supplied; the JSONL row remains the audit trail.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from mergecraft.agents.gates import decide_action, select_rule_id
from mergecraft.evidence.gate_policy import GATE_ACTIONS, GateAction, GateActionPolicy
from mergecraft.run_outcome import RunOutcome

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.agents.shared import AgentResult
    from mergecraft.evidence.packet import MergeEvidencePacket
    from mergecraft.tracing.tracer import NullTracer, Tracer


# Closed action vocabulary: the predicted action must be one of the
# seven names. Anything outside is rejected here, not by the consumer.
_VALID_ACTIONS: Final[frozenset[str]] = frozenset(GATE_ACTIONS)

# Run-outcome strings compared by the verdict-protocol shadow path. Each maps
# to its own direction so ``passed`` vs ``inconclusive`` disagreements stay
# visible — folding both onto a generic "review" direction would hide them.
_PROTOCOL_OUTCOMES: Final[frozenset[str]] = frozenset(str(value) for value in RunOutcome)

_REVIEW_MODE_NAMES: Final[frozenset[str]] = frozenset({"Review", "IncrementalReview"})
_INCREMENTAL_REVIEW_NAMES: Final[frozenset[str]] = frozenset({"IncrementalReview"})


# Map a packet's blast radius lane to a coarse repo area for the
# disagreement report. The grouping is the smallest unit that still
# distinguishes a real signal from a noise floor — finer than a single
# repo, broader than a single file.
_LANE_TO_AREA: Final[dict[str, str]] = {
    "low": "low-risk",
    "medium": "medium-risk",
    "high": "high-risk",
}


class ShadowTarget(BaseModel):
    """A pinned shadow target identity (#737, M4).

    A second shadow target is a second *value* of this model — a different
    pinned model id and/or prompt version — recorded through the existing
    recorder. It is deliberately not a settings block and not a second
    recorder: the target only labels which prediction produced a row so the
    disagreement table can group by target as well as by lane and rule.

    ``target_id`` is the table label (``"live"`` / ``"shadow-b"``); ``model``
    is the pinned model id the prediction was produced with; ``prompt_version``
    is optional so a target may differ by model alone.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str | None = None


class ShadowRecord(BaseModel):
    """One recorded shadow prediction.

    The record is the audit trail of what the gate would have done. It
    is intentionally narrow: it carries the predicted action, the rule
    key that produced it, the blast radius lane, the packet's ``change_id``
    and ``run_id`` for attribution, and the timestamp. The full packet
    lives on disk in the run's evidence directory; the shadow record is
    the breadcrumb.

    The three ``target_*`` fields are additive (#737): a legacy row with no
    target identity still validates, and ``target_id`` is ``None`` for it.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    change_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    lane: str | None = None
    auto_merge_lane: str | None = None
    repo_area: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actual_outcome: str | None = None
    disagreement: bool | None = None
    outcome: str | None = None
    predicted_outcome: str | None = None
    diagnostic: str | None = None
    verdict_diagnostic: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    target_id: str | None = None
    target_model: str | None = None
    target_prompt_version: str | None = None


@dataclass(frozen=True, slots=True)
class VerdictProtocolPrediction:
    """Pure verdict-protocol shadow prediction (VP3)."""

    outcome: RunOutcome
    diagnostic: str

    @property
    def predicted_outcome(self) -> RunOutcome:
        return self.outcome


def _validate_action(action: str) -> None:
    """Reject a non-vocabulary action before it is recorded.

    ``decide_action`` already validates the policy at the gate; this
    guard catches direct callers of the I/O shell that bypass the gate.
    A mis-spelled action recorded here would corrupt the disagreement
    report, so the cost of the check is worth the safety.
    """
    if action not in _VALID_ACTIONS:
        msg = f"action {action!r} is outside the closed action vocabulary {sorted(_VALID_ACTIONS)}"
        raise ValueError(msg)


def _lane_to_repo_area(packet: MergeEvidencePacket) -> str | None:
    """Coarse-grained repo area for the disagreement report."""
    if packet.blast_radius is None:
        return None
    lane = packet.blast_radius.lane
    return _LANE_TO_AREA.get(lane, lane)


def _prediction_attr(prediction: Any, *names: str) -> str | None:
    if isinstance(prediction, dict):
        for name in names:
            raw = prediction.get(name)
            if raw is not None and raw != "":
                return str(raw)
        return None
    for name in names:
        if not hasattr(prediction, name):
            continue
        raw = getattr(prediction, name)
        if raw is not None and raw != "":
            return str(raw)
    return None


def _prediction_outcome_value(prediction: Any) -> str:
    value = _prediction_attr(prediction, "outcome", "predicted_outcome", "action")
    if value is not None:
        return value
    msg = f"unsupported verdict-protocol prediction shape: {type(prediction).__name__}"
    raise TypeError(msg)


def _prediction_diagnostic_value(prediction: Any) -> str:
    value = _prediction_attr(prediction, "diagnostic", "pack_id")
    if value is not None:
        return value
    msg = f"unsupported verdict-protocol prediction shape: {type(prediction).__name__}"
    raise TypeError(msg)


def predict_verdict_protocol(
    result: AgentResult,
    *,
    mode: str,
    setup_reason: str = "",
    setup_policy: str = "warn",
    prep_reason: str | None = None,
    final_summary_written: bool = False,
    terminal_publication_failed: bool = False,
) -> VerdictProtocolPrediction:
    """Read the terminal-verdict protocol prediction without recording it (VP3).

    Mirrors the enforce path of ``_classify_outcome`` so a later flip is
    comparable: IncrementalReview + ``final_summary_written`` is complete,
    setup/prep failures map to the same outcomes the resolver would produce
    with ``verdict_protocol="enforce"``, and a recorded-but-unpublished
    terminal submission (#619 Task 3b) predicts the same ``inconclusive``
    outcome the enforce path now returns, so the ``mergecraft.publish``
    span's diagnostic never disagrees with the actual outcome.
    """
    from mergecraft.mcp.verdict import VerdictDiagnostic

    if not result.success:
        return VerdictProtocolPrediction(
            outcome=RunOutcome.failed,
            diagnostic=VerdictDiagnostic.provider_failure.value,
        )
    if setup_reason and setup_policy == "fail":
        return VerdictProtocolPrediction(
            outcome=RunOutcome.configuration_error,
            diagnostic=VerdictDiagnostic.policy_rejection.value,
        )
    if setup_reason and setup_policy == "inconclusive":
        return VerdictProtocolPrediction(
            outcome=RunOutcome.inconclusive,
            diagnostic=VerdictDiagnostic.policy_rejection.value,
        )
    if prep_reason:
        return VerdictProtocolPrediction(
            outcome=RunOutcome.inconclusive,
            diagnostic=VerdictDiagnostic.policy_rejection.value,
        )
    if mode in _REVIEW_MODE_NAMES and terminal_publication_failed:
        return VerdictProtocolPrediction(
            outcome=RunOutcome.inconclusive,
            diagnostic=VerdictDiagnostic.terminal_submission_unpublished.value,
        )
    if mode in _REVIEW_MODE_NAMES and not result.terminal_submission_received:
        if mode in _INCREMENTAL_REVIEW_NAMES and final_summary_written:
            return VerdictProtocolPrediction(
                outcome=RunOutcome.passed,
                diagnostic=VerdictDiagnostic.approved.value,
            )
        return VerdictProtocolPrediction(
            outcome=RunOutcome.inconclusive,
            diagnostic=VerdictDiagnostic.provider_success_without_submission.value,
        )
    return VerdictProtocolPrediction(
        outcome=RunOutcome.passed,
        diagnostic=VerdictDiagnostic.approved.value,
    )


def predict_action(
    packet: MergeEvidencePacket,
    *,
    policy: GateActionPolicy | None = None,
) -> GateAction:
    """Read the gate's prediction without recording it (W10.2).

    Pure: same input, same output, no side effects. The shadow run
    opens with this call; the runner records the result via
    :func:`record_shadow_prediction` separately.
    """
    return decide_action(packet, policy=policy)


def enforce_action(
    packet: MergeEvidencePacket,
    *,
    policy: GateActionPolicy | None = None,
) -> GateAction:
    """Apply the gate's decision as the final action (W10.4).

    The function is structurally identical to ``predict_action`` — it
    is the same gate, the same packet, the same action. What differs
    is the I/O shell that calls it: the enforce path persists the
    decision on the packet and lets the runner apply the action. The
    distinction lives in the *mode* the gate is being run in, not in
    the gate itself.
    """
    return decide_action(packet, policy=policy)


def _emit_shadow_span(
    tracer: Tracer | NullTracer | None,
    *,
    change_id: str,
    target_id: str | None,
    disagreement: bool | None,
) -> None:
    """Emit one ``mergecraft.shadow.prediction`` span (best-effort, never throws).

    Tracing must never fail a review (convention 3): ``None`` / ``NullTracer``
    is a silent no-op, and any failure degrades to a missing span. The JSONL
    row is already on disk — the span is the second, optional surface.
    """
    if tracer is None:
        return
    try:
        span = tracer.start_span("mergecraft.shadow.prediction")
        span.__enter__()
        span.set_attribute("mergecraft.shadow.change_id", change_id)
        span.set_attribute("mergecraft.shadow.target_id", target_id)
        span.set_attribute("mergecraft.shadow.disagreement", disagreement)
        span.close()
    except Exception as exc:  # pragma: no cover — defensive; tracing is non-fatal
        logger.debug("shadow span failed: {}", exc)


def record_shadow_prediction(
    packet: MergeEvidencePacket,
    *,
    change_id: str,
    run_id: str,
    policy_id: str,
    output_path: Path,
    policy: GateActionPolicy | None = None,
    prediction: Any | None = None,
    actual_outcome: str | None = None,
    metadata: dict[str, Any] | None = None,
    target: ShadowTarget | None = None,
    tracer: Tracer | NullTracer | None = None,
) -> ShadowRecord:
    """Build a :class:`ShadowRecord` and append it to ``output_path`` (W10.2 / VP3).

    When ``prediction`` is supplied the row records a verdict-protocol or Jev
    shadow prediction in the same JSONL file as gate-action rows (D6).
    ``metadata`` is merged onto the row (Jev records pack id, model, and the
    raw confidence float here — never on ``Finding.evidence``). Otherwise the
    gate-action path is unchanged.

    ``target`` is additive (#737): a second shadow target is a second
    :class:`ShadowTarget` value recorded through this same writer, which stamps
    ``target_id`` / ``target_model`` / ``target_prompt_version`` onto the row.
    ``None`` preserves today's behaviour exactly — a legacy row with no target
    identity. When ``tracer`` is supplied one ``mergecraft.shadow.prediction``
    span is emitted; the JSONL row is still written either way, because the
    JSONL log remains the audit trail.
    """
    target_id = target.target_id if target is not None else None
    target_model = target.model if target is not None else None
    target_prompt_version = target.prompt_version if target is not None else None

    if prediction is not None:
        predicted_outcome = _prediction_outcome_value(prediction)
        diagnostic = _prediction_diagnostic_value(prediction)
        disagreement: bool | None = None
        pred_lane = getattr(prediction, "lane", None)
        predicted_lane = pred_lane if isinstance(pred_lane, str) and pred_lane else "review"
        merged_metadata: dict[str, Any] = {}
        if metadata:
            merged_metadata.update(metadata)
        pred_meta = getattr(prediction, "metadata", None)
        if isinstance(pred_meta, dict):
            merged_metadata.update(pred_meta)
        if actual_outcome is not None:
            report = disagree_with_outcome(
                predicted_action=predicted_outcome,
                actual_outcome=actual_outcome,
                predicted_lane=predicted_lane,
                predicted_rule_id=diagnostic,
                repo_area=policy_id,
            )
            raw_disagreement = report["disagreement"]
            disagreement = raw_disagreement if isinstance(raw_disagreement, bool) else None
        record = ShadowRecord(
            run_id=run_id,
            change_id=change_id,
            policy_id=policy_id,
            rule_id=diagnostic,
            action=predicted_outcome,
            lane=predicted_lane,
            repo_area=policy_id,
            outcome=predicted_outcome,
            predicted_outcome=predicted_outcome,
            diagnostic=diagnostic,
            verdict_diagnostic=diagnostic,
            actual_outcome=actual_outcome,
            disagreement=disagreement,
            metadata=merged_metadata,
            target_id=target_id,
            target_model=target_model,
            target_prompt_version=target_prompt_version,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json())
            handle.write("\n")
        logger.info(
            "» shadow record: change={} verdict_protocol outcome={} diagnostic={}",
            change_id,
            predicted_outcome,
            diagnostic,
        )
        _emit_shadow_span(
            tracer,
            change_id=change_id,
            target_id=target_id,
            disagreement=record.disagreement,
        )
        return record

    rule_id = select_rule_id(packet)
    action = predict_action(packet, policy=policy)
    _validate_action(action.value)
    lane = packet.blast_radius.lane if packet.blast_radius else None
    auto_merge_lane = packet.blast_radius.auto_merge_lane if packet.blast_radius else None
    record = ShadowRecord(
        run_id=run_id,
        change_id=change_id,
        policy_id=policy_id,
        rule_id=rule_id,
        action=action.value,
        lane=lane,
        auto_merge_lane=auto_merge_lane,
        repo_area=_lane_to_repo_area(packet),
        target_id=target_id,
        target_model=target_model,
        target_prompt_version=target_prompt_version,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(record.model_dump_json())
        handle.write("\n")
    logger.info(
        "» shadow record: change={} rule={} action={} lane={}",
        change_id,
        rule_id,
        action.value,
        lane,
    )
    _emit_shadow_span(
        tracer,
        change_id=change_id,
        target_id=target_id,
        disagreement=record.disagreement,
    )
    return record


def disagree_with_outcome(
    *,
    predicted_action: str,
    actual_outcome: str,
    predicted_lane: str,
    predicted_rule_id: str,
    repo_area: str,
) -> dict[str, object]:
    """Compare a prediction against the human final outcome (W10.3).

    A *disagreement* is recorded when the predicted action would have
    taken a different gate path than the human outcome. The mapping is
    deliberately narrow: predict a block, the human merged -> disagreement;
    predict an auto_merge, the human closed -> disagreement. Predicting
    a ``request_changes`` that the human merged is the more interesting
    case (the human overrode the gate's request for changes), and is
    also a disagreement.

    The function is pure: it returns a dict of structural fields. The
    caller groups these by ``lane`` and ``rule_id`` for the report.
    """
    # Normalize "merged" / "closed" / "changes_requested" / "auto_merge"
    # onto a single vocabulary: a "block-shaped" outcome is any negative
    # human final state. A "merge-shaped" outcome is a merge.
    block_shape = {"closed", "changes_requested", "block"}
    merge_shape = {"merged", "auto_merge"}
    # Normalize gate-action vocabulary and verdict-protocol run outcomes onto
    # comparable directions. Protocol outcomes each get their own direction so
    # ``passed`` vs ``inconclusive`` mismatches are not folded away.
    if predicted_action in _PROTOCOL_OUTCOMES:
        predicted_direction = predicted_action
    elif predicted_action in merge_shape:
        predicted_direction = "merge"
    elif predicted_action in block_shape:
        predicted_direction = "block"
    else:
        predicted_direction = "review"
    if actual_outcome in _PROTOCOL_OUTCOMES:
        actual_direction = actual_outcome
    elif actual_outcome in merge_shape:
        actual_direction = "merge"
    elif actual_outcome in block_shape:
        actual_direction = "block"
    else:
        actual_direction = "review"
    return {
        "lane": predicted_lane,
        "rule_id": predicted_rule_id,
        "repo_area": repo_area,
        "predicted_action": predicted_action,
        "actual_outcome": actual_outcome,
        "predicted_direction": predicted_direction,
        "actual_direction": actual_direction,
        "disagreement": predicted_direction != actual_direction,
    }


def load_shadow_records(path: Path) -> list[ShadowRecord]:
    """Read a JSON-Lines shadow log into a list of records.

    The function is tolerant: a malformed line is reported at warning
    level and skipped, so a single bad row never blocks the audit.
    """
    if not path.is_file():
        return []
    records: list[ShadowRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("shadow record: could not parse line ({})", exc)
            continue
        try:
            records.append(ShadowRecord.model_validate(payload))
        except Exception as exc:
            logger.warning("shadow record: validation failed ({})", exc)
            continue
    return records


def disagreement_report(
    records: list[ShadowRecord],
    *,
    outcomes: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """Group ``records`` by lane and rule with a disagreement flag (W10.4).

    The report returns one row per record. The caller can group in
    whatever way suits them; the rows are keyed by ``lane`` and
    ``rule_id`` themselves, and carry the target identity so a table can
    group by target as well (#737). ``outcomes`` maps ``change_id`` to the
    human final outcome as a string (``"merged"`` / ``"closed"`` /
    ``"changes_requested"``). When the outcome is absent the row
    carries ``disagreement=None`` so the report can render the missing
    data without dropping the row.
    """
    outcomes = outcomes or {}
    rows: list[dict[str, object]] = []
    for record in records:
        outcome = outcomes.get(record.change_id)
        if outcome is None:
            row: dict[str, object] = {
                "lane": record.lane,
                "rule_id": record.rule_id,
                "repo_area": record.repo_area,
                "predicted_action": record.action,
                "actual_outcome": None,
                "disagreement": None,
            }
        else:
            row = disagree_with_outcome(
                predicted_action=record.action,
                actual_outcome=outcome,
                predicted_lane=record.lane or "(unknown)",
                predicted_rule_id=record.rule_id,
                repo_area=record.repo_area or "(unknown)",
            )
        row["target_id"] = record.target_id
        row["target_model"] = record.target_model
        row["target_prompt_version"] = record.target_prompt_version
        rows.append(row)
    return rows


__all__ = [
    "ShadowRecord",
    "ShadowTarget",
    "VerdictProtocolPrediction",
    "disagree_with_outcome",
    "disagreement_report",
    "enforce_action",
    "load_shadow_records",
    "predict_action",
    "predict_verdict_protocol",
    "record_shadow_prediction",
]
