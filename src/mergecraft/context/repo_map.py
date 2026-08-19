"""Build a structural map of packages, services, entrypoints, and build config."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for repo traversal
from typing import Any, Protocol, cast

_BUILD_CONFIG_NAMES = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "Makefile",
        "makefile",
        "CMakeLists.txt",
        "package.json",
        "Cargo.toml",
        "go.mod",
    }
)
_SERVICE_DIR_NAMES = frozenset({"services", "service"})


class _CacheProto(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class MapEntry:
    """One indexed path or named entry in the repo map."""

    path: str
    name: str = ""


@dataclass(frozen=True, slots=True)
class RepoMap:
    """Structural overview of a repository at one tree SHA."""

    packages: tuple[MapEntry, ...]
    services: tuple[MapEntry, ...]
    entrypoints: tuple[MapEntry, ...]
    build_config: tuple[MapEntry, ...]


def build_repo_map(
    *,
    repo_root: Path,
    tree_sha: str,
    cache: _CacheProto | None = None,
) -> RepoMap:
    """Index packages, services, entrypoints, and build config for ``tree_sha``."""
    if cache is not None:
        cached = cache.get(tree_sha)
        if cached is not None:
            return cast(  # cache stores RepoMap values; Any return type from cache.get narrows back to concrete type
                "RepoMap", cached
            )

    repo_map = RepoMap(
        packages=_index_packages(repo_root),
        services=_index_services(repo_root),
        entrypoints=_index_entrypoints(repo_root),
        build_config=_index_build_config(repo_root),
    )
    if cache is not None:
        cache.set(tree_sha, repo_map)
    return repo_map


def _index_packages(repo_root: Path) -> tuple[MapEntry, ...]:
    packages: list[MapEntry] = []
    src_root = repo_root / "src"
    if src_root.is_dir():
        for path in sorted(src_root.rglob("__init__.py")):
            rel_init = path.relative_to(repo_root).as_posix()
            package_dir = path.parent.relative_to(repo_root).as_posix()
            packages.append(MapEntry(path=package_dir, name=path.parent.name))
            packages.append(MapEntry(path=rel_init, name=path.parent.name))
    return tuple(packages)


def _index_services(repo_root: Path) -> tuple[MapEntry, ...]:
    services: list[MapEntry] = []
    for dir_name in _SERVICE_DIR_NAMES:
        services_root = repo_root / dir_name
        if not services_root.is_dir():
            continue
        for path in sorted(services_root.rglob("*.py")):
            if path.is_file():
                rel = path.relative_to(repo_root).as_posix()
                services.append(MapEntry(path=rel, name=path.stem))
    return tuple(services)


def _index_entrypoints(repo_root: Path) -> tuple[MapEntry, ...]:
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        return ()
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return ()
    scripts = data.get("project", {}).get("scripts", {})
    if not isinstance(scripts, dict):
        return ()
    return tuple(
        MapEntry(path=str(target), name=str(name))
        for name, target in sorted(scripts.items())
        if isinstance(name, str) and isinstance(target, str)
    )


def _index_build_config(repo_root: Path) -> tuple[MapEntry, ...]:
    entries: list[MapEntry] = []
    for name in sorted(_BUILD_CONFIG_NAMES):
        path = repo_root / name
        if path.is_file():
            entries.append(MapEntry(path=name, name=name))
    return tuple(entries)


__all__ = ["MapEntry", "RepoMap", "build_repo_map"]
