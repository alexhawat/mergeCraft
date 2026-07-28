"""Analyzer registry detection and exclusive-group resolution (D1, D13)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import import_module

pytestmark = pytest.mark.xfail(reason="green after W2: registry detection", strict=False)


def test_detect_files_globs_enable_analyzer(fixture_repo: Path) -> None:
    registry = import_module("mergecraft.analyzers.registry")
    changed = [".github/workflows/broken.yml"]
    enabled = registry.detect_enabled(
        repo_root=fixture_repo,
        changed_files=changed,
        settings_overrides={},
    )
    ids = {m.id for m in enabled}
    assert "actionlint" in ids


def test_detect_respects_default_disabled_when_no_matching_files(fixture_repo: Path) -> None:
    registry = import_module("mergecraft.analyzers.registry")
    enabled = registry.detect_enabled(
        repo_root=fixture_repo,
        changed_files=["README.md"],
        settings_overrides={},
    )
    assert all(m.id not in {"actionlint", "shellcheck", "hadolint"} for m in enabled)


def test_default_enabled_auto_respects_repo_config_override(fixture_repo: Path) -> None:
    registry = import_module("mergecraft.analyzers.registry")
    enabled = registry.detect_enabled(
        repo_root=fixture_repo,
        changed_files=["Dockerfile"],
        settings_overrides={
            "analyzers": {"enabled": False, "overrides": {"hadolint": {"enabled": True}}}
        },
    )
    ids = {m.id for m in enabled}
    assert ids == {"hadolint"}


def test_exclusive_group_never_both_enable_by_default(fixture_repo: Path) -> None:
    registry = import_module("mergecraft.analyzers.registry")
    changed = ["src/example.py", "src/other.py"]
    enabled = registry.detect_enabled(
        repo_root=fixture_repo,
        changed_files=changed,
        settings_overrides={},
    )
    by_group: dict[str, list[str]] = {}
    for manifest in enabled:
        group = manifest.exclusive_group
        if group:
            by_group.setdefault(group, []).append(manifest.id)
    for group, ids in by_group.items():
        assert len(ids) <= 1, f"group {group} enabled multiple defaults: {ids}"


def test_explicit_override_wins_over_exclusive_group(fixture_repo: Path) -> None:
    registry = import_module("mergecraft.analyzers.registry")
    overrides = {
        "analyzers": {
            "overrides": {
                "ruff": {"enabled": True},
                "pylint": {"enabled": True},
            }
        }
    }
    enabled = registry.detect_enabled(
        repo_root=fixture_repo,
        changed_files=["src/example.py"],
        settings_overrides=overrides,
    )
    ids = {m.id for m in enabled}
    assert "ruff" in ids
    assert "pylint" in ids
