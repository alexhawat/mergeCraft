"""Prep types / phase smoke tests (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.prep import PrepOptions, PrepResult, run_prep_phase
from mergecraft.prep.types import NodePackageManager, PythonPackageManager


def test_prep_options_defaults() -> None:
    opts = PrepOptions()
    assert opts.ignore_scripts is False
    assert opts.bin_dir == ""


def test_prep_result_shape() -> None:
    result = PrepResult(
        language="node",
        dependencies_installed=True,
        package_manager="npm",
        issues=[],
    )
    assert result.language == "node"
    assert result.dependencies_installed is True
    assert result.package_manager == "npm"


def test_package_manager_literals() -> None:
    node: NodePackageManager = "pnpm"
    py: PythonPackageManager = "uv"
    assert node == "pnpm"
    assert py == "uv"


@pytest.mark.asyncio
async def test_run_prep_phase_empty_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    # no package.json / python configs → empty results (or skipped)
    results = await run_prep_phase(PrepOptions(ignore_scripts=True))
    assert isinstance(results, list)
    assert all(isinstance(r, PrepResult) for r in results)
