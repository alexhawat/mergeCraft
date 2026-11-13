"""Shared utilities for the mergecraft runtime."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

# This function shares its submodule name. Bind it eagerly so importing the
# submodule first cannot replace the public callable with a module object.
from mergecraft.utils.normalize_env import normalize_env

if TYPE_CHECKING:
    from mergecraft.utils.github import GitHubClient, parse_repo_context, resolve_run_context_data
    from mergecraft.utils.log import configure_logging, logger
    from mergecraft.utils.payload import (
        JsonPayload,
        PayloadEvent,
        resolve_payload,
        resolve_prompt_input,
    )
    from mergecraft.utils.secrets import (
        filter_env,
        is_sensitive_env_name,
        sanitize_secret,
        set_env_allowlist,
    )
    from mergecraft.utils.time_parse import (
        TIMEOUT_DISABLED,
        parse_time_string,
        parse_timeout,
        resolve_timeout_ms,
    )

_EXPORT_MODULES = {
    "GitHubClient": "mergecraft.utils.github",
    "parse_repo_context": "mergecraft.utils.github",
    "resolve_run_context_data": "mergecraft.utils.github",
    "configure_logging": "mergecraft.utils.log",
    "logger": "mergecraft.utils.log",
    "JsonPayload": "mergecraft.utils.payload",
    "PayloadEvent": "mergecraft.utils.payload",
    "resolve_payload": "mergecraft.utils.payload",
    "resolve_prompt_input": "mergecraft.utils.payload",
    "filter_env": "mergecraft.utils.secrets",
    "is_sensitive_env_name": "mergecraft.utils.secrets",
    "sanitize_secret": "mergecraft.utils.secrets",
    "set_env_allowlist": "mergecraft.utils.secrets",
    "TIMEOUT_DISABLED": "mergecraft.utils.time_parse",
    "parse_time_string": "mergecraft.utils.time_parse",
    "parse_timeout": "mergecraft.utils.time_parse",
    "resolve_timeout_ms": "mergecraft.utils.time_parse",
}

__all__ = [
    "TIMEOUT_DISABLED",
    "GitHubClient",
    "JsonPayload",
    "PayloadEvent",
    "configure_logging",
    "filter_env",
    "is_sensitive_env_name",
    "logger",
    "normalize_env",
    "parse_repo_context",
    "parse_time_string",
    "parse_timeout",
    "resolve_payload",
    "resolve_prompt_input",
    "resolve_run_context_data",
    "resolve_timeout_ms",
    "sanitize_secret",
    "set_env_allowlist",
]


def __getattr__(name: str) -> Any:
    """Resolve public re-exports without loading unrelated runtime subsystems."""
    if name not in _EXPORT_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_EXPORT_MODULES[name]), name)
    globals()[name] = value
    return value
