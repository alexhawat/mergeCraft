#!/usr/bin/env python3
"""Guard: ``action.yml``/``action.yaml`` ``description:`` text must never embed ``${{``.

GitHub Actions evaluates ``${{ ... }}`` wherever it appears *lexically* in an
action's YAML manifest — not only in executable fields such as
``runs.env``, ``outputs.*.value``, or ``with:`` blocks, but also inside plain
``description:`` prose that documents an input for a consumer. A composite
action's own metadata scope does not expose every context a workflow does
(``secrets`` in particular is not a valid named-value there), so a
copy-pasted example like `` `${{ secrets.MY_TOKEN }}` `` inside a
description fails the action's *load* step for every consumer — not a
review-time lint failure, a load-time break with no diff-time signal. See
``c498e82`` (fix(action): stop action.yml description text from breaking
as an expression) for the incident this guards against.

This is intentionally broader than "no ``secrets.*``": ANY live ``${{``
token inside a ``description:`` scalar is almost certainly a documentation
mistake, since a description field is never templated by GitHub and has no
legitimate reason to carry an unescaped expression — even a *validly scoped*
one (e.g. ``${{ inputs.foo }}``) is far more likely a copy of the executable
field beside it than an intentional literal.

Parsed YAML loses the literal ``${{`` token once it is inside a string
value, so this scans the raw file text (like
``tests/action/test_action_yml_contract.py::TestActionYmlHygiene``'s
existing ``secrets.``-only regression test), rather than the parsed dict.

Module: scripts.check_action_yml_hygiene
Depends: pathlib, re, sys

Exports:
    main — CLI entry; scans every action.yml/action.yaml for description
        fields containing a literal ``${{`` token, and every file under
        ``.github/skills/**`` for the same token (D18).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_EXCLUDED_DIR_PARTS = frozenset(
    {
        ".venv",
        "venv",
        "node_modules",
        ".git",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        # Test fixtures intentionally plant this exact bug (e.g.
        # tests/analyzers/fixtures/repo/action.yml, C3 pattern-scanner
        # coverage for the default ruleset's action-yml-description-
        # expression rule) — they are fixture data, not manifests this repo
        # ships or loads, so they're out of scope for this guard.
        "tests",
    }
)

_BLOCK_INDICATORS = ("|", "|-", "|+", ">", ">-", ">+")


def _find_skill_files(root: Path) -> list[Path]:
    """Return every file under ``.github/skills`` (D18 skill-tree hygiene)."""
    skill_root = root / ".github" / "skills"
    if not skill_root.is_dir():
        return []
    files: list[Path] = []
    for path in skill_root.rglob("*"):
        if not path.is_file():
            continue
        if _EXCLUDED_DIR_PARTS.intersection(path.parts):
            continue
        files.append(path)
    return sorted(files)


def _scan_skill_file(path: Path) -> list[Offense]:
    """Return every ``${{`` occurrence in a skill-tree file."""
    offenses: list[Offense] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if "${{" in line:
            offenses.append(Offense(path, line_no, line.strip()))
    return offenses


def _find_action_manifests(root: Path) -> list[Path]:
    """Return every ``action.yml``/``action.yaml`` under ``root``, sorted.

    Skips vendored/virtualenv/cache trees so the scan stays fast and doesn't
    flag dependency-owned files this repo doesn't control.
    """
    manifests: list[Path] = []
    for pattern in ("action.yml", "action.yaml"):
        for path in root.rglob(pattern):
            if _EXCLUDED_DIR_PARTS.intersection(path.parts):
                continue
            manifests.append(path)
    return sorted(set(manifests))


def _indent(line: str) -> int:
    """Return the count of leading spaces on ``line``."""
    return len(line) - len(line.lstrip(" "))


def _is_description_key(line: str) -> tuple[int, str] | None:
    """Return ``(indent, rest)`` when ``line`` is a ``description:`` mapping key.

    ``rest`` is whatever follows the colon on that same line, stripped.
    Returns ``None`` for lines that aren't a bare ``description:`` key
    (e.g. commented out, or a different key that merely contains the word).
    """
    stripped = line.strip()
    if stripped.startswith("#"):
        return None
    if stripped != "description:" and not stripped.startswith("description:"):
        return None
    # Guard against keys like `description_extra:` matching via startswith.
    key, sep, rest = line.partition("description:")
    if sep != "description:":
        return None
    if key.strip():
        # Something other than whitespace precedes the key on this line —
        # not a mapping key at the start of its own line.
        return None
    return _indent(line), rest.strip()


class Offense:
    """One ``${{`` token found inside a ``description:`` scalar."""

    def __init__(self, path: Path, line_no: int, text: str) -> None:
        self.path = path
        self.line_no = line_no
        self.text = text

    def __str__(self) -> str:
        rel = self.path.resolve().relative_to(REPO).as_posix()
        return f"{rel}:{self.line_no}: {self.text}"


def _scan_manifest(path: Path) -> list[Offense]:
    """Return every ``${{`` occurrence found inside a ``description:`` value in ``path``."""
    lines = path.read_text(encoding="utf-8").splitlines()
    offenses: list[Offense] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        key_match = _is_description_key(line)
        if key_match is None:
            i += 1
            continue

        key_indent, rest = key_match
        # Strip a trailing YAML comment on the block-indicator line itself,
        # e.g. `description: |  # some note`, before checking for a token.
        inline_candidate = rest.split(" #", 1)[0].strip()
        is_block = inline_candidate in _BLOCK_INDICATORS or inline_candidate == ""

        if "${{" in line:
            offenses.append(Offense(path, i + 1, line.strip()))

        if is_block:
            j = i + 1
            while j < len(lines):
                cont = lines[j]
                if cont.strip() == "":
                    j += 1
                    continue
                if _indent(cont) <= key_indent:
                    break
                if "${{" in cont:
                    offenses.append(Offense(path, j + 1, cont.strip()))
                j += 1
            i = j
        else:
            i += 1

    return offenses


def main() -> int:
    """Scan action manifests and the review skill tree for literal ``${{`` tokens."""
    manifests = _find_action_manifests(REPO)
    skill_files = _find_skill_files(REPO)
    if not manifests and not skill_files:
        print(
            f"no action.yml/action.yaml or .github/skills files found under {REPO}",
            file=sys.stderr,
        )
        return 1

    manifest_offenses: list[Offense] = []
    for manifest in manifests:
        manifest_offenses.extend(_scan_manifest(manifest))

    skill_offenses: list[Offense] = []
    for skill_file in skill_files:
        skill_offenses.extend(_scan_skill_file(skill_file))

    if manifest_offenses:
        print(
            "literal `${{` expression syntax found inside `description:` text "
            "(GitHub evaluates it lexically wherever it appears, even in prose "
            "meant only as documentation — see c498e82):",
            file=sys.stderr,
        )
        for offense in manifest_offenses:
            print(f"  {offense}", file=sys.stderr)

    if skill_offenses:
        print(
            "literal `${{` expression syntax found under .github/skills "
            "(D18 — use the documented escape or cite the rule without a live token):",
            file=sys.stderr,
        )
        for offense in skill_offenses:
            print(f"  {offense}", file=sys.stderr)

    if manifest_offenses or skill_offenses:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
