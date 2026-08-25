"""Lens routing capability scoring for eval benchmark result sets (#455, CE)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from mergecraft.classify.change_classifier import classify_change
from mergecraft.classify.generated_files import ChangeSet  # noqa: TC001 — TypedDict wire shape
from mergecraft.config.settings import load_repo_settings
from mergecraft.evals.lens_capability import (
    LensRoutingCapabilityReport,
    LensRoutingCaseLabel,
    LensRoutingCaseOutcome,
    score_lens_routing,
)
from mergecraft.review.lens_routing import load_routing_registry, route_lenses

_RECALL_BASELINE_NAME: Final[str] = "ap5_routing_recall_baseline.json"
_EVALS_DIR: Final[Path] = Path(__file__).resolve().parent
_REPO_ROOT: Final[Path] = _EVALS_DIR.parents[2]


def _resolved_recall_baseline_path() -> Path:
    shipped = _EVALS_DIR / "fixtures" / _RECALL_BASELINE_NAME
    if shipped.is_file():
        return shipped
    checkout = _REPO_ROOT / "evals" / "fixtures" / _RECALL_BASELINE_NAME
    if checkout.is_file():
        return checkout
    msg = f"routing recall baseline fixture missing: {_RECALL_BASELINE_NAME}"
    raise FileNotFoundError(msg)


def score_routing_baseline_capability(
    *,
    repo_root: Path | None = None,
) -> LensRoutingCapabilityReport:
    """Score the frozen AP5 routing baseline without live provider calls."""
    baseline_path = _resolved_recall_baseline_path()
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    cases_raw = baseline["cases"]
    if not isinstance(cases_raw, list):
        msg = "routing recall baseline cases must be a list"
        raise TypeError(msg)

    root = repo_root if repo_root is not None else _REPO_ROOT
    settings = load_repo_settings(root=root)
    registry = load_routing_registry(settings=settings, repo_root=root)

    labels: list[LensRoutingCaseLabel] = []
    outcomes: list[LensRoutingCaseOutcome] = []
    for case in cases_raw:
        if not isinstance(case, dict):
            msg = "routing recall baseline case must be an object"
            raise TypeError(msg)
        case_id = str(case["id"])
        expected_raw = case.get("expected_lens_ids", [])
        if not isinstance(expected_raw, list):
            msg = f"expected_lens_ids must be a list for case {case_id}"
            raise TypeError(msg)
        expected = tuple(str(item) for item in expected_raw)
        labels.append(LensRoutingCaseLabel(case_id=case_id, expected_lens_ids=expected))

        change: ChangeSet = {
            "changed_paths": case["changed_paths"],
            "diff_stats": case["diff_stats"],
        }
        classification = classify_change(change)
        decision = route_lenses(classification, registry=registry)
        outcomes.append(
            LensRoutingCaseOutcome(
                case_id=case_id,
                selected_lens_ids=tuple(decision.selected_lens_ids),
            )
        )

    return score_lens_routing(labels, outcomes)


__all__ = ["score_routing_baseline_capability"]
