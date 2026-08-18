"""Generated, minified, and vendored path classification (DG1, D4)."""

from __future__ import annotations

from enum import StrEnum
from typing import TypedDict

from mergecraft.review_policy.manifest_names import GENERATOR_CONFIG_NAMES
from mergecraft.review_policy.paths import normalize_repo_path


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


def _generator_config_changed(change: ChangeSet) -> bool:
    changed = {normalize_repo_path(item) for item in change.get("changed_paths", [])}
    return any(item.rsplit("/", 1)[-1] in GENERATOR_CONFIG_NAMES for item in changed)


def review_includes_path(path: str, *, change: ChangeSet) -> bool:
    """Return whether review scope includes ``path`` under generator policy (D4)."""
    kind = classify_path(path)
    if kind == FileKind.SOURCE:
        return True
    changed = {normalize_repo_path(item) for item in change.get("changed_paths", [])}
    normalized_path = normalize_repo_path(path)
    if kind == FileKind.GENERATED:
        return _generator_config_changed(change) or normalized_path in changed
    return normalized_path in changed


def finding_survives_generated_policy(path: str, *, change: ChangeSet) -> bool:
    """Return whether findings on ``path`` survive post-diff generated filtering (D4).

    Unlike ``review_includes_path``, this ignores the ``path in changed`` shortcut
    for generated/minified/vendored paths — callers already scoped findings to
    the diff.
    """
    kind = classify_path(path)
    if kind == FileKind.SOURCE:
        return True
    if kind == FileKind.GENERATED:
        return _generator_config_changed(change)
    return False


__all__ = [
    "ChangeSet",
    "FileKind",
    "classify_path",
    "finding_survives_generated_policy",
    "review_includes_path",
]
