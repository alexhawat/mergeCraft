"""Diff path extraction shared by evidence assembly and verifier confinement."""

from __future__ import annotations

from mergecraft.analyzers.scope import parse_diff_scope
from mergecraft.diff import parse_diff, split_diff_git_paths

_HEADER = "diff --git "


def post_image_path_from_header(line: str) -> str | None:
    """Return the post-image path of one ``diff --git`` header line.

    Handles unquoted paths containing spaces and quoted (C-style escaped)
    paths. Returns ``None`` when the header is not a ``diff --git`` line or
    its paths are ambiguous (an unquoted rename whose names contain `` b/``);
    callers then fall back to their own heuristic.

    Examples:
        >>> post_image_path_from_header("diff --git a/my file.txt b/my file.txt")
        'my file.txt'
    """
    if not line.startswith(_HEADER):
        return None
    pair = split_diff_git_paths(line[len(_HEADER) :].rstrip("\r\n"))
    return pair[1] if pair is not None else None


def paths_from_diff_headers(diff_text: str) -> set[str]:
    """Return every path a ``diff --git`` header names, pre-image and post-image.

    Hunks say what changed line by line; a header says which files an entry is
    about. Using both matters because a review judges *paths*: a pure rename, a
    binary-only entry and a mode-only entry all touch a file without
    contributing a hunk, so a hunk-only reading of the diff would leave them out
    of the change set entirely.

    Both images of a rename are returned — the old path stopped existing and the
    new one started, so a rule scoped over either has been touched. Quoted paths
    are decoded, and the ``a/``/``b/`` prefix is stripped, so a caller compares
    repository-relative paths.

    Args:
        diff_text (str): A unified diff as git renders it.

    Returns:
        set[str]: The paths named by the diff's headers, without duplicates.

    Examples:
        >>> sorted(paths_from_diff_headers("diff --git a/x.py b/y.py\\n"))
        ['x.py', 'y.py']
    """
    found: set[str] = set()
    for section in parse_diff(diff_text).files:
        if not section.paths:
            header = section.text.split("\n", 1)[0]
            msg = f"could not parse changed paths from diff header: {header}"
            raise ValueError(msg)
        found.update(section.paths)
    return found


def changed_paths_from_diff(diff_text: str) -> list[str]:
    """Return every path the diff touches, sorted and deduplicated.

    Three signals are unioned, and each catches something the others miss:

    - ``analyzers/scope.py``'s hunk ranges, added files and scope exceptions
      (changed workflows, migrations, lockfiles, dependency manifests). Those are
      precisely the paths that drive blast radius, so this reuses that signal
      rather than writing a second diff parser with its own idea of what a
      migration looks like.
    - The ``diff --git`` headers, which are the only place a pure rename, a
      binary-only entry or a mode-only entry appears — none of them has a hunk
      for the scope parser to read.

    Unioning the exception sets in matters: a lockfile or workflow changed with
    no surviving hunk range would otherwise drop out of the path list and
    silently soften the classification.
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
    paths |= paths_from_diff_headers(diff_text)
    return sorted(paths)


__all__ = ["changed_paths_from_diff", "paths_from_diff_headers", "post_image_path_from_header"]
