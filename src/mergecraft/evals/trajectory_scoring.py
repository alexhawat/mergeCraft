"""Strict, offline scoring for the trajectory auditor (#735).

The scorer compares the eight deterministic trajectory checks with frozen,
path-aware labels.  Development labels are useful for exercising this code,
but their provenance is reported as advisory and can never establish an
independent quality claim.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime  # noqa: TC003 - Pydantic resolves this annotation at runtime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, Self

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mergecraft.analyzers.finding import Finding  # noqa: TC001 - Pydantic runtime field
from mergecraft.evals.adjudication import AdjudicationRecord, provenance_for
from mergecraft.evidence.trajectory import TrajectoryRecord  # noqa: TC001 - Pydantic runtime field
from mergecraft.evidence.trajectory_audit import (
    TRAJECTORY_AUDITOR_VERSION,
    TRAJECTORY_CHECKS,
    audit_trajectory,
)

if TYPE_CHECKING:
    from mergecraft.tracing.tracer import NullTracer, Tracer

TRAJECTORY_LABEL_SCHEMA_VERSION: Final[Literal["1.0.0"]] = "1.0.0"
TRAJECTORY_SCORER_VERSION: Final[str] = "1.0.0"
TRAJECTORY_PROTOCOL_SCHEMA_VERSION: Final[Literal["1.0.0"]] = "1.0.0"
DEFAULT_TRAJECTORY_PROTOCOL_PATH: Final[Path] = Path("evals/trajectories/protocol-v1.json")

TrajectorySplit = Literal["development", "calibration", "held_out"]
TrajectoryTruth = Literal["positive", "negative", "unknown"]
TrajectoryLabelProvenance = Literal["agent-seeded", "human"]

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}\Z")
_RULE_IDS: Final[tuple[str, ...]] = tuple(check.rule_id for check in TRAJECTORY_CHECKS)
_RULE_ID_SET: Final[frozenset[str]] = frozenset(_RULE_IDS)


def canonical_trajectory_sha256(trajectory: TrajectoryRecord) -> str:
    """Return the stable digest of one strict trajectory record."""
    encoded = json.dumps(
        trajectory.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def canonical_label_set_sha256(label_set: TrajectoryLabelSet) -> str:
    """Return the stable digest of one fully validated label set."""
    encoded = json.dumps(
        label_set.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class TrajectoryCheckLabel(BaseModel):
    """Human or development truth for one named auditor check."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    truth: TrajectoryTruth
    expected_paths: list[str]

    @field_validator("rule_id")
    @classmethod
    def _known_rule_id(cls, value: str) -> str:
        if value not in _RULE_ID_SET:
            raise ValueError(f"unknown trajectory check {value!r}")
        return value

    @model_validator(mode="after")
    def _expected_paths_match_truth(self) -> Self:
        if self.truth == "positive" and not self.expected_paths:
            raise ValueError("positive labels require at least one expected_paths entry")
        if self.truth != "positive" and self.expected_paths:
            raise ValueError(f"{self.truth} labels require empty expected_paths")
        return self


