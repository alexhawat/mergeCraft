"""Release regression gate over benchmark result sets (EV3).

A candidate :class:`~mergecraft.evals.benchmark.BenchmarkResultSet` is
compared against the published baseline with a **declared tolerance band**:
a metric that regresses by more than the band fails the release, and noise
inside the band passes. The comparison is direction-aware — a *drop* in
``decision_replay_pass_rate`` regresses, while a *rise* in
``unsafe_approval_rate`` / ``clean_block_rate`` regresses, because those are
safety-opposite failure modes a single scalar cannot express (#140).

The release log must say *which* number moved, not just "failed", so
:attr:`GateReport.regressed_metrics` names every regressed metric and
:attr:`GateReport.deltas` carries the full baseline/candidate/delta ledger.

Gated metrics:

- Structural replay (always compared): ``decision_replay_pass_rate``
  (higher is better), ``unsafe_approval_rate`` and ``clean_block_rate``
  (lower is better).
- Live detection join (compared only when **both** result sets carry it —
  an absent half is skipped, never fabricated): ``detection.recall``,
  ``detection.corpus_confirmed_precision`` and ``detection.f1`` (all higher
  is better).

Pure core: no I/O except in :func:`load_result_set`, which the caller hands
an explicit path; no ``os.environ`` reads; nothing at import time (§W11.6).
The CLI shell is ``mergecraft eval gate --baseline … --candidate …``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict

from mergecraft.evals.benchmark import BenchmarkResultSet

if TYPE_CHECKING:
    from pathlib import Path

#: The declared tolerance band (EV3): wider than one-case noise on the
#: current corpus, far narrower than any material multi-case regression.
DEFAULT_GATE_TOLERANCE: Final[float] = 0.02

Direction = Literal["higher_is_better", "lower_is_better"]

#: Structural gate metrics — always compared.
_STRUCTURAL_GATE_METRICS: Final[tuple[tuple[str, Direction], ...]] = (
    ("decision_replay_pass_rate", "higher_is_better"),
    ("unsafe_approval_rate", "lower_is_better"),
    ("clean_block_rate", "lower_is_better"),
)

#: Detection-join gate metrics — compared only when both sides ran detection.
_DETECTION_GATE_METRICS: Final[tuple[tuple[str, Direction], ...]] = (
    ("recall", "higher_is_better"),
    ("corpus_confirmed_precision", "higher_is_better"),
    ("f1", "higher_is_better"),
)


class MetricDelta(BaseModel):
    """One gated metric's baseline → candidate movement."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    baseline: float
    candidate: float
    #: Signed movement (``candidate - baseline``) — negative is a drop.
    delta: float
    #: True when the movement is a regression beyond the tolerance band.
    regressed: bool


class GateReport(BaseModel):
    """Outcome of gating a candidate result set against the baseline."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    tolerance: float
    deltas: list[MetricDelta]
    #: Names of every metric that regressed beyond the band, in comparison
    #: order. Empty iff ``passed``.
    regressed_metrics: tuple[str, ...]


def _regressed(
    *, direction: Direction, baseline: float, candidate: float, tolerance: float
) -> bool:
    if direction == "higher_is_better":
        return baseline - candidate > tolerance
    return candidate - baseline > tolerance


def _compare(
    metric: str,
    direction: Direction,
    baseline: float,
    candidate: float,
    tolerance: float,
) -> MetricDelta:
    return MetricDelta(
        metric=metric,
        baseline=baseline,
        candidate=candidate,
        delta=candidate - baseline,
        regressed=_regressed(
            direction=direction, baseline=baseline, candidate=candidate, tolerance=tolerance
        ),
    )


def eval_gate(
    *,
    candidate: BenchmarkResultSet,
    baseline: BenchmarkResultSet,
    tolerance: float = DEFAULT_GATE_TOLERANCE,
) -> GateReport:
    """Compare two result sets' scalar gate metrics, direction-aware.

    Pure: the caller owns how the result sets were produced. A metric is
    regressed when it moves in its bad direction by strictly more than
    ``tolerance``; movement within the band is noise and passes.

    Raises:
        ValueError: ``tolerance`` is negative.
    """
    if tolerance < 0:
        msg = f"tolerance must be >= 0; got {tolerance}"
        raise ValueError(msg)

    deltas: list[MetricDelta] = []
    for metric, direction in _STRUCTURAL_GATE_METRICS:
        deltas.append(
            _compare(
                metric,
                direction,
                getattr(baseline.metrics, metric),
                getattr(candidate.metrics, metric),
                tolerance,
            )
        )

    if baseline.detection is not None and candidate.detection is not None:
        for metric, direction in _DETECTION_GATE_METRICS:
            deltas.append(
                _compare(
                    f"detection.{metric}",
                    direction,
                    getattr(baseline.detection.aggregate, metric),
                    getattr(candidate.detection.aggregate, metric),
                    tolerance,
                )
            )

    regressed = tuple(delta.metric for delta in deltas if delta.regressed)
    return GateReport(
        passed=not regressed,
        tolerance=tolerance,
        deltas=deltas,
        regressed_metrics=regressed,
    )


def load_result_set(path: Path) -> BenchmarkResultSet:
    """Load a :class:`BenchmarkResultSet` from a JSON file on disk."""
    return BenchmarkResultSet.model_validate(json.loads(path.read_text(encoding="utf-8")))


__all__ = [
    "DEFAULT_GATE_TOLERANCE",
    "Direction",
    "GateReport",
    "MetricDelta",
    "eval_gate",
    "load_result_set",
]
