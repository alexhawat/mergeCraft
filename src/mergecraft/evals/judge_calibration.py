"""Offline calibration of saved verifier verdicts against human references."""

import json
import re
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mergecraft.agents.verifier import (
    HIGH_STAKES_LANES,
    AgentFinding,
    JudgePin,
    JudgeVerdict,
    JudgeVerdictName,
    VerdictOutcome,
)
from mergecraft.evals.adjudication import AdjudicationRecord, provenance_for
from mergecraft.evidence.packet import DeterministicCheck
from mergecraft.policy.schema import SeverityLiteral

CalibrationState = Literal["eligibility_only", "provisional", "validated", "rejected"]
_VERDICTS: tuple[JudgeVerdictName, ...] = ("confirm", "downgrade", "drop")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class HumanJudgeReference(BaseModel):
    """One independent human decision in the verifier's raw vocabulary."""

    model_config = ConfigDict(extra="forbid")

    verdict: JudgeVerdictName
    new_severity: SeverityLiteral | None = None

    @model_validator(mode="after")
    def _severity_matches_verdict(self) -> "HumanJudgeReference":
        if self.verdict == "downgrade" and self.new_severity is None:
            raise ValueError("a human downgrade reference must name new_severity")
        if self.verdict != "downgrade" and self.new_severity is not None:
            raise ValueError("new_severity is valid only for a downgrade reference")
        return self


class JudgeCalibrationCase(BaseModel):
    """One frozen finding with saved model and human decisions."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    finding: AgentFinding
    deterministic_checks: list[DeterministicCheck]
    lane: str
    evidence_sha256: str
    human_reference: HumanJudgeReference
    human_adjudicator_login: str
    human_adjudicated_at: datetime
    saved_judge_verdict: JudgeVerdict
    prompt_sha256: str
    policy_id: str
    policy_parameters: dict[str, str | int | float | bool]
    provenance: str
    adjudication: AdjudicationRecord
    saved_policy_outcome: VerdictOutcome | None = None

    @field_validator("case_id", "lane", "human_adjudicator_login", "policy_id")
    @classmethod
    def _nonempty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be empty")
        return value

    @field_validator("evidence_sha256", "prompt_sha256")
    @classmethod
    def _valid_evidence_hash(cls, value: str) -> str:
        if _SHA256_RE.fullmatch(value) is None:
            raise ValueError("evidence_sha256 must be 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def _validate_saved_pair(self) -> "JudgeCalibrationCase":
        if not self.deterministic_checks:
            raise ValueError("calibration cases require deterministic checks")
        if any(
            not check.name.strip() or not check.status.strip() or not check.command.strip()
            for check in self.deterministic_checks
        ):
            raise ValueError("deterministic check names, statuses, and commands must not be empty")
        if not self.policy_parameters:
            raise ValueError("calibration cases require explicit policy parameters")

        verdict = self.saved_judge_verdict
        pin: JudgePin = verdict.pin
        if any(
            not value.strip()
            for value in (pin.provider, pin.model, pin.judge_version, pin.rubric_version)
        ):
            raise ValueError(
                "judge provider, model, judge version, and rubric version are required"
            )
        if not pin.model_pinned:
            raise ValueError("calibration requires a pinned judge model")
        if not verdict.deterministic_checks:
            raise ValueError("the saved judge verdict must record deterministic checks")
        expected_checks = [check.name for check in self.deterministic_checks]
        if verdict.deterministic_checks != expected_checks:
            raise ValueError("saved verdict deterministic checks do not match case evidence")
        if verdict.fingerprint != self.finding.identity():
            raise ValueError("saved verdict fingerprint does not match the finding")
        if verdict.lane != self.lane:
            raise ValueError("saved verdict lane does not match the calibration case")

        if self.adjudication.adjudicated_by != "human":
            raise ValueError("judge calibration references require human adjudication")
        if self.adjudication.independence != "independent":
            raise ValueError("judge calibration references must be independently adjudicated")
        if provenance_for(self.adjudication) != self.provenance or self.provenance != "human":
            raise ValueError("agent-seeded or non-human reference truth is ineligible")
        if self.adjudication.at != self.human_adjudicated_at:
            raise ValueError("human_adjudicated_at must match the adjudication record")

        outcome = self.saved_policy_outcome
        if outcome is not None and (
            outcome.fingerprint != verdict.fingerprint or outcome.verdict != verdict.verdict
        ):
            raise ValueError("saved policy outcome does not match the judge verdict")
        if self.lane in HIGH_STAKES_LANES and verdict.verdict == "drop" and outcome is None:
            raise ValueError("high-stakes judge drops require a saved policy outcome")
        return self


class JudgeCalibrationProtocol(BaseModel):
    """Frozen split and explicit acceptance contract for one candidate."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    calibration_case_ids: list[str]
    held_out_case_ids: list[str]
    case_hashes: dict[str, str]
    minimum_per_class: int = Field(ge=1)
    minimum_macro_f1: float = Field(ge=0.0, le=1.0)
    minimum_drop_precision: float = Field(ge=0.0, le=1.0)
    minimum_confirm_recall: float = Field(ge=0.0, le=1.0)
    minimum_kappa: float = Field(ge=-1.0, le=1.0)
    maximum_disagreement_rate: float = Field(ge=0.0, le=1.0)
    required_high_stakes_escalation_recall: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_split_and_hashes(self) -> "JudgeCalibrationProtocol":
        calibration = self.calibration_case_ids
        held_out = self.held_out_case_ids
        if not calibration or not held_out:
            raise ValueError("calibration and held-out splits must both be non-empty")
        if len(calibration) != len(set(calibration)) or len(held_out) != len(set(held_out)):
            raise ValueError("calibration split IDs must be unique")
        overlap = set(calibration) & set(held_out)
        if overlap:
            raise ValueError(f"calibration and held-out splits overlap: {sorted(overlap)}")
        all_ids = set(calibration) | set(held_out)
        if set(self.case_hashes) != all_ids:
            raise ValueError("case_hashes must name exactly every split case")
        if any(_SHA256_RE.fullmatch(value) is None for value in self.case_hashes.values()):
            raise ValueError("case_hashes values must be lowercase SHA-256 digests")
        return self


