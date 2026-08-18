"""Canonical lockfile and config manifest names for scope and generated policy."""

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

CONFIG_MANIFEST_NAMES: frozenset[str] = frozenset(
    {
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "package.json",
        "go.mod",
        "Cargo.toml",
        "Gemfile",
        "composer.json",
        "Makefile",
        "buf.gen.yaml",
        "openapi-generator.yaml",
    }
)

__all__ = ["CONFIG_MANIFEST_NAMES", "LOCKFILE_NAMES"]
