"""Tests for loguru configuration + W12.6 structured-log helpers."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from mergecraft.utils import log as log_mod
from mergecraft.utils.log import (
    bind_run_context,
    clear_run_context,
    configure_logging,
    is_debug_enabled,
    resolve_log_format,
    resolve_log_level,
)


@pytest.fixture(autouse=True)
def _reset_run_context() -> Iterator[None]:
    clear_run_context()
    yield
    clear_run_context()


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


def test_resolve_log_format_defaults_to_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """W12.6 — unset format stays human-readable text."""
    monkeypatch.delenv("MERGECRAFT_LOG_FORMAT", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    assert resolve_log_format() == "text"


@pytest.mark.parametrize(
    ("env_name", "raw", "expected"),
    [
        ("MERGECRAFT_LOG_FORMAT", "json", "json"),
        ("MERGECRAFT_LOG_FORMAT", "JSON", "json"),
        ("LOG_FORMAT", "json", "json"),
        ("MERGECRAFT_LOG_FORMAT", "pretty", "text"),
        ("LOG_FORMAT", "text", "text"),
    ],
)
def test_resolve_log_format_from_env(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    raw: str,
    expected: str,
) -> None:
    """W12.6 — ``MERGECRAFT_LOG_FORMAT`` / ``LOG_FORMAT`` select json vs text."""
    monkeypatch.delenv("MERGECRAFT_LOG_FORMAT", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.setenv(env_name, raw)
    assert resolve_log_format() == expected


def test_bind_run_context_stores_correlation_fields() -> None:
    """W12.6 — ``bind_run_context`` writes run_id/repo/pr/phase into the bound map."""
    bind_run_context(run_id="run-1", repo="acme/demo", pr=42, phase="review")
    assert log_mod._BOUND_CONTEXT == {
        "run_id": "run-1",
        "repo": "acme/demo",
        "pr": 42,
        "phase": "review",
    }


def test_bind_run_context_partial_update_preserves_prior_fields() -> None:
    """W12.6 — ``None`` args are omitted so phase can advance without clearing repo."""
    bind_run_context(run_id=7, repo="acme/demo", pr="9", phase="setup")
    bind_run_context(phase="agent")
    assert log_mod._BOUND_CONTEXT["run_id"] == "7"
    assert log_mod._BOUND_CONTEXT["repo"] == "acme/demo"
    assert log_mod._BOUND_CONTEXT["pr"] == "9"
    assert log_mod._BOUND_CONTEXT["phase"] == "agent"


def test_clear_run_context_resets_all_fields() -> None:
    """W12.6 — ``clear_run_context`` nulls every correlation field."""
    bind_run_context(run_id="x", repo="a/b", pr=1, phase="done")
    clear_run_context()
    assert all(value is None for value in log_mod._BOUND_CONTEXT.values())
