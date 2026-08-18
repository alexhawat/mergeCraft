"""Canonical lockfile and manifest names for scope and generated policy."""

from __future__ import annotations

LOCKFILE_NAMES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "poetry.lock",
        "Pipfile.lock",
        "uv.lock",
        "Cargo.lock",
        "go.sum",
        "composer.lock",
        "Gemfile.lock",
    }
)

DEPENDENCY_MANIFEST_NAMES: frozenset[str] = frozenset(
    {
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "package.json",
        "go.mod",
        "Cargo.toml",
        "Gemfile",
        "composer.json",
    }
)

GENERATOR_CONFIG_NAMES: frozenset[str] = frozenset(
    {
        "Makefile",
        "buf.gen.yaml",
        "openapi-generator.yaml",
    }
)

__all__ = [
    "DEPENDENCY_MANIFEST_NAMES",
    "GENERATOR_CONFIG_NAMES",
    "LOCKFILE_NAMES",
]
