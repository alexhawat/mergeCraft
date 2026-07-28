"""Loguru configuration for local + GitHub Actions environments."""

from __future__ import annotations

import os
import sys

from loguru import logger

_CONFIGURED = False


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


def configure_logging(*, force: bool = False) -> None:
    """Configure loguru sinks from ``LOG_LEVEL`` / ``ACTIONS_STEP_DEBUG``.

    Idempotent unless ``force=True``.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    level = resolve_log_level()
    logger.remove()
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
    "configure_logging",
    "is_debug_enabled",
    "logger",
    "resolve_log_level",
]
