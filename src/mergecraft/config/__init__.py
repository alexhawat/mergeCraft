"""Public re-exports for ``mergecraft.config``."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mergecraft.config.settings import (
        CliTrustOverride,
        HeadingDepth,
        LearningsHeading,
        ModeDefinition,
        RepoInfo,
        RepoSettings,
        RunContextData,
        StaticCheckDefinition,
        TraceSinkEntry,
        TracingSettings,
        default_settings,
        load_learnings,
        load_repo_settings,
        parse_cli_trust_override,
        parse_learnings_headings,
    )
    from mergecraft.types import PushPermission, ShellPermission

_EXPORT_MODULES = {
    "CliTrustOverride": "mergecraft.config.settings",
    "HeadingDepth": "mergecraft.config.settings",
    "LearningsHeading": "mergecraft.config.settings",
    "ModeDefinition": "mergecraft.config.settings",
    "RepoInfo": "mergecraft.config.settings",
    "RepoSettings": "mergecraft.config.settings",
    "RunContextData": "mergecraft.config.settings",
    "StaticCheckDefinition": "mergecraft.config.settings",
    "TraceSinkEntry": "mergecraft.config.settings",
    "TracingSettings": "mergecraft.config.settings",
    "default_settings": "mergecraft.config.settings",
    "load_learnings": "mergecraft.config.settings",
    "load_repo_settings": "mergecraft.config.settings",
    "parse_cli_trust_override": "mergecraft.config.settings",
    "parse_learnings_headings": "mergecraft.config.settings",
    "PushPermission": "mergecraft.types",
    "ShellPermission": "mergecraft.types",
}

__all__ = [
    "CliTrustOverride",
    "HeadingDepth",
    "LearningsHeading",
    "ModeDefinition",
    "PushPermission",
    "RepoInfo",
    "RepoSettings",
    "RunContextData",
    "ShellPermission",
    "StaticCheckDefinition",
    "TraceSinkEntry",
    "TracingSettings",
    "default_settings",
    "load_learnings",
    "load_repo_settings",
    "parse_cli_trust_override",
    "parse_learnings_headings",
]


def __getattr__(name: str) -> Any:
    """Resolve public re-exports without loading unrelated runtime subsystems."""
    if name not in _EXPORT_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_EXPORT_MODULES[name]), name)
    globals()[name] = value
    return value