class TrajectoryLabelCase(BaseModel):
    """One frozen trajectory and the complete eight-check label vector."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    trajectory: TrajectoryRecord
    trajectory_sha256: str
    # A case that omits provenance is agent-seeded by default: it stays in the
    # advisory development tier and can never establish an independent claim.
    labelled_at: datetime | None = None
    provenance: TrajectoryLabelProvenance = "agent-seeded"
    adjudication: AdjudicationRecord | None = None
    labels: list[TrajectoryCheckLabel]

    @field_validator("case_id")
    @classmethod
    def _case_id_is_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("case_id must not be empty")
        return value

    @field_validator("trajectory_sha256")
    @classmethod
    def _trajectory_digest_is_valid(cls, value: str) -> str:
        if _SHA256_RE.fullmatch(value) is None:
            raise ValueError("trajectory_sha256 must be 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def _validate_frozen_case(self) -> Self:
        actual = canonical_trajectory_sha256(self.trajectory)
        if self.trajectory_sha256 != actual:
            raise ValueError(
                "trajectory_sha256 does not match the canonical TrajectoryRecord payload"
            )

        seen = [label.rule_id for label in self.labels]
        if len(seen) != len(_RULE_IDS) or set(seen) != _RULE_ID_SET:
            missing = sorted(_RULE_ID_SET - set(seen))
            duplicated = sorted(rule_id for rule_id, count in Counter(seen).items() if count > 1)
            raise ValueError(
                "labels must contain every runtime trajectory check exactly once "
                f"(missing={missing}, duplicated={duplicated})"
            )

        if self.provenance == "agent-seeded":
            if self.adjudication is not None:
                raise ValueError("agent-seeded labels must not claim an adjudication record")
            return self

        if self.labelled_at is None or self.adjudication is None:
            raise ValueError("human labels require labelled_at and an adjudication record")
        if self.adjudication.adjudicated_by != "human":
            raise ValueError("human trajectory labels require human adjudication")
        if self.adjudication.independence != "independent":
            raise ValueError("human trajectory labels require independent adjudication")
        if provenance_for(self.adjudication) != self.provenance:
            raise ValueError("label provenance does not match its adjudication record")
        if self.adjudication.at != self.labelled_at:
            raise ValueError("labelled_at must match the adjudication timestamp")
        return self


class TrajectoryLabelSet(BaseModel):
    """One split of frozen trajectory labels."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    auditor_version: str
    split: TrajectorySplit
    source_commit: str
    adjudicator_login: str | None
    cases: list[TrajectoryLabelCase]

    @field_validator("source_commit")
    @classmethod
    def _source_commit_is_pinned(cls, value: str) -> str:
        if _COMMIT_RE.fullmatch(value) is None:
            raise ValueError("source_commit must be a full 40-character lowercase git commit")
        return value

    @model_validator(mode="after")
    def _validate_set(self) -> Self:
        if self.auditor_version != TRAJECTORY_AUDITOR_VERSION:
            raise ValueError(
                "auditor_version is incompatible with the running auditor: "
                f"expected {TRAJECTORY_AUDITOR_VERSION!r}"
            )
        if not self.cases:
            raise ValueError("trajectory label sets require at least one case")
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("duplicate case_id in trajectory label set")
        trajectory_hashes = [case.trajectory_sha256 for case in self.cases]
        if len(trajectory_hashes) != len(set(trajectory_hashes)):
            raise ValueError("duplicate trajectory_sha256 in trajectory label set")

        if self.split in {"calibration", "held_out"}:
            if self.adjudicator_login is None or not self.adjudicator_login.strip():
                raise ValueError(
                    "independent calibration/held_out labels require adjudicator_login"
                )
            if any(case.provenance != "human" for case in self.cases):
                raise ValueError("independent calibration/held_out labels require human provenance")
            if any(case.labelled_at is None for case in self.cases):
                raise ValueError("independent calibration/held_out labels require labelled_at")
        if any(case.provenance == "human" for case in self.cases) and (
            self.adjudicator_login is None or not self.adjudicator_login.strip()
        ):
            raise ValueError("human trajectory labels require adjudicator_login")
        return self


def validate_label_sets(label_sets: list[TrajectoryLabelSet]) -> None:
    """Reject case/evidence identities reused anywhere in the input corpus."""
    if not label_sets:
        raise ValueError("no trajectory label sets were provided")
    seen_case_ids: set[str] = set()
    seen_digests: set[str] = set()
    for label_set in label_sets:
        for case in label_set.cases:
            if case.case_id in seen_case_ids:
                raise ValueError(
                    f"duplicate case_id across trajectory label sets: {case.case_id!r}"
                )
            if case.trajectory_sha256 in seen_digests:
                raise ValueError(
                    "duplicate trajectory_sha256 across trajectory label sets: "
                    f"{case.trajectory_sha256!r}"
                )
            seen_case_ids.add(case.case_id)
            seen_digests.add(case.trajectory_sha256)


def load_trajectory_label_sets(path: Path) -> list[TrajectoryLabelSet]:
    """Load one label-set JSON file or every JSON file below a directory."""
    paths = sorted(path.rglob("*.json")) if path.is_dir() else [path]
    if not paths or any(not candidate.is_file() for candidate in paths):
        raise ValueError(f"no trajectory label JSON files found at {path}")
    label_sets: list[TrajectoryLabelSet] = []
    for candidate in paths:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        label_sets.append(TrajectoryLabelSet.model_validate(payload))
    validate_label_sets(label_sets)
    return label_sets


