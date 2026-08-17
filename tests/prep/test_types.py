"""Prep types / phase smoke tests (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.prep import PrepOptions, PrepResult, is_prep_install_failure, run_prep_phase
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
    assert result.skipped is False


def test_prep_result_skipped_defaults_false() -> None:
    result = PrepResult(language="python", dependencies_installed=False)
    assert result.skipped is False
    assert result.issues == []


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            PrepResult(
                language="python",
                dependencies_installed=False,
                skipped=True,
                issues=[
                    "skipped: python dependency installation can execute arbitrary code "
                    "(setup.py, build backends, local path references), which is blocked "
                    "when shell is disabled"
                ],
            ),
            False,
        ),
        (
            PrepResult(
                language="python",
                dependencies_installed=False,
                skipped=False,
                issues=["pip install -r requirements.txt failed (exit 1)"],
            ),
            True,
        ),
        (
            PrepResult(
                language="python",
                dependencies_installed=True,
                package_manager="uv",
                issues=[],
            ),
            False,
        ),
        (
            PrepResult(
                language="python",
                dependencies_installed=False,
                skipped=True,
                issues=[],
            ),
            False,
        ),
        (
            PrepResult(
                language="python",
                dependencies_installed=True,
                skipped=False,
                issues=["stale warning"],
            ),
            False,
        ),
        (
            PrepResult(
                language="python",
                dependencies_installed=False,
                skipped=False,
                issues=[],
            ),
            False,
        ),
    ],
    ids=(
        "skipped_with_issues",
        "failed_install",
        "successful_install",
        "skipped_empty_issues",
        "installed_with_issues",
        "not_installed_empty_issues",
    ),
)
def test_is_prep_install_failure(result: PrepResult, expected: bool) -> None:
    """A policy skip is not an install failure even when ``issues`` describe it.

    Deleting the ``skipped`` short-circuit in ``is_prep_install_failure``
    must fail ``skipped_with_issues`` (the live Action bug: skip text in
    ``issues`` was treated as ``status="failed"``).
    """
    assert is_prep_install_failure(result) is expected


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
