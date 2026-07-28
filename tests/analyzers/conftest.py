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
