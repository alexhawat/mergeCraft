#!/usr/bin/env python3
"""Synchronize authored eval cases into package resources.

``evals/cases`` is the authoring tree. The wheel copy under
``src/mergecraft/evals/cases`` is generated one way from it. Packaged-only
files are reported but never deleted automatically.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_AUTHORING_ROOT = _REPO_ROOT / "evals" / "cases"
_PACKAGED_ROOT = _REPO_ROOT / "src" / "mergecraft" / "evals" / "cases"
_PACKAGED_SUBTREES = ("golden", "mutation", "skill")


class UnsafeCaseTree(ValueError):
    """A case tree contains a symlink or resolves outside its declared root."""


def _case_files(root: Path) -> dict[Path, Path]:
    """Return safe regular files under the package-backed subtrees."""
    if root.is_symlink():
        raise UnsafeCaseTree(f"refusing symlinked case root: {root}")
    resolved_root = root.resolve()
    files: dict[Path, Path] = {}
    for subtree_name in _PACKAGED_SUBTREES:
        subtree = root / subtree_name
        if subtree.is_symlink():
            raise UnsafeCaseTree(f"refusing symlinked case subtree: {subtree}")
        if not subtree.exists():
            continue
        if not subtree.is_dir():
            raise UnsafeCaseTree(f"case subtree is not a directory: {subtree}")
        for entry in subtree.rglob("*"):
            if entry.is_symlink():
                raise UnsafeCaseTree(f"refusing symlink in case tree: {entry}")
            resolved = entry.resolve()
            if not resolved.is_relative_to(resolved_root):
                raise UnsafeCaseTree(f"case path escapes declared root: {entry}")
            if entry.is_file():
                files[entry.relative_to(root)] = entry
    return files


def sync_eval_cases(
    *,
    authoring_root: Path = _AUTHORING_ROOT,
    packaged_root: Path = _PACKAGED_ROOT,
    check: bool = False,
) -> int:
    """Copy authoring files to the package tree, or report drift in check mode."""
    source = _case_files(authoring_root)
    if not source:
        raise UnsafeCaseTree(f"no package-backed authoring cases under {authoring_root}")
    packaged = _case_files(packaged_root)

    source_paths = set(source)
    packaged_paths = set(packaged)
    missing = sorted(source_paths - packaged_paths)
    stale = sorted(packaged_paths - source_paths)
    drifted = sorted(
        relative
        for relative in source_paths & packaged_paths
        if source[relative].read_bytes() != packaged[relative].read_bytes()
    )

    for relative in missing:
        print(f"missing packaged case: {relative.as_posix()}", file=sys.stderr)
    for relative in drifted:
        print(f"byte drift: {relative.as_posix()}", file=sys.stderr)
    for relative in stale:
        print(
            f"stale packaged-only case: {relative.as_posix()} "
            "(review and delete it explicitly from the packaged tree)",
            file=sys.stderr,
        )

    if check:
        if missing or drifted or stale:
            return 1
        print(f"eval case copies are synchronized ({len(source)} files)")
        return 0

    for relative in missing + drifted:
        destination = packaged_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source[relative], destination)
        print(f"synced {relative.as_posix()}")

    # Stale package files require a reviewed deletion in both trees. Since the
    # source-side file is already absent, the script leaves the package copy in
    # place and exits non-zero until an operator resolves it explicitly.
    return 1 if stale else 0


def main(argv: list[str] | None = None) -> int:
    """Run the one-way sync command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report missing, stale, or byte-drifted package copies without writing",
    )
    args = parser.parse_args(argv)
    try:
        return sync_eval_cases(check=args.check)
    except (OSError, UnsafeCaseTree) as exc:
        print(f"eval case sync refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
