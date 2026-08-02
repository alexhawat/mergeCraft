"""Pytest fixtures for analyzer platform tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.analyzers.support import (
    FIXTURE_REPO,
    FORK_PULL_REQUEST_EVENT,
    SAME_REPO_PULL_REQUEST_EVENT,
)


@pytest.fixture
def fixture_repo() -> Path:
    return FIXTURE_REPO


@pytest.fixture
def same_repo_event() -> dict[str, Any]:
    return SAME_REPO_PULL_REQUEST_EVENT.copy()


@pytest.fixture
def fork_pr_event() -> dict[str, Any]:
    return FORK_PULL_REQUEST_EVENT.copy()


def _ignore_analyzer_cache(_dir: str, names: list[str]) -> set[str]:
    if Path(_dir).name == ".mergecraft":
        return {"analyzer-cache"}
    return set()


@pytest.fixture
def adapter_fixture_repo(fixture_repo: Path, tmp_path: Path) -> Path:
    """Isolated copy of the W0.8 fixture so parallel workers do not share analyzer cache."""
    import shutil

    dest = tmp_path / "fixture-repo"
    shutil.copytree(fixture_repo, dest, ignore=_ignore_analyzer_cache)
    return dest
