# SPDX-License-Identifier: MIT
"""Normalize a release branch after ``craft prepare``.

Craft cuts the release section **above** ``## [Unreleased]`` and advances
``docs/consumer-release.json``. Two repository gates then fail on the release
branch and nowhere else, because both are keyed to state that only a release
changes:

* ``tests/docs/test_changelog_structure.py`` requires ``## [Unreleased]`` to be
  the first release block.
* ``tests/docs/test_gen_agent_packages_blob_ref.py`` requires the recorded
  documentation fixture to name the ref the generated packages link to, which is
  ``v<consumer-release version>``.

Pull request CI renders against the published release and cannot see either
drift, so the Release workflow's ``prepare`` job runs this after Craft and
commits the result. A local ``craft prepare`` must do the same before pushing
(``make release-normalize``).

Every function is pure apart from the two writers, and both are idempotent, so a
re-run on an already-normalized tree changes nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
FIXTURE = ROOT / "tests" / "docs" / "fixtures" / "agent_package_documentation.json"
UNRELEASED = "## [Unreleased]"


class NormalizeError(Exception):
    """The tree cannot be normalized without guessing."""


def reorder_unreleased(text: str) -> str:
    """Return ``text`` with the ``## [Unreleased]`` block first.

    The block moves above the first release heading, which is where it sits on
    ``main``. Order inside the block and every other block is untouched, so this
    never rewrites an entry.

    Raises:
        NormalizeError: There is no ``## [Unreleased]`` block at all.
    """
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.startswith("## ")]
    unreleased = [index for index in starts if lines[index].startswith(UNRELEASED)]
    if len(unreleased) != 1:
        msg = f"expected exactly one {UNRELEASED} block, found {len(unreleased)}"
        raise NormalizeError(msg)
    start = unreleased[0]
    later = [index for index in starts if index > start]
    end = later[0] if later else len(lines)
    if start == starts[0]:
        return text
    block = lines[start:end]
    rest = lines[:start] + lines[end:]
    first = next(index for index, line in enumerate(rest) if line.startswith("## "))
    return "".join(rest[:first] + block + rest[first:])


def release_ref(version: str) -> str:
    """Return the documentation ref the generated packages pin for ``version``."""
    return f"v{version}"


def refresh_fixture(
    document: dict[str, object], version: str, blobs: dict[str, str]
) -> dict[str, object]:
    """Return ``document`` pinned to ``version``, with each recorded blob refreshed.

    The fixture records the git blob ids behind the documentation links the
    generated packages emit, so it has to describe the tree being released rather
    than the previously published tag.

    Raises:
        NormalizeError: A recorded path is missing from the release tree.
    """
    recorded = document.get("blobs")
    if not isinstance(recorded, dict) or not recorded:
        msg = "the documentation fixture records no blobs"
        raise NormalizeError(msg)
    missing = sorted(set(recorded) - set(blobs))
    if missing:
        msg = f"documentation paths missing from the release tree: {missing}"
        raise NormalizeError(msg)
    refreshed: dict[str, object] = {}
    for path, entry in recorded.items():
        oid = blobs[path]
        refreshed[path] = {**(entry if isinstance(entry, dict) else {}), "git_blob_oid": oid}
    return {"ref": release_ref(version), "blobs": refreshed}


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = f"git {' '.join(args)} failed: {result.stderr.strip()}"
        raise NormalizeError(msg)
    return result.stdout.strip()


def _version_from_pyproject() -> str:
    match = re.search(
        r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M
    )
    if match is None:
        msg = "pyproject.toml carries no version"
        raise NormalizeError(msg)
    return match.group(1)


def _tree_blobs(paths: list[str]) -> dict[str, str]:
    return {path: _git("rev-parse", f"HEAD:{path}") for path in paths}


def main(argv: list[str] | None = None) -> int:
    """Normalize the working tree; ``--check`` reports drift instead of writing it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="release version (defaults to pyproject.toml)")
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when the tree needs normalizing"
    )
    args = parser.parse_args(argv)

    version = str(args.version or _version_from_pyproject())
    if version.endswith(".dev0"):
        print(f"release-normalize: {version} is a development version; nothing to do")
        return 0

    try:
        changelog = CHANGELOG.read_text(encoding="utf-8")
        ordered = reorder_unreleased(changelog)
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        paths = sorted(document["blobs"])
        refreshed = refresh_fixture(document, version, _tree_blobs(paths))
    except (NormalizeError, KeyError, TypeError) as error:
        print(f"release-normalize: {error}", file=sys.stderr)
        return 1

    fixture_text = json.dumps(refreshed, indent=2) + "\n"
    changed = ordered != changelog or fixture_text != FIXTURE.read_text(encoding="utf-8")
    if args.check:
        print(f"release-normalize: {'drift' if changed else 'clean'} for {release_ref(version)}")
        return 1 if changed else 0
    if not changed:
        print(f"release-normalize: already normalized for {release_ref(version)}")
        return 0
    CHANGELOG.write_text(ordered, encoding="utf-8")
    FIXTURE.write_text(fixture_text, encoding="utf-8")
    print(f"release-normalize: normalized the tree for {release_ref(version)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
