"""Ablation harness for specialist and pipeline contribution (#384).

Dimensions: multi-agent vs single-agent, verifier, judge, context-engine,
analyzer, memory. Adversarial corpora are out of scope (separate issue).

Analyzer contribution uses the **current** shipped catalog as its baseline
inventory (#339 closed and added analyzers; do not freeze a pre-sweep count).

This harness records per-dimension contribution versus a named baseline.
Pass paired scores on :class:`AblationConfig` (baseline plus each dimension)
to get ``measured=True`` deltas. Without scores, deltas stay ``0.0`` /
``measured=False`` — do not treat a zero as proof of no value.

Exports:
    ABLATION_DIMENSIONS: Required #384 ablation dimension names.
    AblationConfig: Which dimensions to run against which baseline.
    AblationContribution: One dimension's measured (or unmeasured) delta.
    AblationReport: Per-dimension contribution report.
    run_ablation: Execute the named dimensions against a baseline.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.analyzers.registry import load_catalog

__all__ = [
    "ABLATION_DIMENSIONS",
    "AblationConfig",
    "AblationContribution",
    "AblationReport",
    "run_ablation",
]

ABLATION_DIMENSIONS: Final[frozenset[str]] = frozenset(
    {
        "multi_agent",
        "single_agent",
        "verifier",
        "judge",
        "context_engine",
        "analyzer",
        "memory",
    }
)


class AblationConfig(BaseModel):
    """Which ablation dimensions to compare against a named baseline.

    ``scores`` maps a dimension (or the baseline name) to a comparable
    metric such as F1. When both the baseline and a dimension are present,
    :func:`run_ablation` records ``delta = score[dimension] - score[baseline]``
    with ``measured=True``.
    """

    model_config = ConfigDict(extra="forbid")

    dimensions: tuple[str, ...]
    baseline: str = "single_agent"
    scores: dict[str, float] | None = None


class AblationContribution(BaseModel):
    """One dimension's contribution relative to the configured baseline."""

    model_config = ConfigDict(extra="forbid")

    dimension: str
    delta: float
    measured: bool
    notes: str = ""


class AblationReport(BaseModel):
    """Per-dimension contribution report for one ablation run."""

    model_config = ConfigDict(extra="forbid")

    baseline: str
    contributions: tuple[AblationContribution, ...] = Field(default_factory=tuple)
    analyzer_catalog_size: int = 0

    def __str__(self) -> str:
        """Human-readable summary that names every requested dimension."""
        names = ", ".join(item.dimension for item in self.contributions) or "(none)"
        return (
            f"ablation report baseline={self.baseline} dimensions=[{names}] "
            f"analyzer_catalog_size={self.analyzer_catalog_size}"
        )


def _analyzer_catalog_size() -> int:
    """Count shipped analyzer manifests — the post-#339 ablation baseline."""
    return len(load_catalog())


def run_ablation(config: AblationConfig) -> AblationReport:
    """Return a per-dimension contribution report.

    Unknown dimension names raise ``ValueError``. When ``config.scores``
    includes both the baseline and a dimension, that row is measured;
    otherwise the row stays ``delta=0.0`` / ``measured=False``.

    Args:
        config: Dimensions to ablate, baseline name, and optional paired scores.

    Returns:
        An :class:`AblationReport` naming every requested dimension.

    Raises:
        ValueError: If a dimension is not in :data:`ABLATION_DIMENSIONS`.
    """
    unknown = [name for name in config.dimensions if name not in ABLATION_DIMENSIONS]
    if unknown:
        msg = f"unknown ablation dimension(s): {', '.join(unknown)}"
        raise ValueError(msg)
    catalog_size = _analyzer_catalog_size()
    scores = config.scores or {}
    baseline_score = scores.get(config.baseline)
    contributions: list[AblationContribution] = []
    for name in config.dimensions:
        if baseline_score is not None and name in scores:
            contributions.append(
                AblationContribution(
                    dimension=name,
                    delta=scores[name] - baseline_score,
                    measured=True,
                    notes="measured from paired scored runs",
                )
            )
            continue
        contributions.append(
            AblationContribution(
                dimension=name,
                delta=0.0,
                measured=False,
                notes=(
                    f"unmeasured; analyzer catalog baseline is {catalog_size} shipped "
                    "manifests (post-#339), not a frozen pre-sweep count"
                    if name == "analyzer"
                    else "unmeasured until paired scored runs record a delta"
                ),
            )
        )
    return AblationReport(
        baseline=config.baseline,
        contributions=tuple(contributions),
        analyzer_catalog_size=catalog_size,
    )
