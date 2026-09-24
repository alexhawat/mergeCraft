"""Tests for loguru configuration + W12.6 structured-log helpers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from mergecraft.analyzers.redact import install_loguru_redaction_filter
from mergecraft.utils import log as log_mod
from mergecraft.utils.log import (
    bind_run_context,
    clear_run_context,
    is_debug_enabled,
    resolve_log_format,
    resolve_log_level,
)

_CANARY = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890"


@pytest.fixture(autouse=True)
def _reset_run_context() -> Iterator[None]:
    clear_run_context()
    yield
    clear_run_context()


@pytest.fixture(autouse=True)
def _restore_log_patcher() -> Iterator[None]:
    """Leave the process-wide loguru patcher as the tests found it.

    The patcher and the message-redactor slot are process-global; a test that
    installs one must restore both so later tests in the same process are not
    affected.
    """
    yield
    setter = getattr(log_mod, "set_message_redactor", None)
    if setter is not None:
        setter(None)
    log_mod.configure_logging(force=True)


def _capture_records() -> tuple[list[Any], int]:
    """Attach a local sink and return its collected records plus its handler id."""
    records: list[Any] = []
    sink_id = log_mod.logger.add(lambda message: records.append(message), level="TRACE")
    return records, sink_id


def _record_context_and_message(records: list[Any]) -> tuple[dict[str, Any], str]:
    assert records, "no log record reached the local sink"
    record = records[-1].record
    return dict(record["extra"]), str(record["message"])


def test_resolve_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("ACTIONS_STEP_DEBUG", raising=False)
    assert resolve_log_level() == "INFO"
    monkeypatch.setenv("LOG_LEVEL", "warning")
    assert resolve_log_level() == "WARNING"
    monkeypatch.setenv("ACTIONS_STEP_DEBUG", "true")
    assert resolve_log_level() == "DEBUG"
    assert is_debug_enabled() is True


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


def _assert_context_and_redaction(records: list[Any]) -> None:
    extra, message = _record_context_and_message(records)
    assert extra.get("run_id") == "run-42"
    assert extra.get("repo") == "acme/demo"
    assert extra.get("pr") == 7
    assert extra.get("phase") == "review"
    assert _CANARY not in message


@pytest.mark.xfail(reason="green after the composed-patcher wave lands", strict=False)
def test_configure_then_install_keeps_context_and_redaction() -> None:
    """A record keeps its bound correlation fields and loses the planted canary.

    The redaction patcher is installed after ``configure_logging``, which is the
    order the CLI root callback uses.
    """
    log_mod.configure_logging(force=True)
    install_loguru_redaction_filter()
    bind_run_context(run_id="run-42", repo="acme/demo", pr=7, phase="review")
    records, sink_id = _capture_records()
    try:
        log_mod.logger.warning("fetching with {}", _CANARY)
    finally:
        log_mod.logger.remove(sink_id)
    _assert_context_and_redaction(records)


@pytest.mark.xfail(reason="green after the composed-patcher wave lands", strict=False)
def test_install_then_configure_keeps_context_and_redaction() -> None:
    """Installing redaction first and reconfiguring after still keeps both.

    The install order must not decide whether a record loses its correlation
    fields or its redaction.
    """
    install_loguru_redaction_filter()
    log_mod.configure_logging(force=True)
    bind_run_context(run_id="run-42", repo="acme/demo", pr=7, phase="review")
    records, sink_id = _capture_records()
    try:
        log_mod.logger.warning("fetching with {}", _CANARY)
    finally:
        log_mod.logger.remove(sink_id)
    _assert_context_and_redaction(records)


@pytest.mark.xfail(reason="green after the composed-patcher wave lands", strict=False)
def test_repeated_configure_after_install_keeps_redaction() -> None:
    """A later ``configure_logging(force=True)`` must not drop the redactor."""
    install_loguru_redaction_filter()
    log_mod.configure_logging(force=True)
    log_mod.configure_logging(force=True)
    bind_run_context(run_id="run-42", repo="acme/demo", pr=7, phase="review")
    records, sink_id = _capture_records()
    try:
        log_mod.logger.warning("fetching with {}", _CANARY)
    finally:
        log_mod.logger.remove(sink_id)
    _assert_context_and_redaction(records)
