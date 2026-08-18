"""DG2 split advisor — advisory PR split recommendations (G6, convention 3).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG2).
Implementation: **DG2.2** — consume change clusters; output text only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def _independent_groups() -> list[dict[str, Any]]:
    return [
        {
            "id": "ui",
            "paths": ["frontend/app.tsx", "frontend/router.tsx"],
            "intent": "ui-refactor",
        },
        {
            "id": "infra",
            "paths": ["infra/terraform/main.tf", "infra/terraform/variables.tf"],
            "intent": "infra",
        },
    ]


def _recommend_split(groups: list[dict[str, Any]], **kwargs: Any) -> Any:
    from mergecraft.review.split_advisor import recommend_pr_split

    return recommend_pr_split(groups, **kwargs)


@pytest.mark.xfail(reason="green after DG2.2", strict=False)
def test_unrelated_groups_produce_a_split_recommendation() -> None:
    """Independent clusters yield a concrete split recommendation."""
    advice = _recommend_split(_independent_groups())

    assert advice.recommend_split is True
    assert len(advice.suggested_prs) >= 2
    suggested_paths = {path for pr in advice.suggested_prs for path in pr.paths}
    assert "frontend/app.tsx" in suggested_paths
    assert "infra/terraform/main.tf" in suggested_paths
    assert advice.summary.strip()


@pytest.mark.xfail(reason="green after DG2.2", strict=False)
def test_split_advice_is_advisory_only(tmp_path: Path) -> None:
    """Split advice is text-only — convention 3 forbids repo writes."""
    target = tmp_path / "would-be-split-plan.md"
    advice = _recommend_split(_independent_groups(), output_path=target)

    assert advice.advisory_only is True
    assert not target.exists(), "split advice must not write to the reviewed tree"
    assert isinstance(advice.summary, str)
    assert advice.summary.strip()
