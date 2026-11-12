# SPDX-License-Identifier: MIT
"""Normalize a release branch after ``craft prepare``.

Craft cuts the release section **above** ``## [Unreleased]`` and advances
``docs/consumer-release.json``. Three repository gates then fail on the release
branch and nowhere else, because each is keyed to state that only a release
changes:

* ``scripts/release_publish.py`` builds the GitHub release notes from the
  section naming the version, so hand-written entries left under
  ``[Unreleased]`` never reach the release.
* ``tests/docs/test_changelog_structure.py`` requires ``## [Unreleased]`` to be
  the first release block.
* ``tests/docs/test_gen_agent_packages_blob_ref.py`` requires the recorded
  documentation fixture to name the ref the generated packages link to, which is
  ``v<consumer-release version>``.

Pull request CI renders against the published release and cannot see any of it,
so the Release workflow's ``prepare`` job runs this after Craft and commits the
result. A local ``craft prepare`` must do the same before pushing
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

_H3 = re.compile(r"^### (?P<title>.*)$", re.M)
_VERSION_HEADING = re.compile(r"^##[ \t]+(?:\[(?P<bracketed>[^\]]+)\]|(?P<bare>[^\s\[]+))")


class NormalizeError(Exception):
    """The tree cannot be normalized without guessing."""


def _block_spans(lines: list[str]) -> list[tuple[int, int, str]]:
    """Return ``(start, end, heading)`` for every top-level ``## `` block."""
    starts = [index for index, line in enumerate(lines) if line.startswith("## ")]
    spans: list[tuple[int, int, str]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        spans.append((start, end, lines[start].rstrip("\n")))
    return spans


def _heading_version(heading: str) -> str | None:
    """Return the version a release heading names, bare or bracketed."""
    match = _VERSION_HEADING.match(heading)
    if match is None:
        return None
    return match.group("bracketed") or match.group("bare")


def _split_h3(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a block body into its preamble and its ``### `` sections."""
    matches = list(_H3.finditer(body))
    if not matches:
        return body, []
    sections: list[tuple[str, str]] = []
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(body)
        sections.append((match.group(0), body[match.end() : end]))
    return body[: matches[0].start()], sections


def _join_h3(preamble: str, sections: list[tuple[str, str]]) -> str:
    parts = [preamble.rstrip("\n")] if preamble.strip() else []
    for heading, body in sections:
        parts.append(heading)
        parts.append(body.strip("\n"))
    return "\n\n".join(parts) + "\n"


def _merge_bodies(target: str, incoming: str) -> str:
    """Merge ``incoming`` into ``target``, one heading per type.

    A heading the target already has keeps its position and gains the incoming
    entries after its own. A heading the target lacks is inserted above the
    target's first section, in incoming order, so curated notes such as
    ``### Breaking — action required`` stay where a reader expects them.
    """
    target_preamble, target_sections = _split_h3(target)
    incoming_preamble, incoming_sections = _split_h3(incoming)
    positions = {
        heading.strip().lower(): index for index, (heading, _) in enumerate(target_sections)
    }
    added: list[tuple[str, str]] = []
    for heading, body in incoming_sections:
        position = positions.get(heading.strip().lower())
        if position is None:
            added.append((heading, body))
            continue
        existing_heading, existing_body = target_sections[position]
        target_sections[position] = (
            existing_heading,
            existing_body.rstrip("\n") + "\n\n" + body.strip("\n") + "\n",
        )
    preamble = target_preamble
    if incoming_preamble.strip():
        preamble = preamble.rstrip("\n") + "\n\n" + incoming_preamble.strip("\n") + "\n"
    return _join_h3(preamble, added + target_sections)


def fold_unreleased(text: str, version: str) -> str:
    """Return ``text`` with the ``## [Unreleased]`` entries folded into ``version``.

    Craft cuts a section listing every merged pull request and leaves the
    hand-written ``## [Unreleased]`` block below it. Shipping that unchanged
    publishes release notes without the curated entries (breaking changes,
    action-required notes) and leaves the tag describing shipped work as
    unreleased. The entries move into the cut section and ``[Unreleased]`` is
    left empty.

    Raises:
        NormalizeError: There is no single ``[Unreleased]`` block, or it holds
            entries while no section exists for ``version``.
    """
    lines = text.splitlines(keepends=True)
    spans = _block_spans(lines)
    unreleased = [span for span in spans if span[2].startswith(UNRELEASED)]
    if len(unreleased) != 1:
        msg = f"expected exactly one {UNRELEASED} block, found {len(unreleased)}"
        raise NormalizeError(msg)
    unreleased_start, unreleased_end, _ = unreleased[0]
    unreleased_body = "".join(lines[unreleased_start + 1 : unreleased_end])
    if "- " not in unreleased_body:
        return text
    released = [span for span in spans if _heading_version(span[2]) == version]
    if len(released) != 1:
        msg = f"expected exactly one release block for {version}, found {len(released)}"
        raise NormalizeError(msg)
    released_start, released_end, _ = released[0]
    merged = _merge_bodies("".join(lines[released_start + 1 : released_end]), unreleased_body)
    preamble = "".join(lines[: spans[0][0]])
    parts: list[str] = []
    for start, end, heading in spans:
        if start == released_start:
            body = merged
        elif start == unreleased_start:
            body = "\n"
        else:
            body = "".join(lines[start + 1 : end])
        parts.append(heading + "\n" + body.rstrip("\n") + "\n")
    return preamble + "\n".join(parts)


def normalize_changelog(text: str, version: str) -> str:
    """Fold the hand-written entries into ``version`` and put ``[Unreleased]`` first."""
    return reorder_unreleased(fold_unreleased(text, version))


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
        ordered = normalize_changelog(changelog, version)
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