class TrajectoryProtocol(BaseModel):
    """Pre-registered sample minimums and a comparison tolerance.

    The protocol is the one artefact that turns an independently labelled
    report into a quality claim. It pins, per runtime check, how many
    independent samples a report must carry before it can be eligible, and the
    relative drift a candidate report may show against a frozen baseline before
    the comparison fails.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    sample_minimums: dict[str, int]
    tolerance: float = Field(ge=0.0)

    @field_validator("sample_minimums")
    @classmethod
    def _sample_minimums_cover_every_check(cls, value: dict[str, int]) -> dict[str, int]:
        unknown = sorted(set(value) - _RULE_ID_SET)
        if unknown:
            raise ValueError(f"unknown trajectory check in sample_minimums: {unknown}")
        missing = sorted(_RULE_ID_SET - set(value))
        if missing:
            raise ValueError(
                f"sample_minimums must pre-register every trajectory check: missing={missing}"
            )
        for rule_id, minimum in value.items():
            if minimum < 1:
                raise ValueError(f"sample_minimums[{rule_id!r}] must be at least 1, got {minimum}")
        return value


def load_trajectory_protocol(path: Path) -> TrajectoryProtocol:
    """Load and validate one approved trajectory protocol JSON file."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return TrajectoryProtocol.model_validate(payload)


class TrajectoryRuleMetrics(BaseModel):
    """Confusion counts and rates for one trajectory check."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    precision: float | None
    recall: float | None


class TrajectoryMicroMetrics(BaseModel):
    """Counts summed before calculating corpus-level rates."""

    model_config = ConfigDict(extra="forbid")

    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    precision: float | None
    recall: float | None


class TrajectoryMacroMetrics(BaseModel):
    """Mean of only the per-check metrics whose denominators are defined."""

    model_config = ConfigDict(extra="forbid")

    precision: float | None
    recall: float | None
    precision_checks: int = Field(ge=0)
    recall_checks: int = Field(ge=0)


class TrajectoryExactMatch(BaseModel):
    """Run-level exact-match result over cases with non-unknown labels."""

    model_config = ConfigDict(extra="forbid")

    eligible_cases: int = Field(ge=0)
    exact_cases: int = Field(ge=0)
    rate: float | None


class TrajectoryDisagreement(BaseModel):
    """One exact ``(rule_id, path)`` count mismatch."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    rule_id: str
    path: str
    expected_count: int = Field(ge=0)
    predicted_count: int = Field(ge=0)


class TrajectoryCaseScore(BaseModel):
    """Raw auditor output and exact-match status for one labelled run."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    split: TrajectorySplit
    provenance: TrajectoryLabelProvenance
    trajectory_sha256: str
    predictions: list[Finding]
    eligible_for_exact_match: bool
    exact_match: bool | None


class TrajectoryLabelCounts(BaseModel):
    """Per-check label counts, including excluded unknown rows."""

    model_config = ConfigDict(extra="forbid")

    positive: int = Field(ge=0)
    negative: int = Field(ge=0)
    unknown: int = Field(ge=0)
    scored: int = Field(ge=0)
    independent: int = Field(ge=0)


class TrajectoryEligibility(BaseModel):
    """Whether the report rests entirely on independent human truth."""

    model_config = ConfigDict(extra="forbid")

    independent: bool
    quality_eligible: bool
    advisory: bool
    reason: str
    provenance_counts: dict[str, int]
    per_check: dict[str, TrajectoryLabelCounts]


class TrajectoryLabelSetReference(BaseModel):
    """Immutable identity needed to reproduce one report input."""

    model_config = ConfigDict(extra="forbid")

    split: TrajectorySplit
    source_commit: str
    adjudicator_login: str | None
    label_set_sha256: str
    case_ids: list[str]


class TrajectoryScoreReport(BaseModel):
    """Reproducible labelled report for the running trajectory auditor."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"] = TRAJECTORY_LABEL_SCHEMA_VERSION
    scorer_version: str = TRAJECTORY_SCORER_VERSION
    auditor_version: str = TRAJECTORY_AUDITOR_VERSION
    label_sets: int = Field(ge=1)
    cases_total: int = Field(ge=1)
    inputs: list[TrajectoryLabelSetReference]
    per_check: list[TrajectoryRuleMetrics]
    micro: TrajectoryMicroMetrics
    macro: TrajectoryMacroMetrics
    exact_match: TrajectoryExactMatch
    eligibility: TrajectoryEligibility
    cases: list[TrajectoryCaseScore]
    disagreements: list[TrajectoryDisagreement]


