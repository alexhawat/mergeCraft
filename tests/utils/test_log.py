"""Tests for loguru configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.utils.log import configure_logging, is_debug_enabled, resolve_log_level

if TYPE_CHECKING:
    import pytest


def test_resolve_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("ACTIONS_STEP_DEBUG", raising=False)
    assert resolve_log_level() == "INFO"
    monkeypatch.setenv("LOG_LEVEL", "warning")
    assert resolve_log_level() == "WARNING"
    monkeypatch.setenv("ACTIONS_STEP_DEBUG", "true")
    assert resolve_log_level() == "DEBUG"
    assert is_debug_enabled() is True
    configure_logging(force=True)
