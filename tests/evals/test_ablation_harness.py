"""W10.1 — ablation harness (#384).

Dimensions: multi-agent vs single-agent, verifier, judge, context-engine,
analyzer, memory. Adversarial corpora are out of scope (separate issue).
Intended public API (W10.2): ``mergecraft.evals.ablation``.
"""

from __future__ import annotations

import pytest

_REQUIRED_DIMENSIONS = frozenset(
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


def test_ablation_dimensions_cover_issue_384() -> None:
    """Happy: the harness names every required ablation dimension."""
    from mergecraft.evals.ablation import ABLATION_DIMENSIONS

    names = {str(item).casefold() for item in ABLATION_DIMENSIONS}
    missing = {item for item in _REQUIRED_DIMENSIONS if item not in names}
    assert not missing, f"ablation harness missing dimensions: {sorted(missing)}"


def test_run_ablation_returns_per_dimension_delta() -> None:
    """Happy: running an ablation yields a per-dimension contribution report."""
    from mergecraft.evals.ablation import AblationConfig, run_ablation

    report = run_ablation(AblationConfig(dimensions=("verifier",), baseline="single_agent"))
    assert report is not None
    blob = str(report).casefold()
    assert "verifier" in blob


def test_run_ablation_unknown_dimension_raises() -> None:
    """Error: an unknown dimension raises ValueError naming ablation."""
    from mergecraft.evals.ablation import AblationConfig, run_ablation

    with pytest.raises(ValueError, match="ablation"):
        run_ablation(AblationConfig(dimensions=("not-a-dimension",), baseline="single_agent"))


def test_ablation_does_not_require_adversarial_corpus() -> None:
    """#384 out of scope: adversarial corpora are a separate issue."""
    from mergecraft.evals.ablation import ABLATION_DIMENSIONS

    names = {str(item).casefold() for item in ABLATION_DIMENSIONS}
    assert "adversarial" not in names
