"""Loguru configuration for local + GitHub Actions environments."""

from __future__ import annotations

import os
import sys
from typing import Any

from loguru import logger

_CONFIGURED = False
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


def configure_logging(*, force: bool = False) -> None:
    """Configure loguru sinks from ``LOG_LEVEL`` / ``ACTIONS_STEP_DEBUG``.

    Opt into JSON via ``MERGECRAFT_LOG_FORMAT=json`` (or ``LOG_FORMAT=json``).
    Idempotent unless ``force=True``.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    level = resolve_log_level()
    log_format = resolve_log_format()
    logger.remove()
    logger.configure(patcher=_patch_bound_context)  # type: ignore[arg-type]

    if log_format == "json":
        logger.add(
            sys.stderr,
            level=level,
            serialize=True,
            enqueue=False,
            backtrace=level == "DEBUG",
            diagnose=False,
        )
    else:
        logger.add(
            sys.stderr,
            level=level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
                if level == "DEBUG"
                else "<level>{message}</level>"
            ),
            enqueue=False,
            backtrace=level == "DEBUG",
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
