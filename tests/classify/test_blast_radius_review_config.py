"""Config that governs the review itself can never land in the ``eligible`` lane (#942)."""

from __future__ import annotations

import pytest

from mergecraft.classify import classify_blast_radius


def _classify(paths: list[str]):
    return classify_blast_radius(
        {"changed_paths": paths, "diff_stats": {"lines_added": 1, "lines_deleted": 0}}
    )


@pytest.mark.parametrize(
    "path",
    [
        ".mergecraft/config.yaml",
        ".mergecraft/rules/extra.yaml",
        "ruff.toml",
        ".ruff.toml",
        ".eslintrc.json",
        "eslint.config.js",
        ".golangci.yml",
        ".rubocop.yml",
        ".semgrepignore",
        ".gitleaks.toml",
        ".gitleaksignore",
        ".bandit",
        "setup.cfg",
        "tsconfig.json",
        ".pre-commit-config.yaml",
    ],
)
def test_review_governing_config_is_never_auto_merge_eligible(path: str) -> None:
    result = _classify([path])

    assert result.auto_merge_lane != "eligible"
    assert "review_config" in result.categories


def test_learnings_and_feedback_state_do_not_count_as_config() -> None:
    result = _classify([".mergecraft/learnings.md"])

    assert "review_config" not in result.categories


def test_ordinary_source_edit_is_unchanged() -> None:
    assert "review_config" not in _classify(["README.md"]).categories
