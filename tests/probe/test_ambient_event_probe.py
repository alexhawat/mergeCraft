"""F3 (#760) — child process used to prove the ambient-event guard, in isolation.

This module is run two ways:

* directly, as a normal test module, where the autouse guard in
  ``tests/conftest.py`` is expected to have cleared both variables; and
* from a subprocess by
  ``tests/test_conftest_ambient_event_guard.py`` with ``GITHUB_EVENT_NAME`` and
  ``GITHUB_EVENT_PATH`` deliberately exported, so the guard's contract is
  proven without depending on the ambient environment of whoever runs the
  suite.

It contains no product imports on purpose: it must observe ``os.environ``
exactly as the interpreter inherited it after fixtures ran.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_ambient_github_event_name_is_cleared() -> None:
    assert os.environ.get("GITHUB_EVENT_NAME") is None, (
        "tests/conftest.py must clear GITHUB_EVENT_NAME so a test cannot inherit "
        "the runner's event; opt in with monkeypatch.setenv"
    )


def test_ambient_github_event_path_is_cleared() -> None:
    assert os.environ.get("GITHUB_EVENT_PATH") is None, (
        "tests/conftest.py must clear GITHUB_EVENT_PATH so a test cannot inherit "
        "the runner's event payload; opt in with monkeypatch.setenv"
    )


def test_explicit_setenv_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test that wants an event must be able to opt back in after the guard."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", "/tmp/mergecraft-explicit-event.json")
    assert os.environ["GITHUB_EVENT_NAME"] == "pull_request"
    assert os.environ["GITHUB_EVENT_PATH"] == "/tmp/mergecraft-explicit-event.json"
