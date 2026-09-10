#!/usr/bin/env python3
"""Agent Skills portability gate for ``.github/skills/code-review`` (D15).

Validates frontmatter limits, name-matches-directory, reference resolution,
one-level depth, long-file TOCs, and no reference→reference links.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from mergecraft.analyzers.agentsec.skill_manifest import parse_skill_file

REPO = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO / ".github" / "skills" / "code-review"
SKILL_MD = SKILL_ROOT / "SKILL.md"
_REFERENCE_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _reference_paths(body: str) -> list[Path]:
    rels = [
        match.group(1)
        for match in _REFERENCE_LINK_RE.finditer(body)
        if match.group(1).startswith("references/")
    ]
    return [(SKILL_ROOT / rel).resolve() for rel in rels]


def _fail(message: str) -> None:
    print(message, file=sys.stderr)


def main() -> int:
    """Validate the canonical review skill against the Agent Skills spec."""
    if not SKILL_MD.is_file():
        _fail(f"missing {SKILL_MD}")
        return 1

    text = SKILL_MD.read_text(encoding="utf-8")
    if "references/" not in text:
        _fail("SKILL.md must link at least one references/ file")
        return 1

    document = parse_skill_file(SKILL_MD, repo_relative=".github/skills/code-review/SKILL.md")
    if document is None:
        _fail("failed to parse SKILL.md frontmatter")
        return 1

    name = str(document.fields.get("name") or "")
    description = str(document.fields.get("description") or "")
    if name != "code-review":
        _fail(f"name must be code-review, got {name!r}")
        return 1
    if name != SKILL_ROOT.name:
        _fail("name must match the skill directory")
        return 1
    if len(name) > 64:
        _fail("name exceeds 64 characters")
        return 1
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        _fail("name contains consecutive hyphens or invalid characters")
        return 1
    if not description:
        _fail("description must be non-empty")
        return 1
    if len(description) > 1024:
        _fail("description exceeds 1024 characters")
        return 1

    lines = text.splitlines()
    if len(lines) >= 500:
        _fail("SKILL.md body exceeds the 500-line budget")
        return 1

    body = text.split("---", 2)[-1]
    refs = _reference_paths(body)
    if not refs:
        _fail("SKILL.md must resolve at least one references/ file")
        return 1

    skill_root_resolved = SKILL_ROOT.resolve()
    for path in refs:
        if not path.is_file():
            _fail(f"missing reference file: {path}")
            return 1
        if not path.resolve().is_relative_to(skill_root_resolved):
            _fail(f"reference escapes skill root: {path}")
            return 1

    for path in refs:
        ref_text = path.read_text(encoding="utf-8")
        for match in _REFERENCE_LINK_RE.finditer(ref_text):
            target = match.group(1)
            if target.startswith("references/"):
                _fail(f"{path.name} links to another reference: {target}")
                return 1

    for path in refs:
        ref_lines = path.read_text(encoding="utf-8").splitlines()
        if len(ref_lines) <= 100:
            continue
        head = "\n".join(ref_lines[:20]).casefold()
        if "table of contents" not in head:
            _fail(f"{path.name} exceeds 100 lines without a TOC")
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
