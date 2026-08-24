"""Per-lens routing precision/recall capability metrics (#455, CE).

Additive eval metrics for labeled routing cases: compare expected lens sets
against observed selections and emit a diffable JSON report. Does not rebuild
the eval harness — scores labeled diffs only.

Exports:
    LENS_CAPABILITY_SCHEMA_VERSION: Stable schema version string.
    LensRoutingCaseLabel: Ground-truth lenses for one labeled case.
    LensRoutingCaseOutcome: Observed lens selection for one case.
    PerLensRoutingMetrics: TP/FP/FN and precision/recall for one lens.
    LensRoutingCapabilityReport: Corpus-wide routing capability report.
    score_lens_routing: Score labels against outcomes.
    render_lens_capability_json: Canonical compact JSON for stable diffs.
    lens_capability_digest: SHA-256 digest over canonical JSON.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

LENS_CAPABILITY_SCHEMA_VERSION: Final[str] = "1.0.0"


class LensRoutingCaseLabel(BaseModel):
    """Ground-truth lenses that should fire for one labeled routing case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    expected_lens_ids: tuple[str, ...] = Field(default_factory=tuple)


class LensRoutingCaseOutcome(BaseModel):
    """Observed lens selection for one routing case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    selected_lens_ids: tuple[str, ...] = Field(default_factory=tuple)


class PerLensRoutingMetrics(BaseModel):
    """Per-lens routing precision/recall rolled up across labeled cases."""

    model_config = ConfigDict(extra="forbid")

    lens_id: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    precision: float | None = None
    recall: float | None = None


class LensRoutingCapabilityReport(BaseModel):
    """Corpus-wide per-lens routing capability numbers."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = LENS_CAPABILITY_SCHEMA_VERSION
    cases: int = 0
    by_lens: dict[str, PerLensRoutingMetrics] = Field(default_factory=dict)
    macro_precision: float = 0.0
    macro_recall: float = 0.0
    macro_f1: float = 0.0


def _precision(tp: int, fp: int) -> float | None:
    denom = tp + fp
    if denom == 0:
        return None
    return tp / denom


def _recall(tp: int, fn: int) -> float | None:
    denom = tp + fn
    if denom == 0:
        return None
    return tp / denom


def _f1(precision: float | None, recall: float | None) -> float:
    if precision is None or recall is None:
        return 0.0
    if precision == 0.0 and recall == 0.0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _macro_average(values: list[float | None]) -> float:
    """Macro-average metric values over participating lenses only.

    ``None`` precision/recall (lens never selected or never expected) counts as
    0.0 so macro totals stay finite and match the CE routing capability tests.
    """
    if not values:
        return 0.0
    total = sum(0.0 if value is None else value for value in values)
    return total / len(values)


def score_lens_routing(
    labels: list[LensRoutingCaseLabel],
    outcomes: list[LensRoutingCaseOutcome],
) -> LensRoutingCapabilityReport:
    """Score labeled routing cases against observed lens selections."""
    label_ids = {label.case_id for label in labels}
    outcome_ids = {outcome.case_id for outcome in outcomes}
    if label_ids != outcome_ids:
        raise ValueError(
            f"case ids must align one-to-one: labels={sorted(label_ids)} outcomes={sorted(outcome_ids)}"
        )

    label_by_id = {label.case_id: label for label in labels}
    outcome_by_id = {outcome.case_id: outcome for outcome in outcomes}

    true_positives: dict[str, int] = {}
    false_positives: dict[str, int] = {}
    false_negatives: dict[str, int] = {}

    for case_id in sorted(label_ids):
        expected = set(label_by_id[case_id].expected_lens_ids)
        selected = set(outcome_by_id[case_id].selected_lens_ids)
        participating = expected | selected

        for lens_id in participating:
            if lens_id in expected and lens_id in selected:
                true_positives[lens_id] = true_positives.get(lens_id, 0) + 1
            elif lens_id in selected:
                false_positives[lens_id] = false_positives.get(lens_id, 0) + 1
            else:
                false_negatives[lens_id] = false_negatives.get(lens_id, 0) + 1

    by_lens: dict[str, PerLensRoutingMetrics] = {}
    macro_precisions: list[float | None] = []
    macro_recalls: list[float | None] = []
    macro_f1s: list[float] = []

    for lens_id in sorted(true_positives.keys() | false_positives.keys() | false_negatives.keys()):
        tp = true_positives.get(lens_id, 0)
        fp = false_positives.get(lens_id, 0)
        fn = false_negatives.get(lens_id, 0)
        precision = _precision(tp, fp)
        recall = _recall(tp, fn)
        metrics = PerLensRoutingMetrics(
            lens_id=lens_id,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            precision=precision,
            recall=recall,
        )
        by_lens[lens_id] = metrics
        macro_precisions.append(precision)
        macro_recalls.append(recall)
        macro_f1s.append(_f1(precision, recall))

    return LensRoutingCapabilityReport(
        cases=len(label_ids),
        by_lens=by_lens,
        macro_precision=_macro_average(macro_precisions),
        macro_recall=_macro_average(macro_recalls),
        macro_f1=sum(macro_f1s) / len(macro_f1s) if macro_f1s else 0.0,
    )


def render_lens_capability_json(report: LensRoutingCapabilityReport) -> str:
    """Render a routing capability report as canonical compact JSON."""
    payload = report.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def lens_capability_digest(report: LensRoutingCapabilityReport) -> str:
    """Return a SHA-256 digest over the canonical JSON representation."""
    canonical = render_lens_capability_json(report)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "LENS_CAPABILITY_SCHEMA_VERSION",
    "LensRoutingCapabilityReport",
    "LensRoutingCaseLabel",
    "LensRoutingCaseOutcome",
    "PerLensRoutingMetrics",
    "lens_capability_digest",
    "render_lens_capability_json",
    "score_lens_routing",
]
