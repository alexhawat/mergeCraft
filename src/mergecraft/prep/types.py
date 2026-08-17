"""Prep phase type definitions."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Literal, Protocol

NodePackageManager = Literal["npm", "pnpm", "yarn", "bun", "deno"]
PythonPackageManager = Literal["pip", "pipenv", "poetry", "uv"]
PrepLanguage = Literal["node", "python", "unknown"]


@dataclass(slots=True)
class PrepOptions:
    """Options for dependency prep steps."""

    ignore_scripts: bool = False
    bin_dir: str = ""


@dataclass(slots=True)
class PrepResult:
    """Result of a single language prep step."""

    language: PrepLanguage
    dependencies_installed: bool
    package_manager: str | None = None
    config_file: str | None = None
    skipped: bool = False
    issues: list[str] = field(default_factory=list)


def is_prep_install_failure(result: PrepResult) -> bool:
    """True when a language prep step attempted an install and failed.

    A policy skip (``shell: disabled`` / ``ignore_scripts``) is not an
    install failure. W6.1 fail-closed must not map that skip to
    ``RunOutcome.inconclusive`` — otherwise a completed review of a Python
    repo never posts ``mergecraft-approval``.
    """
    if result.skipped or result.dependencies_installed:
        return False
    return bool(result.issues)


class PrepDefinition(Protocol):
    name: str

    def should_run(self) -> bool | Awaitable[bool]: ...

    def run(self, options: PrepOptions) -> Awaitable[PrepResult]: ...


__all__ = [
    "NodePackageManager",
    "PrepDefinition",
    "PrepLanguage",
    "PrepOptions",
    "PrepResult",
    "PythonPackageManager",
    "is_prep_install_failure",
]