class TrajectoryComparisonResult(BaseModel):
    """Outcome of comparing a candidate report against a frozen baseline.

    ``failures`` holds the rule ids whose per-check counts drifted outside the
    protocol tolerance, so the failing check is named rather than summarised.
    """

    model_config = ConfigDict(extra="forbid")

    passed: bool
    tolerance: float = Field(ge=0.0)
    failures: list[str]
    compared_checks: int = Field(ge=0)


_COUNT_METRICS: Final[tuple[str, ...]] = ("true_positive", "false_positive", "false_negative")


def _counts_drift_outside_tolerance(
    baseline: TrajectoryRuleMetrics,
    candidate: TrajectoryRuleMetrics,
    tolerance: float,
) -> bool:
    """True when any per-check count drifts by more than *tolerance*.

    Each count is compared as a symmetric relative difference,
    ``|candidate - baseline| / max(|candidate|, |baseline|, 1)``. The floor of
    one bounds a move away from zero (an all-zero baseline cannot divide by
    zero), so a move from 0 to *n* reads as a drift of exactly 1.0 — only a
    tolerance of 1.0 or wider admits it, and any genuine count change at a
    tighter tolerance is named.
    """
    for metric in _COUNT_METRICS:
        baseline_value = float(getattr(baseline, metric))
        candidate_value = float(getattr(candidate, metric))
        scale = max(abs(candidate_value), abs(baseline_value), 1.0)
        if abs(candidate_value - baseline_value) / scale > tolerance:
            return True
    return False


def compare_trajectory_report(
    candidate: TrajectoryScoreReport,
    baseline: TrajectoryScoreReport,
    *,
    protocol: TrajectoryProtocol,
) -> TrajectoryComparisonResult:
    """Compare a candidate report's per-check counts against a frozen baseline.

    A check fails when any of its confusion counts drifts by more than the
    protocol ``tolerance`` relative to the baseline (counts scale by a floor of
    one so a move away from zero is never lost). The returned ``failures`` name
    every such check by rule id.
    """
    baseline_by_rule = {row.rule_id: row for row in baseline.per_check}
    candidate_by_rule = {row.rule_id: row for row in candidate.per_check}
    failures: list[str] = []
    for rule_id in _RULE_IDS:
        baseline_row = baseline_by_rule.get(rule_id)
        candidate_row = candidate_by_rule.get(rule_id)
        if (
            baseline_row is None
            or candidate_row is None
            or _counts_drift_outside_tolerance(baseline_row, candidate_row, protocol.tolerance)
        ):
            failures.append(rule_id)
    known = set(_RULE_IDS)
    extra = sorted((set(baseline_by_rule) | set(candidate_by_rule)) - known)
    failures.extend(rule_id for rule_id in extra if rule_id not in failures)
    return TrajectoryComparisonResult(
        passed=not failures,
        tolerance=protocol.tolerance,
        failures=failures,
        compared_checks=len(_RULE_IDS),
    )


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _emit_case_score(
    *,
    tracer: Tracer | NullTracer | None,
    case_id: str,
    counts: dict[str, tuple[int, int, int]],
) -> None:
    try:
        from mergecraft.tracing import current_tracer
        from mergecraft.tracing.signals import emit_eval_score

        active_tracer = tracer if tracer is not None else current_tracer()
        metrics: dict[str, Any] = {}
        for rule_id, (true_positive, false_positive, false_negative) in counts.items():
            prefix = f"trajectory.{rule_id}"
            metrics[f"{prefix}.true_positive"] = true_positive
            metrics[f"{prefix}.false_positive"] = false_positive
            metrics[f"{prefix}.false_negative"] = false_negative
            precision = _rate(true_positive, true_positive + false_positive)
            recall = _rate(true_positive, true_positive + false_negative)
            if precision is not None:
                metrics[f"{prefix}.precision"] = precision
            if recall is not None:
                metrics[f"{prefix}.recall"] = recall
        emit_eval_score(active_tracer, case_id=case_id, metrics=metrics)
    except Exception as exc:  # pragma: no cover - tracing is strictly best effort
        logger.debug("trajectory score span skipped for {}: {}", case_id, exc)


