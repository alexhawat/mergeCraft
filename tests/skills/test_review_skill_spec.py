"""RS1.5 — Agent Skills spec portability gates (RS4, D8/D15)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.context.review_skill_support import skill_root

_SKILL_ROOT = skill_root()
_SKILL_MD = _SKILL_ROOT / "SKILL.md"
_REFERENCE_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _skill_text() -> str:
    return _SKILL_MD.read_text(encoding="utf-8")


def _reference_paths() -> list[Path]:
    body = _skill_text().split("---", 2)[-1]
    rels = [
        match.group(1)
        for match in _REFERENCE_LINK_RE.finditer(body)
        if match.group(1).startswith("references/")
    ]
    return [(_SKILL_ROOT / rel).resolve() for rel in rels]


@pytest.mark.xfail(reason="green after RS3: Agent Skills frontmatter", strict=False)
def test_frontmatter_satisfies_the_agent_skills_spec() -> None:
    assert "references/" in _skill_text(), "pointer skill is not the authored payload"
    from mergecraft.analyzers.agentsec.skill_manifest import parse_skill_file

    document = parse_skill_file(_SKILL_MD, repo_relative=".github/skills/code-review/SKILL.md")
    assert document is not None
    name = str(document.fields.get("name") or "")
    description = str(document.fields.get("description") or "")
    assert name == "code-review"
    assert name == _SKILL_ROOT.name
    assert len(name) <= 64
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
    assert description
    assert len(description) <= 1024


@pytest.mark.xfail(reason="green after RS3: SKILL.md line budget", strict=False)
def test_body_is_under_the_line_budget() -> None:
    lines = _skill_text().splitlines()
    assert len(lines) > 80, "pointer skill is not the authored payload"
    assert len(lines) < 500


@pytest.mark.xfail(reason="green after RS3: reference link resolution", strict=False)
def test_every_reference_link_resolves_and_is_inside_the_skill_root() -> None:
    body = _skill_text().split("---", 2)[-1]
    links = [
        match.group(1)
        for match in _REFERENCE_LINK_RE.finditer(body)
        if match.group(1).startswith("references/")
    ]
    assert links, "SKILL.md must link at least one references/ file (Part 4 layout)"
    skill_root_resolved = _SKILL_ROOT.resolve()
    for path in _reference_paths():
        assert path.is_file(), f"missing reference file: {path}"
        assert path.resolve().is_relative_to(skill_root_resolved)


@pytest.mark.xfail(reason="green after RS3: one-level reference depth", strict=False)
def test_no_reference_file_links_to_another_reference_file() -> None:
    refs = _reference_paths()
    assert refs, "expected a references/ tree once RS3 lands"
    for path in refs:
        text = path.read_text(encoding="utf-8")
        for match in _REFERENCE_LINK_RE.finditer(text):
            target = match.group(1)
            assert not target.startswith("references/"), (
                f"{path.name} links to another reference: {target}"
            )


@pytest.mark.xfail(reason="green after RS3: reference TOC requirement", strict=False)
def test_reference_files_over_100_lines_open_with_a_table_of_contents() -> None:
    refs = _reference_paths()
    assert refs, "expected a references/ tree once RS3 lands"
    for path in refs:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= 100:
            continue
        head = "\n".join(lines[:20]).casefold()
        assert "table of contents" in head, f"{path.name} exceeds 100 lines without a TOC"


def test_skill_contains_no_literal_workflow_expression() -> None:
    tree = _SKILL_ROOT
    for path in tree.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "${{" not in text, f"literal workflow expression in {path.relative_to(tree)}"
