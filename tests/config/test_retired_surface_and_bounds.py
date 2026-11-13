"""Retired preview settings and effective runtime bounds."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from mergecraft.config.settings import RepoSettings


@pytest.mark.parametrize(
    ("key", "value"),
    [
        pytest.param("autoMergeEnabled", False, id="old-scaffold-auto-merge"),
        pytest.param("auto_merge_enabled", True, id="python-auto-merge-alias"),
        pytest.param("operatorPipeline", "preview.yaml", id="operator-preview"),
        pytest.param("pipeline", "preview.yaml", id="repo-preview"),
        pytest.param("orchestrator", "deterministic", id="preview-orchestrator"),
    ],
)
def test_retired_settings_load_without_surviving_serialization(key: str, value: Any) -> None:
    settings = RepoSettings.model_validate({key: value})
    assert key not in settings.model_dump(by_alias=True)
    assert key not in settings.model_dump()
    assert key not in RepoSettings.model_json_schema()["properties"]


@pytest.mark.parametrize(
    "config",
    [
        pytest.param({"review": {"roundBudgets": {"multipliers": []}}}, id="empty-rounds"),
        pytest.param({"review": {"roundBudgets": {"multipliers": [0]}}}, id="zero-round"),
        pytest.param({"review": {"roundBudgets": {"multipliers": [-2]}}}, id="negative-round"),
        pytest.param({"review": {"roundBudgets": {"multipliers": [1e6]}}}, id="unbounded-round"),
        pytest.param({"review": {"instructionBundleByteCap": -1}}, id="negative-instructions"),
        pytest.param({"review": {"verificationBudget": -1}}, id="negative-verification"),
        pytest.param({"review": {"fileGroupFanout": {"minFiles": -1}}}, id="negative-files"),
        pytest.param({"review": {"fileGroupFanout": {"minDiffLines": -1}}}, id="negative-diff"),
        pytest.param({"jev": {"thresholds": {"unit/v1.likley": 0.2}}}, id="threshold-typo"),
        pytest.param({"jev": {"thresholds": {"unit/v1.certain": 5}}}, id="threshold-range"),
        pytest.param(
            {"jev": {"thresholds": {"unit/v1.certain": float("nan")}}}, id="threshold-nan"
        ),
        pytest.param({"jev": {"thresholds": {"unit/v1.certain": 0.4}}}, id="inverted-floors"),
    ],
)
def test_invalid_effective_bounds_fail_closed(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RepoSettings.model_validate(config)


def test_unwired_alignment_overrides_are_discarded() -> None:
    settings = RepoSettings.model_validate(
        {"jev": {"thresholds": {"align/v1.same_defect": 0.2, "evidence/v1.relation": 0.8}}}
    )
    assert settings.jev.thresholds == {"evidence/v1.relation": 0.8}


def test_retirement_does_not_ignore_unknown_configuration() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RepoSettings.model_validate({"autoMergeEnabeld": True})