def score_trajectory_labels(
    label_sets: list[TrajectoryLabelSet],
    *,
    protocol: TrajectoryProtocol | None = None,
    tracer: Tracer | NullTracer | None = None,
) -> TrajectoryScoreReport:
    """Run the current auditor and score exact rule/path multiplicities.

    ``quality_eligible`` is true only when the labels are independent, an
    approved ``protocol`` is supplied, and every runtime check carries at least
    its pre-registered independent sample minimum. Without a protocol the
    report stays advisory and nothing is enforced.
    """
    validate_label_sets(label_sets)
    aggregate: dict[str, list[int]] = {rule_id: [0, 0, 0] for rule_id in _RULE_IDS}
    label_counts: dict[str, Counter[str]] = {rule_id: Counter() for rule_id in _RULE_IDS}
    provenance_counts: Counter[str] = Counter()
    case_scores: list[TrajectoryCaseScore] = []
    disagreements: list[TrajectoryDisagreement] = []
    eligible_cases = 0
    exact_cases = 0

    for label_set in label_sets:
        for case in label_set.cases:
            provenance_counts[case.provenance] += 1
            labels = {label.rule_id: label for label in case.labels}
            for label in case.labels:
                label_counts[label.rule_id][label.truth] += 1
                if label.truth != "unknown":
                    label_counts[label.rule_id]["scored"] += 1
                    if (
                        case.provenance == "human"
                        and case.adjudication is not None
                        and case.adjudication.independence == "independent"
                    ):
                        label_counts[label.rule_id]["independent"] += 1

            predictions = audit_trajectory(case.trajectory)
            unknown_prediction_rules = sorted(
                {finding.rule_id for finding in predictions if finding.rule_id not in _RULE_ID_SET}
            )
            if unknown_prediction_rules:
                raise ValueError(
                    "auditor emitted rule IDs absent from the labelled contract: "
                    f"{unknown_prediction_rules}"
                )
            predicted_by_rule: dict[str, Counter[str]] = {
                rule_id: Counter() for rule_id in _RULE_IDS
            }
            for finding in predictions:
                if finding.rule_id in predicted_by_rule:
                    predicted_by_rule[finding.rule_id][finding.path] += 1

            case_counts: dict[str, tuple[int, int, int]] = {}
            case_is_eligible = False
            case_is_exact = True
            for rule_id in _RULE_IDS:
                label = labels[rule_id]
                if label.truth == "unknown":
                    continue
                case_is_eligible = True
                expected = Counter(label.expected_paths)
                predicted = predicted_by_rule[rule_id]
                keys = set(expected) | set(predicted)
                true_positive = sum(min(expected[path], predicted[path]) for path in keys)
                false_positive = sum(max(predicted[path] - expected[path], 0) for path in keys)
                false_negative = sum(max(expected[path] - predicted[path], 0) for path in keys)
                totals = aggregate[rule_id]
                totals[0] += true_positive
                totals[1] += false_positive
                totals[2] += false_negative
                case_counts[rule_id] = (true_positive, false_positive, false_negative)
                if predicted != expected:
                    case_is_exact = False
                    for path in sorted(keys):
                        if predicted[path] != expected[path]:
                            disagreements.append(
                                TrajectoryDisagreement(
                                    case_id=case.case_id,
                                    rule_id=rule_id,
                                    path=path,
                                    expected_count=expected[path],
                                    predicted_count=predicted[path],
                                )
                            )

            if case_is_eligible:
                eligible_cases += 1
                if case_is_exact:
                    exact_cases += 1
            case_scores.append(
                TrajectoryCaseScore(
                    case_id=case.case_id,
                    split=label_set.split,
                    provenance=case.provenance,
                    trajectory_sha256=case.trajectory_sha256,
                    predictions=predictions,
                    eligible_for_exact_match=case_is_eligible,
                    exact_match=case_is_exact if case_is_eligible else None,
                )
            )
            _emit_case_score(tracer=tracer, case_id=case.case_id, counts=case_counts)

    per_check = [
        TrajectoryRuleMetrics(
            rule_id=rule_id,
            true_positive=counts[0],
            false_positive=counts[1],
            false_negative=counts[2],
            precision=_rate(counts[0], counts[0] + counts[1]),
            recall=_rate(counts[0], counts[0] + counts[2]),
        )
        for rule_id, counts in aggregate.items()
    ]
    total_tp = sum(row.true_positive for row in per_check)
    total_fp = sum(row.false_positive for row in per_check)
    total_fn = sum(row.false_negative for row in per_check)
    defined_precision = [row.precision for row in per_check if row.precision is not None]
    defined_recall = [row.recall for row in per_check if row.recall is not None]

    all_cases = [case for label_set in label_sets for case in label_set.cases]
    independent = bool(all_cases) and all(
        label_set.split in {"calibration", "held_out"}
        and case.provenance == "human"
        and case.adjudication is not None
        and case.adjudication.independence == "independent"
        for label_set in label_sets
        for case in label_set.cases
    )
    if not independent:
        quality_eligible = False
        advisory = True
        reason = "development or non-independent labels are advisory only"
    elif protocol is None:
        quality_eligible = False
        advisory = True
        reason = (
            "no approved protocol — advisory; independent labels cannot support a quality "
            "claim until a protocol pins per-check sample minimums and a tolerance"
        )
    else:
        below_minimum = [
            rule_id
            for rule_id in _RULE_IDS
            if label_counts[rule_id]["independent"] < protocol.sample_minimums[rule_id]
        ]
        if below_minimum:
            quality_eligible = False
            advisory = True
            reason = "checks below their pre-registered sample minimum: " + ", ".join(below_minimum)
        else:
            quality_eligible = True
            advisory = False
            reason = "independent labels meet every pre-registered sample minimum"
    return TrajectoryScoreReport(
        label_sets=len(label_sets),
        cases_total=len(all_cases),
        inputs=[
            TrajectoryLabelSetReference(
                split=label_set.split,
                source_commit=label_set.source_commit,
                adjudicator_login=label_set.adjudicator_login,
                label_set_sha256=canonical_label_set_sha256(label_set),
                case_ids=[case.case_id for case in label_set.cases],
            )
            for label_set in label_sets
        ],
        per_check=per_check,
        micro=TrajectoryMicroMetrics(
            true_positive=total_tp,
            false_positive=total_fp,
            false_negative=total_fn,
            precision=_rate(total_tp, total_tp + total_fp),
            recall=_rate(total_tp, total_tp + total_fn),
        ),
        macro=TrajectoryMacroMetrics(
            precision=(
                sum(defined_precision) / len(defined_precision) if defined_precision else None
            ),
            recall=(sum(defined_recall) / len(defined_recall) if defined_recall else None),
            precision_checks=len(defined_precision),
            recall_checks=len(defined_recall),
        ),
        exact_match=TrajectoryExactMatch(
            eligible_cases=eligible_cases,
            exact_cases=exact_cases,
            rate=_rate(exact_cases, eligible_cases),
        ),
        eligibility=TrajectoryEligibility(
            independent=independent,
            quality_eligible=quality_eligible,
            advisory=advisory,
            reason=reason,
            provenance_counts=dict(sorted(provenance_counts.items())),
            per_check={
                rule_id: TrajectoryLabelCounts(
                    positive=label_counts[rule_id]["positive"],
                    negative=label_counts[rule_id]["negative"],
                    unknown=label_counts[rule_id]["unknown"],
                    scored=label_counts[rule_id]["scored"],
                    independent=label_counts[rule_id]["independent"],
                )
                for rule_id in _RULE_IDS
            },
        ),
        cases=case_scores,
        disagreements=disagreements,
    )


__all__ = [
    "DEFAULT_TRAJECTORY_PROTOCOL_PATH",
    "TRAJECTORY_LABEL_SCHEMA_VERSION",
    "TRAJECTORY_PROTOCOL_SCHEMA_VERSION",
    "TRAJECTORY_SCORER_VERSION",
    "TrajectoryCaseScore",
    "TrajectoryCheckLabel",
    "TrajectoryComparisonResult",
    "TrajectoryDisagreement",
    "TrajectoryEligibility",
    "TrajectoryExactMatch",
    "TrajectoryLabelCase",
    "TrajectoryLabelCounts",
    "TrajectoryLabelProvenance",
    "TrajectoryLabelSet",
    "TrajectoryLabelSetReference",
    "TrajectoryMacroMetrics",
    "TrajectoryMicroMetrics",
    "TrajectoryProtocol",
    "TrajectoryRuleMetrics",
    "TrajectoryScoreReport",
    "TrajectorySplit",
    "TrajectoryTruth",
    "canonical_label_set_sha256",
    "canonical_trajectory_sha256",
    "compare_trajectory_report",
    "load_trajectory_label_sets",
    "load_trajectory_protocol",
    "score_trajectory_labels",
    "validate_label_sets",
]
