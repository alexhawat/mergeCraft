"""Diff path extraction shared by evidence assembly and verifier confinement."""

from __future__ import annotations

from mergecraft.analyzers.scope import parse_diff_scope


def changed_paths_from_diff(diff_text: str) -> list[str]:
    """Return every path the diff touches, reusing the analyzer scope parser.

    ``analyzers/scope.py`` already parses a unified diff and, on top of the
    hunk ranges, explicitly identifies changed workflows, migrations,
    lockfiles and dependency manifests (its "scope exceptions"). Those are
    precisely the paths that drive blast radius, so this reuses that signal
    rather than writing a second diff parser with its own idea of what a
    migration looks like.

    Unioning the exception sets in matters: a lockfile or workflow changed
    with no surviving hunk range would otherwise drop out of the path list
    and silently soften the classification.
    """
    if not diff_text.strip():
        return []
    scope = parse_diff_scope(diff_text)
    paths: set[str] = set(scope.hunk_ranges)
    paths |= set(scope.added_files)
    paths |= set(scope.changed_lockfiles)
    paths |= set(scope.changed_workflows)
    paths |= set(scope.changed_migrations)
    paths |= set(scope.changed_dependency_manifests)
    return sorted(paths)


__all__ = ["changed_paths_from_diff"]
