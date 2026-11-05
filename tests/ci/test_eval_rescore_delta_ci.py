"""CI wiring for advisory eval rescore delta (#1164)."""

from __future__ import annotations

from pathlib import Path

from mergecraft.evals.rescore_delta import touches_reviewer_surface


def test_ci_workflow_mentions_eval_rescore_delta_job() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "eval-rescore-delta:" in text
    assert "ci_touches_reviewer_surface.py" in text


def test_reviewer_surface_helper_matches_modes_path() -> None:
    assert touches_reviewer_surface(["src/mergecraft/modes/Review.py"])
