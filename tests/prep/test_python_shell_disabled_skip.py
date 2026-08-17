"""Python prep skip under ``shell: disabled`` / ``ignore_scripts`` is not a failure."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.prep.python import InstallPythonDependencies
from mergecraft.prep.types import PrepOptions, PrepResult, is_prep_install_failure

_SKIP_ISSUE = (
    "skipped: python dependency installation can execute arbitrary code "
    "(setup.py, build backends, local path references), which is blocked "
    "when shell is disabled"
)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            PrepResult(
                language="python",
                dependencies_installed=False,
                skipped=True,
                issues=[_SKIP_ISSUE],
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
                package_manager="uv",
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
        (
            PrepResult(
                language="python",
                dependencies_installed=False,
                skipped=False,
                issues=["pip install -r requirements.txt failed (exit 1)"],
            ),
            True,
        ),
    ],
    ids=(
        "skipped_with_skip_message",
        "skipped_empty_issues",
        "installed_clean",
        "installed_with_issues",
        "not_installed_empty_issues",
        "genuine_install_failure",
    ),
)
def test_is_prep_install_failure(result: PrepResult, expected: bool) -> None:
    """Policy skip is never an install failure; only a real failed install is.

    Deleting the ``result.skipped`` short-circuit in ``is_prep_install_failure``
    must fail ``skipped_with_skip_message`` — that was the live bug: skip text
    in ``issues`` was treated as ``status="failed"``.
    """
    assert is_prep_install_failure(result) is expected


@pytest.mark.asyncio
async def test_install_python_dependencies_skips_when_ignore_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``uv.lock`` + ``ignore_scripts=True`` is a policy skip, not a failed install."""
    (tmp_path / "uv.lock").write_text("# test lockfile\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = await InstallPythonDependencies().run(PrepOptions(ignore_scripts=True))

    assert result.skipped is True
    assert result.dependencies_installed is False
    assert result.language == "python"
    assert result.package_manager == "uv"
    assert result.config_file == "uv.lock"
    assert result.issues == [_SKIP_ISSUE]
    assert is_prep_install_failure(result) is False
