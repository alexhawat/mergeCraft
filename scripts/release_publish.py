"""Helpers for the workflow-driven release publish.

``notes`` extracts one version's section from ``CHANGELOG.md`` for the GitHub
release body. ``verify-dist`` refuses a dist directory that is not exactly the
wheel and sdist for the version being published, so the workflow cannot upload
an artifact built for another commit or a stray file.

Exports:
    main: CLI entry point (``notes`` / ``verify-dist``).
    release_notes: Return the changelog body for one version.
    verify_dist: Validate the dist directory and return its two files.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\](?:[ \t]+[—-][ \t]+(?P<date>.+))?[ \t]*$", re.M)


def release_notes(changelog: str, version: str) -> str:
    """Return the ``## [version]`` section body, without the heading.

    Raises:
        ValueError: The changelog has no section for ``version``.
    """
    headings = list(_HEADING.finditer(changelog))
    for index, heading in enumerate(headings):
        if heading.group("version") != version:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
        body = changelog[heading.end() : end].strip("\n")
        if not body.strip():
            msg = f"the ## [{version}] changelog section is empty"
            raise ValueError(msg)
        return body
    msg = f"no ## [{version}] section in the changelog"
    raise ValueError(msg)


def verify_dist(dist_dir: Path, version: str) -> list[Path]:
    """Return the wheel and sdist when the directory holds exactly those two.

    Raises:
        ValueError: The directory has anything else, or a file names another
            version.
    """
    files = sorted(path for path in dist_dir.iterdir() if path.is_file())
    wheels = [path for path in files if path.suffix == ".whl"]
    sdists = [path for path in files if path.name.endswith(".tar.gz")]
    if len(files) != 2 or len(wheels) != 1 or len(sdists) != 1:
        msg = (
            "the dist directory must hold exactly one wheel and one sdist, "
            f"found: {[path.name for path in files]}"
        )
        raise ValueError(msg)
    for path in files:
        stem = path.name[:-4] if path.name.endswith(".whl") else path.name[:-7]
        parts = stem.split("-")
        found = parts[1] if len(parts) > 1 else ""
        if found != version:
            msg = f"{path.name} names version {found or '<none>'}, not {version}"
            raise ValueError(msg)
    return files


def main(argv: list[str] | None = None) -> int:
    """Run the ``notes`` or ``verify-dist`` subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    notes = sub.add_parser("notes", help="print one changelog section")
    notes.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    notes.add_argument("--version", required=True)

    verify = sub.add_parser("verify-dist", help="validate the release dist directory")
    verify.add_argument("--dist", type=Path, default=Path("dist"))
    verify.add_argument("--version", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "notes":
            print(release_notes(args.changelog.read_text(encoding="utf-8"), args.version))
        else:
            for path in verify_dist(args.dist, args.version):
                print(path.name)
    except (OSError, ValueError) as exc:
        print(f"release-publish: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
