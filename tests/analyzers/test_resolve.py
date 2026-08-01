"""Execution-mode resolution preference chain (D4, D5)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tests.analyzers.support import import_module

if TYPE_CHECKING:
    import pytest


def test_preference_order_repo_native_before_managed(fixture_repo: Path) -> None:
    resolve = import_module("mergecraft.analyzers.resolve")
    manifest = import_module("mergecraft.analyzers.manifest")
    raw = (Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml")).read_text(
        encoding="utf-8"
    )
    m = manifest.load_manifest_yaml(raw.replace("runtime: managed", "runtime: repo-native"))
    plan = resolve.resolve_analyzer(
        manifest=m,
        repo_root=fixture_repo,
        repo_has_tool=True,
        ci_artifact_available=False,
        managed_available=True,
        container_available=True,
    )
    assert plan.mode == "repo-native"


def test_ci_result_preferred_over_managed_when_repo_lacks_tool(fixture_repo: Path) -> None:
    resolve = import_module("mergecraft.analyzers.resolve")
    manifest = import_module("mergecraft.analyzers.manifest")
    m = manifest.load_manifest_file(
        Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml")
    )
    plan = resolve.resolve_analyzer(
        manifest=m,
        repo_root=fixture_repo,
        repo_has_tool=False,
        ci_artifact_available=True,
        managed_available=True,
        container_available=True,
    )
    assert plan.mode == "ci-result"


def test_skip_records_human_readable_reason(fixture_repo: Path) -> None:
    resolve = import_module("mergecraft.analyzers.resolve")
    manifest = import_module("mergecraft.analyzers.manifest")
    m = manifest.load_manifest_file(
        Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml")
    )
    skipped = resolve.resolve_analyzer(
        manifest=m,
        repo_root=fixture_repo,
        repo_has_tool=False,
        ci_artifact_available=False,
        managed_available=False,
        container_available=False,
    )
    assert skipped.mode == "skip"
    assert skipped.reason
    assert "skip" in skipped.reason.lower() or "unavailable" in skipped.reason.lower()


def test_repo_installed_tool_never_substituted(
    fixture_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolve = import_module("mergecraft.analyzers.resolve")
    manifest = import_module("mergecraft.analyzers.manifest")
    m = manifest.load_manifest_yaml(
        (Path("tests/analyzers/fixtures/manifests/invalid-unmapped-severity.yaml"))
        .read_text(encoding="utf-8")
        .replace("runtime: repo-native", "runtime: managed")
    )
    plan = resolve.resolve_analyzer(
        manifest=m,
        repo_root=fixture_repo,
        repo_has_tool=True,
        repo_tool_path="/usr/local/bin/ruff",
        repo_tool_version="0.14.0",
        managed_available=True,
        managed_version="0.15.12",
    )
    assert plan.mode == "repo-native"
    assert plan.version_note is not None
    assert "0.14.0" in plan.version_note
    assert "0.15.12" not in plan.argv[0]
