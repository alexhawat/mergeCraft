"""Canonical lockfile and manifest names for scope and generated policy."""

from __future__ import annotations

from pathlib import PurePosixPath

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
        "Pipfile",
    }
)

BUILD_MANIFEST_NAMES: frozenset[str] = frozenset({"CMakeLists.txt"})
"""Build definitions whose suffix reads like prose (``.txt``)."""

_REQUIREMENTS_SUFFIXES: tuple[str, ...] = (".txt", ".in")

GENERATOR_CONFIG_NAMES: frozenset[str] = frozenset(
    {
        "Makefile",
        "buf.gen.yaml",
        "openapi-generator.yaml",
    }
)


def is_dependency_manifest_path(path: str) -> bool:
    """Whether ``path`` names a dependency manifest or lockfile, compared case-insensitively.

    Beyond the exact names in :data:`DEPENDENCY_MANIFEST_NAMES` and
    :data:`LOCKFILE_NAMES`, every pip requirements or constraints variant counts:
    a ``.txt`` / ``.in`` file whose name contains ``requirements`` or starts with
    ``constraints``, and any such file under a ``requirements/`` directory.

    Examples:
        >>> is_dependency_manifest_path("requirements/prod.txt")
        True
        >>> is_dependency_manifest_path("docs/notes.txt")
        False
    """
    pure = PurePosixPath(path.replace("\\", "/").lower())
    name = pure.name
    exact = {item.lower() for item in DEPENDENCY_MANIFEST_NAMES | LOCKFILE_NAMES}
    if name in exact:
        return True
    if not name.endswith(_REQUIREMENTS_SUFFIXES):
        return False
    if "requirements" in name or name.startswith("constraints"):
        return True
    return "requirements" in pure.parts[:-1]


def is_build_manifest_path(path: str) -> bool:
    """Whether ``path`` names a build definition in :data:`BUILD_MANIFEST_NAMES` (any case)."""
    name = PurePosixPath(path.replace("\\", "/")).name.lower()
    return name in {item.lower() for item in BUILD_MANIFEST_NAMES}


__all__ = [
    "BUILD_MANIFEST_NAMES",
    "DEPENDENCY_MANIFEST_NAMES",
    "GENERATOR_CONFIG_NAMES",
    "LOCKFILE_NAMES",
    "is_build_manifest_path",
    "is_dependency_manifest_path",
]
