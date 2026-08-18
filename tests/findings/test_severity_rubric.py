"""DG1 severity rubric — code-defined, not model-assigned (G2).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG1).
Implementation: **DG1.2** — rubric applied at the ``JudgeVerdict`` seam in
``agents/verifier.py``.
"""

from __future__ import annotations

from mergecraft.agents.gates import BLOCKING_SEVERITIES
from tests.findings.support import make_finding


def test_blocking_severities_unchanged() -> None:
    """Regression pin — ``BLOCKING_SEVERITIES`` stays ``Critical`` + ``Major`` only."""
    assert frozenset({"Critical", "Major"}) == BLOCKING_SEVERITIES


def test_rubric_normalizes_model_assigned_severity() -> None:
    """Inflated model severity is normalized by the code-defined rubric."""
    from mergecraft.findings.severity_rubric import apply_severity_rubric

    finding = make_finding(
        category="Maintainability & Code Quality",
        severity="Critical",
        message="Prefer f-string over percent formatting",
        path="src/util.py",
        start_line=3,
        end_line=3,
    )

    normalized = apply_severity_rubric(finding, model_assigned_severity="Critical")

    assert normalized.severity not in BLOCKING_SEVERITIES
    assert normalized.severity in {"Minor", "Trivial"}


def test_rubric_is_code_defined_not_model_defined() -> None:
    """The rubric is a code artifact — not delegated to the reviewing model."""
    from mergecraft.findings import severity_rubric

    assert hasattr(severity_rubric, "SEVERITY_RUBRIC")
    rubric = severity_rubric.SEVERITY_RUBRIC
    assert isinstance(rubric, (tuple, list, dict))
    assert len(rubric) > 0
    # Rubric rules must be inspectable Python data, not prompt prose.
    assert not isinstance(rubric, str)
