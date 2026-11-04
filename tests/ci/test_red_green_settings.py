"""Config surface for fail-then-pass receipts (#1056 part 5).

``ciEvidence.redGreenArtifacts`` names the receipt artifact (empty by default,
so an undeclared repository makes no extra API call); ``review.fixLabels``
names the labels that mark a pull request as a fix (default ``bug``, ``fix``).
Both are read from the operator-owned settings like the other ``ciEvidence``
names. Sibling of ``test_coverage_mutation_settings.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from mergecraft.config.settings import (
    CiEvidenceSettings,
    ReviewSettings,
    default_settings,
    load_repo_settings,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_config(tmp_path: Path, body: str) -> None:
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir()
    config.write_text("push: restricted\nshell: restricted\n" + body, encoding="utf-8")


def test_red_green_artifacts_default_empty_beside_the_other_ci_evidence_names() -> None:
    settings = default_settings()

    assert settings.ci_evidence.red_green_artifacts == []
    assert settings.ci_evidence.coverage_artifacts == []


def test_fix_labels_default_to_bug_and_fix() -> None:
    assert default_settings().review.fix_labels == ["bug", "fix"]


def test_a_missing_config_file_keeps_both_defaults(tmp_path: Path) -> None:
    settings = load_repo_settings(tmp_path / "missing.yaml", load_learnings_files=False)

    assert settings.ci_evidence.red_green_artifacts == []
    assert settings.review.fix_labels == ["bug", "fix"]


def test_consumer_yaml_declares_the_receipt_artifact_and_fix_labels(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "ciEvidence:\n"
        "  redGreenArtifacts:\n"
        "    - red-green-receipt\n"
        "review:\n"
        "  fixLabels:\n"
        "    - regression\n"
        "    - hotfix\n",
    )

    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)

    assert settings.ci_evidence.red_green_artifacts == ["red-green-receipt"]
    assert settings.review.fix_labels == ["regression", "hotfix"]


def test_an_empty_fix_labels_list_is_kept_empty(tmp_path: Path) -> None:
    _write_config(tmp_path, "review:\n  fixLabels: []\n")

    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)

    assert settings.review.fix_labels == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"redGreenArtifacts": ["receipt"]}, ["receipt"]),
        ({"red_green_artifacts": ["receipt"]}, ["receipt"]),
    ],
    ids=["alias", "field-name"],
)
def test_ci_evidence_accepts_the_alias_and_the_field_name(
    payload: dict[str, object], expected: list[str]
) -> None:
    assert CiEvidenceSettings.model_validate(payload).red_green_artifacts == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"fixLabels": ["regression"]}, ["regression"]),
        ({"fix_labels": ["regression"]}, ["regression"]),
    ],
    ids=["alias", "field-name"],
)
def test_review_accepts_the_alias_and_the_field_name(
    payload: dict[str, object], expected: list[str]
) -> None:
    assert ReviewSettings.model_validate(payload).fix_labels == expected


def test_the_aliases_round_trip_by_alias() -> None:
    ci = CiEvidenceSettings.model_validate({"redGreenArtifacts": ["receipt"]})
    review = ReviewSettings.model_validate({"fixLabels": ["regression"]})

    assert ci.model_dump(by_alias=True)["redGreenArtifacts"] == ["receipt"]
    assert review.model_dump(by_alias=True)["fixLabels"] == ["regression"]


def test_a_string_instead_of_a_list_is_refused_at_the_alias() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CiEvidenceSettings.model_validate({"redGreenArtifacts": "red-green-receipt"})

    errors = excinfo.value.errors()
    assert [error["loc"] for error in errors] == [("redGreenArtifacts",)]
    assert errors[0]["type"] == "list_type"


def test_a_non_string_fix_label_is_refused_at_the_alias() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ReviewSettings.model_validate({"fixLabels": [{"name": "bug"}]})

    errors = excinfo.value.errors()
    assert [error["loc"] for error in errors] == [("fixLabels", 0)]
    assert errors[0]["type"] == "string_type"


def test_ci_evidence_still_refuses_an_unknown_key() -> None:
    """The new key does not loosen ``extra="forbid"``: a misspelling still fails."""
    assert CiEvidenceSettings.model_validate({"redGreenArtifacts": []}).red_green_artifacts == []
    with pytest.raises(ValidationError) as excinfo:
        CiEvidenceSettings.model_validate({"redGreenArtifact": ["receipt"]})

    assert excinfo.value.errors()[0]["type"] == "extra_forbidden"
