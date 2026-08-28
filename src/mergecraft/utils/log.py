"""Loguru configuration for local + GitHub Actions environments."""

from __future__ import annotations

import os
import sys
from contextlib import suppress
from typing import Any

from loguru import logger

_CONFIGURED = False
_STDERR_HANDLER_ID: int | None = None
_BOUND_CONTEXT: dict[str, Any] = {
    "run_id": None,
    "repo": None,
    "pr": None,
    "phase": None,
}


def is_debug_enabled() -> bool:
    """True when ``LOG_LEVEL=debug`` or ``ACTIONS_STEP_DEBUG=true``."""
    level = (os.environ.get("LOG_LEVEL") or "").lower()
    if level == "debug":
        return True
    return os.environ.get("ACTIONS_STEP_DEBUG", "").lower() == "true"


def resolve_log_level() -> str:
    """Resolve the effective loguru level name from the environment."""
    if is_debug_enabled():
        return "DEBUG"
    raw = (os.environ.get("LOG_LEVEL") or "INFO").upper()
    allowed = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
    return raw if raw in allowed else "INFO"


def resolve_log_format() -> str:
    """Resolve log sink format: ``json`` (opt-in) or ``text`` (default).

    Honours ``MERGECRAFT_LOG_FORMAT`` then ``LOG_FORMAT``. Any value other than
    ``json`` (case-insensitive) keeps the human-readable text sink.
    """
    raw = (
        (os.environ.get("MERGECRAFT_LOG_FORMAT") or os.environ.get("LOG_FORMAT") or "text")
        .strip()
        .lower()
    )
    return "json" if raw == "json" else "text"


def bind_run_context(
    *,
    run_id: str | int | None = None,
    repo: str | None = None,
    pr: int | str | None = None,
    phase: str | None = None,
) -> None:
    """Bind correlation fields for subsequent log records (W12.6 / #33).

    No-op fields left as ``None`` are omitted from JSON records. Call again to
    update ``phase`` as the run advances. Works with both text and JSON sinks.
    """
    if run_id is not None:
        _BOUND_CONTEXT["run_id"] = str(run_id)
    if repo is not None:
        _BOUND_CONTEXT["repo"] = repo
    if pr is not None:
        _BOUND_CONTEXT["pr"] = pr
    if phase is not None:
        _BOUND_CONTEXT["phase"] = phase


def clear_run_context() -> None:
    """Reset bound correlation fields (tests / process teardown)."""
    for key in _BOUND_CONTEXT:
        _BOUND_CONTEXT[key] = None


def _patch_bound_context(record: dict[str, Any]) -> None:
    extra = record["extra"]
    for key, value in _BOUND_CONTEXT.items():
        if value is not None and key not in extra:
            extra[key] = value


def _remove_stderr_handler() -> None:
    global _STDERR_HANDLER_ID
    if _STDERR_HANDLER_ID is not None:
        with suppress(ValueError):
            logger.remove(_STDERR_HANDLER_ID)
        _STDERR_HANDLER_ID = None


def configure_logging(*, force: bool = False, level: str | None = None) -> None:
    """Configure loguru sinks from ``LOG_LEVEL`` / ``ACTIONS_STEP_DEBUG``.

    Opt into JSON via ``MERGECRAFT_LOG_FORMAT=json`` (or ``LOG_FORMAT=json``).
    Idempotent unless ``force=True``. Pass ``level`` to override env resolution
    (root ``--log-level`` / ``--quiet`` / ``--verbose`` / ``MERGECRAFT_LOG_LEVEL``).
    """
    global _CONFIGURED, _STDERR_HANDLER_ID
    if _CONFIGURED and not force:
        return

    effective_level = level if level is not None else resolve_log_level()
    log_format = resolve_log_format()
    if force:
        _remove_stderr_handler()
        if not _CONFIGURED:
            with suppress(ValueError):
                logger.remove(0)
    elif not _CONFIGURED:
        with suppress(ValueError):
            logger.remove(0)
    logger.configure(patcher=_patch_bound_context)  # type: ignore[arg-type]  # — loguru patcher stub is overly restrictive; _patch_bound_context(record) signature is compatible at runtime

    if log_format == "json":
        _STDERR_HANDLER_ID = logger.add(
            sys.stderr,
            level=effective_level,
            serialize=True,
            enqueue=False,
            backtrace=effective_level == "DEBUG",
            diagnose=False,
        )
    else:
        _STDERR_HANDLER_ID = logger.add(
            sys.stderr,
            level=effective_level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
                if effective_level == "DEBUG"
                else "<level>{message}</level>"
            ),
            enqueue=False,
            backtrace=effective_level == "DEBUG",
            diagnose=False,
        )
    _CONFIGURED = True


# Configure on import so ``from mergecraft.utils.log import logger`` just works.
configure_logging()

__all__ = [
    "bind_run_context",
    "clear_run_context",
    "configure_logging",
    "is_debug_enabled",
    "logger",
    "resolve_log_format",
    "resolve_log_level",
]
