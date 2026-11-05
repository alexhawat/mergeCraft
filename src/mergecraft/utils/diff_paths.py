"""Diff path extraction shared by evidence assembly and verifier confinement."""

from __future__ import annotations

from mergecraft.analyzers.scope import (
    parse_diff_scope,
    split_diff_git_paths,
    unquote_git_path,
)

_HEADER = "diff --git "


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
    header: str | None = None
    pair: tuple[str, str] | None = None
    images: dict[str, str] = {}
    in_hunk = False

    def finish_entry() -> None:
        if header is None:
            return
        # Extended rename/copy metadata and ---/+++ headers are authoritative
        # when an unquoted path itself contains the header separator " b/".
        resolved = (images["old"], images["new"]) if len(images) == 2 else pair
        if resolved is None:
            msg = f"could not parse changed paths from diff header: {header}"
            raise ValueError(msg)
        found.update(path for path in resolved if path and path != "/dev/null")

    for line in diff_text.splitlines():
        if line.startswith(_HEADER):
            finish_entry()
            header = line
            pair = split_diff_git_paths(line[len(_HEADER) :])
            images = {}
            in_hunk = False
        elif line.startswith("@@"):
            in_hunk = True
        elif header is not None and not in_hunk:
            for prefix, image, diff_prefix in (
                ("rename from ", "old", ""),
                ("rename to ", "new", ""),
                ("copy from ", "old", ""),
                ("copy to ", "new", ""),
                ("--- ", "old", "a/"),
                ("+++ ", "new", "b/"),
            ):
                if line.startswith(prefix):
                    token = line[len(prefix) :]
                    # Git separates a space-bearing ---/+++ path from an
                    # optional timestamp with a tab. Tabs in names are quoted.
                    if diff_prefix:
                        token = token.split("\t", 1)[0]
                    decoded = unquote_git_path(token)
                    if decoded is not None:
                        images[image] = decoded.removeprefix(diff_prefix)
                    break
    finish_entry()
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


__all__ = ["changed_paths_from_diff", "paths_from_diff_headers"]
