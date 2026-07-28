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
    issues: list[str] = field(default_factory=list)


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
]
