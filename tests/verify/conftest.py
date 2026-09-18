"""Isolate verify tests from ambient GitHub Actions event env."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_github_event_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests are local unless they set the Actions event themselves."""
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
