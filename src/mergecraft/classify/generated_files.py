"""Generated, minified, and vendored path classification (DG1, D4)."""

from __future__ import annotations

from enum import StrEnum
from typing import TypedDict

from mergecraft.analyzers.manifest_names import CONFIG_MANIFEST_NAMES
from mergecraft.analyzers.paths import normalize_repo_path

_GENERATOR_CONFIG_NAMES = CONFIG_MANIFEST_NAMES


class FileKind(StrEnum):
    """How a path should be treated for review policy."""

    SOURCE = "source"
    GENERATED = "generated"
    MINIFIED = "minified"
    VENDORED = "vendored"


class ChangeSet(TypedDict, total=False):
    """Side-effect-free change payload for inclusion policy."""

    changed_paths: list[str]
    diff_stats: dict[str, object]


def classify_path(path: str) -> FileKind:
    """Label a repository path as source, generated, minified, or vendored."""
    normalized = normalize_repo_path(path).casefold()
    name = normalized.rsplit("/", 1)[-1]
    if name.endswith((".min.js", ".min.css")):
        return FileKind.MINIFIED
    if "/generated/" in f"/{normalized}/" or normalized.startswith("generated/"):
        return FileKind.GENERATED
    if normalized.startswith("vendor/") or "/vendor/" in f"/{normalized}/":
        return FileKind.VENDORED
    if normalized.startswith("third_party/") or "/third_party/" in f"/{normalized}/":
        return FileKind.VENDORED
    return FileKind.SOURCE


def review_includes_path(path: str, *, change: ChangeSet) -> bool:
    """Return whether review scope includes ``path`` under generator policy (D4)."""
    kind = classify_path(path)
    if kind == FileKind.SOURCE:
        return True
    changed = {normalize_repo_path(item) for item in change.get("changed_paths", [])}
    normalized_path = normalize_repo_path(path)
    if kind == FileKind.GENERATED:
        generator_changed = any(
            item.rsplit("/", 1)[-1] in _GENERATOR_CONFIG_NAMES for item in changed
        )
        return generator_changed or normalized_path in changed
    return normalized_path in changed


__all__ = ["ChangeSet", "FileKind", "classify_path", "review_includes_path"]