class ClassMetrics(BaseModel):
    """Precision, recall, and direct multiclass F1 for one verdict."""

    model_config = ConfigDict(extra="forbid")

    support: int
    predicted: int
    true_positive: int
    precision: float | None
    recall: float | None
    f1: float | None


class CalibrationMetrics(BaseModel):
    """Paired judge-human metrics for one frozen split."""

    model_config = ConfigDict(extra="forbid")

    sample_count: int
    human_class_counts: dict[str, int]
    confusion_matrix: dict[str, dict[str, int]]
    per_class: dict[str, ClassMetrics]
    micro_precision: float | None
    micro_recall: float | None
    micro_f1: float | None
    macro_precision: float | None
    macro_recall: float | None
    macro_f1: float | None
    disagreement_rate: float | None
    cohen_kappa: float | None
    downgrade_severity_agreement: float | None
    downgrade_severity_pair_count: int
    high_stakes_escalation_recall: float | None
    high_stakes_drop_count: int
    limitations: list[str]


class CalibrationSplitReport(BaseModel):
    """Metrics plus every fail-closed threshold result for a split."""

    model_config = ConfigDict(extra="forbid")

    metrics: CalibrationMetrics
    threshold_results: dict[str, bool]
    passed: bool


class JudgeCalibrationReport(BaseModel):
    """Reproducible result for one fully frozen calibration protocol."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"] = "1.0.0"
    state: CalibrationState
    candidate_id: str
    prompt_sha256: str
    policy_id: str
    policy_parameters: dict[str, str | int | float | bool]
    protocol_sha256: str
    calibration_report_sha256: str
    case_hashes: dict[str, str]
    acceptance_contract: dict[str, float | int]
    calibration: CalibrationSplitReport
    held_out: CalibrationSplitReport | None
    seal_sha256: str | None = None
    sealed_by: str | None = None
    sealed_at: datetime | None = None
    limitations: list[str]


class JudgeCandidateSeal(BaseModel):
    """Operator-created commitment required before held-out metrics are computed."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    candidate_id: str
    prompt_sha256: str
    policy_id: str
    protocol_sha256: str
    case_hashes: dict[str, str]
    calibration_report_sha256: str
    policy_parameters: dict[str, str | int | float | bool]
    sealed_by: str
    sealed_at: datetime

    @field_validator("prompt_sha256", "protocol_sha256", "calibration_report_sha256")
    @classmethod
    def _valid_hash(cls, value: str) -> str:
        if _SHA256_RE.fullmatch(value) is None:
            raise ValueError("seal hashes must be lowercase SHA-256 digests")
        return value

    @model_validator(mode="after")
    def _complete_seal(self) -> "JudgeCandidateSeal":
        if (
            not self.candidate_id.strip()
            or not self.policy_id.strip()
            or not self.sealed_by.strip()
        ):
            raise ValueError("candidate_id, policy_id, and sealed_by must not be empty")
        if not self.policy_parameters:
            raise ValueError("the candidate seal must record explicit policy parameters")
        if any(_SHA256_RE.fullmatch(value) is None for value in self.case_hashes.values()):
            raise ValueError("sealed case hashes must be lowercase SHA-256 digests")
        return self


def case_sha256(case: JudgeCalibrationCase) -> str:
    """Return the canonical content digest pinned by a protocol."""
    rendered = json.dumps(
        case.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return sha256(rendered.encode()).hexdigest()


def protocol_sha256(protocol: JudgeCalibrationProtocol) -> str:
    """Return a canonical digest of the acceptance contract and split."""
    rendered = json.dumps(
        protocol.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256(rendered.encode()).hexdigest()


def calibration_report_sha256(report: CalibrationSplitReport) -> str:
    """Digest the calibration-only result committed by a candidate seal."""
    rendered = json.dumps(report.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256(rendered.encode()).hexdigest()


def candidate_seal_sha256(seal: JudgeCandidateSeal) -> str:
    """Return the immutable digest retained in a validated report."""
    rendered = json.dumps(seal.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256(rendered.encode()).hexdigest()


def _optional_mean(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def compute_calibration_metrics(cases: list[JudgeCalibrationCase]) -> CalibrationMetrics:
    """Compute the saved raw-verdict agreement metrics without calling a provider."""
    matrix: dict[str, dict[str, int]] = {
        human: {judge: 0 for judge in _VERDICTS} for human in _VERDICTS
    }
    for case in cases:
        matrix[case.human_reference.verdict][case.saved_judge_verdict.verdict] += 1

    per_class: dict[str, ClassMetrics] = {}
    for verdict in _VERDICTS:
        tp = matrix[verdict][verdict]
        support = sum(matrix[verdict].values())
        predicted = sum(matrix[human][verdict] for human in _VERDICTS)
        precision = tp / predicted if predicted else None
        recall = tp / support if support else None
        f1_denominator = 2 * tp + (predicted - tp) + (support - tp)
        f1 = 2 * tp / f1_denominator if f1_denominator else None
        per_class[verdict] = ClassMetrics(
            support=support,
            predicted=predicted,
            true_positive=tp,
            precision=precision,
            recall=recall,
            f1=f1,
        )

    sample_count = len(cases)
    diagonal = sum(matrix[label][label] for label in _VERDICTS)
    micro = diagonal / sample_count if sample_count else None
    disagreement = 1.0 - micro if micro is not None else None
    if sample_count:
        observed = diagonal / sample_count
        expected = sum(
            sum(matrix[label].values()) * sum(matrix[human][label] for human in _VERDICTS)
            for label in _VERDICTS
        ) / (sample_count**2)
        kappa = (observed - expected) / (1.0 - expected) if expected != 1.0 else None
    else:
        kappa = None

    severity_pairs = [
        case
        for case in cases
        if case.human_reference.verdict == "downgrade"
        and case.saved_judge_verdict.verdict == "downgrade"
    ]
    severity_agreement = (
        sum(
            case.human_reference.new_severity == case.saved_judge_verdict.new_severity
            for case in severity_pairs
        )
        / len(severity_pairs)
        if severity_pairs
        else None
    )

    high_stakes_drops = [
        case
        for case in cases
        if case.lane in HIGH_STAKES_LANES and case.saved_judge_verdict.verdict == "drop"
    ]
    escalation_recall = (
        sum(
            case.saved_policy_outcome is not None and case.saved_policy_outcome.escalated_to_human
            for case in high_stakes_drops
        )
        / len(high_stakes_drops)
        if high_stakes_drops
        else None
    )

    counts: dict[str, int] = {label: sum(matrix[label].values()) for label in _VERDICTS}
    limitations = [
        "References contain one human decision per case; human-human reliability was not measured."
    ]
    missing_classes = [label for label, count in counts.items() if count == 0]
    if missing_classes:
        limitations.append(f"Human reference has no samples for: {', '.join(missing_classes)}.")
    if kappa is None:
        limitations.append("Cohen's kappa is undefined for this paired sample.")
    return CalibrationMetrics(
        sample_count=sample_count,
        human_class_counts=counts,
        confusion_matrix=matrix,
        per_class=per_class,
        micro_precision=micro,
        micro_recall=micro,
        micro_f1=micro,
        macro_precision=_optional_mean([per_class[label].precision for label in _VERDICTS]),
        macro_recall=_optional_mean([per_class[label].recall for label in _VERDICTS]),
        macro_f1=_optional_mean([per_class[label].f1 for label in _VERDICTS]),
        disagreement_rate=disagreement,
        cohen_kappa=kappa,
        downgrade_severity_agreement=severity_agreement,
        downgrade_severity_pair_count=len(severity_pairs),
        high_stakes_escalation_recall=escalation_recall,
        high_stakes_drop_count=len(high_stakes_drops),
        limitations=limitations,
    )


def _threshold_report(
    metrics: CalibrationMetrics, protocol: JudgeCalibrationProtocol
) -> CalibrationSplitReport:
    def minimum(value: float | None, threshold: float) -> bool:
        return value is not None and value >= threshold

    results = {
        "minimum_per_class": all(
            metrics.human_class_counts[label] >= protocol.minimum_per_class for label in _VERDICTS
        ),
        "minimum_macro_f1": minimum(metrics.macro_f1, protocol.minimum_macro_f1),
        "minimum_drop_precision": minimum(
            metrics.per_class["drop"].precision, protocol.minimum_drop_precision
        ),
        "minimum_confirm_recall": minimum(
            metrics.per_class["confirm"].recall, protocol.minimum_confirm_recall
        ),
        "minimum_kappa": minimum(metrics.cohen_kappa, protocol.minimum_kappa),
        "maximum_disagreement_rate": (
            metrics.disagreement_rate is not None
            and metrics.disagreement_rate <= protocol.maximum_disagreement_rate
        ),
        "required_high_stakes_escalation_recall": minimum(
            metrics.high_stakes_escalation_recall,
            protocol.required_high_stakes_escalation_recall,
        ),
    }
    return CalibrationSplitReport(
        metrics=metrics,
        threshold_results=results,
        passed=all(results.values()),
    )


def evaluate_judge_calibration(
    protocol: JudgeCalibrationProtocol,
    cases: list[JudgeCalibrationCase],
    *,
    seal: JudgeCandidateSeal | None = None,
) -> JudgeCalibrationReport:
    """Validate frozen inputs, then score calibration and held-out splits once."""
    by_id: dict[str, JudgeCalibrationCase] = {}
    for case in cases:
        if case.case_id in by_id:
            raise ValueError(f"duplicate calibration case ID: {case.case_id}")
        by_id[case.case_id] = case
    expected_ids = set(protocol.calibration_case_ids) | set(protocol.held_out_case_ids)
    if set(by_id) != expected_ids:
        raise ValueError("cases must contain exactly every protocol split ID")
    actual_hashes = {case_id: case_sha256(case) for case_id, case in by_id.items()}
    if actual_hashes != protocol.case_hashes:
        raise ValueError("calibration case hash drift detected")

    calibration_evidence = {
        by_id[case_id].evidence_sha256 for case_id in protocol.calibration_case_ids
    }
    held_out_evidence = {by_id[case_id].evidence_sha256 for case_id in protocol.held_out_case_ids}
    overlap = calibration_evidence & held_out_evidence
    if overlap:
        raise ValueError("calibration and held-out splits reuse frozen evidence")

    pins = {case.saved_judge_verdict.pin.model_dump_json() for case in cases}
    if len(pins) != 1:
        raise ValueError("all calibration cases must use one pinned judge candidate")
    pin = cases[0].saved_judge_verdict.pin
    candidate_contracts = {
        (
            case.prompt_sha256,
            case.policy_id,
            json.dumps(case.policy_parameters, sort_keys=True, separators=(",", ":")),
        )
        for case in cases
    }
    if len(candidate_contracts) != 1:
        raise ValueError("all calibration cases must use one prompt and policy contract")
    prompt_hash, policy_id, _ = next(iter(candidate_contracts))
    policy_parameters = cases[0].policy_parameters
    candidate_id = (
        f"{pin.provider}/{pin.model}@judge-{pin.judge_version}/rubric-{pin.rubric_version}"
        f"/prompt-{prompt_hash[:12]}/policy-{policy_id}"
    )
    calibration = _threshold_report(
        compute_calibration_metrics([by_id[case_id] for case_id in protocol.calibration_case_ids]),
        protocol,
    )
    calibration_hash = calibration_report_sha256(calibration)
    contract = {
        "minimum_per_class": protocol.minimum_per_class,
        "minimum_macro_f1": protocol.minimum_macro_f1,
        "minimum_drop_precision": protocol.minimum_drop_precision,
        "minimum_confirm_recall": protocol.minimum_confirm_recall,
        "minimum_kappa": protocol.minimum_kappa,
        "maximum_disagreement_rate": protocol.maximum_disagreement_rate,
        "required_high_stakes_escalation_recall": (protocol.required_high_stakes_escalation_recall),
    }
    base_limitations = [
        "This report measures judge-human agreement for one human reference per case; "
        "it does not establish human-human reliability.",
        "The file format cannot prove held-out data was never inspected before sealing; "
        "operational access control and a new protocol version are required for each run.",
    ]
    if not calibration.passed:
        return JudgeCalibrationReport(
            state="rejected",
            candidate_id=candidate_id,
            prompt_sha256=prompt_hash,
            policy_id=policy_id,
            policy_parameters=policy_parameters,
            protocol_sha256=protocol_sha256(protocol),
            calibration_report_sha256=calibration_hash,
            case_hashes=actual_hashes,
            acceptance_contract=contract,
            calibration=calibration,
            held_out=None,
            limitations=base_limitations,
        )
    if seal is None:
        return JudgeCalibrationReport(
            state="provisional",
            candidate_id=candidate_id,
            prompt_sha256=prompt_hash,
            policy_id=policy_id,
            policy_parameters=policy_parameters,
            protocol_sha256=protocol_sha256(protocol),
            calibration_report_sha256=calibration_hash,
            case_hashes=actual_hashes,
            acceptance_contract=contract,
            calibration=calibration,
            held_out=None,
            limitations=[
                *base_limitations,
                "Held-out metrics were not computed because no precommitted candidate seal "
                "was supplied.",
            ],
        )

    expected_protocol_hash = protocol_sha256(protocol)
    expected_calibration_hash = calibration_hash
    if seal.candidate_id != candidate_id:
        raise ValueError("candidate seal identity does not match saved judge pins")
    if seal.prompt_sha256 != prompt_hash:
        raise ValueError("candidate seal prompt hash mismatch")
    if seal.policy_id != policy_id or seal.policy_parameters != policy_parameters:
        raise ValueError("candidate seal policy contract mismatch")
    if seal.protocol_sha256 != expected_protocol_hash:
        raise ValueError("candidate seal protocol hash mismatch")
    if seal.case_hashes != actual_hashes:
        raise ValueError("candidate seal dataset hashes mismatch")
    if seal.calibration_report_sha256 != expected_calibration_hash:
        raise ValueError("candidate seal calibration report hash mismatch")

    held_out = _threshold_report(
        compute_calibration_metrics([by_id[case_id] for case_id in protocol.held_out_case_ids]),
        protocol,
    )
    return JudgeCalibrationReport(
        state="validated" if held_out.passed else "rejected",
        candidate_id=candidate_id,
        prompt_sha256=prompt_hash,
        policy_id=policy_id,
        policy_parameters=policy_parameters,
        protocol_sha256=expected_protocol_hash,
        calibration_report_sha256=calibration_hash,
        case_hashes=actual_hashes,
        acceptance_contract=contract,
        calibration=calibration,
        held_out=held_out,
        seal_sha256=candidate_seal_sha256(seal),
        sealed_by=seal.sealed_by,
        sealed_at=seal.sealed_at,
        limitations=base_limitations,
    )


def load_and_evaluate(
    protocol_path: Path,
    cases_path: Path,
    *,
    seal_path: Path | None = None,
) -> JudgeCalibrationReport:
    """Load strict JSON inputs and return an offline saved-verdict report."""
    protocol = JudgeCalibrationProtocol.model_validate_json(
        protocol_path.read_text(encoding="utf-8")
    )
    raw_cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list):
        raise ValueError("judge calibration cases must be a JSON list")
    cases = [JudgeCalibrationCase.model_validate(item) for item in raw_cases]
    seal = (
        JudgeCandidateSeal.model_validate_json(seal_path.read_text(encoding="utf-8"))
        if seal_path is not None
        else None
    )
    return evaluate_judge_calibration(protocol, cases, seal=seal)


__all__ = [
    "CalibrationMetrics",
    "CalibrationSplitReport",
    "CalibrationState",
    "ClassMetrics",
    "HumanJudgeReference",
    "JudgeCalibrationCase",
    "JudgeCalibrationProtocol",
    "JudgeCalibrationReport",
    "JudgeCandidateSeal",
    "calibration_report_sha256",
    "candidate_seal_sha256",
    "case_sha256",
    "compute_calibration_metrics",
    "evaluate_judge_calibration",
    "load_and_evaluate",
    "protocol_sha256",
]
