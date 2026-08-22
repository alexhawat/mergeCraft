"""RV1.2 — glossary page and landing jargon links (RED until RV2).

Pins ``docs/glossary.md``, manifest row, required term anchors, first-use links on
the landing README, and the D5 ban on ``<abbr title=…>`` tooltips.
"""

from __future__ import annotations

import re

import pytest
import yaml

from tests.ci.workflow_support import REPO_ROOT, read_text

GLOSSARY = REPO_ROOT / "docs" / "glossary.md"
MANIFEST = REPO_ROOT / "docs" / "manifest.yaml"
README = REPO_ROOT / "README.md"

_REQUIRED_TERMS: tuple[tuple[str, str], ...] = (
    ("trust tier", "trust-tier"),
    ("typed finding", "typed-finding"),
    ("blast radius", "blast-radius"),
    ("harness", "harness"),
    ("verifier", "verifier"),
    ("analyzer", "analyzer"),
    ("BYOK", "byok"),
    ("SARIF", "sarif"),
    ("structural approval gate", "structural-approval-gate"),
    ("learnings", "learnings"),
)


def _load_manifest_paths() -> set[str]:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    pages = data.get("pages") or []
    paths: set[str] = set()
    for row in pages:
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            paths.add(row["path"])
    return paths


def _term_pattern(term: str) -> re.Pattern[str]:
    if term.isupper():
        return re.compile(rf"\b{re.escape(term)}\b")
    return re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)


def _first_occurrence_link(text: str, term: str, anchor: str) -> bool:
    pattern = _term_pattern(term)
    match = pattern.search(text)
    if not match:
        return False
    start = match.start()
    # Walk backward to the opening bracket of the enclosing markdown link, if any.
    prefix = text[:start]
    link_start = prefix.rfind("[")
    if link_start == -1:
        return False
    segment = text[link_start : start + len(term) + 80]
    return f"docs/glossary.md#{anchor}" in segment or f"glossary.md#{anchor}" in segment


def test_glossary_exists_and_is_manifested() -> None:
    assert GLOSSARY.is_file(), f"missing {GLOSSARY.relative_to(REPO_ROOT)} (RV2)"
    paths = _load_manifest_paths()
    assert "docs/glossary.md" in paths, "docs/manifest.yaml must list docs/glossary.md (D10)"


def test_glossary_defines_required_terms() -> None:
    assert GLOSSARY.is_file(), "docs/glossary.md missing"
    text = GLOSSARY.read_text(encoding="utf-8")
    missing: list[str] = []
    for term, anchor in _REQUIRED_TERMS:
        has_anchor = f"#{anchor}" in text
        has_heading = bool(
            re.search(rf"^###\s+.*{re.escape(term)}", text, re.IGNORECASE | re.MULTILINE)
        )
        if not has_anchor and not has_heading:
            missing.append(term)
    assert not missing, f"docs/glossary.md missing required terms: {missing}"


@pytest.mark.xfail(
    reason="green after RV2: landing jargon links on first use (D5/D6)",
    strict=False,
)
def test_landing_jargon_is_linked_on_first_use() -> None:
    text = read_text("README.md")
    unlinked: list[str] = []
    for term, anchor in _REQUIRED_TERMS:
        if _term_pattern(term).search(text) and not _first_occurrence_link(text, term, anchor):
            unlinked.append(term)
    assert not unlinked, (
        f"README first-use jargon must link to docs/glossary.md#<anchor>: {unlinked}"
    )


def test_no_abbr_title_tooltips() -> None:
    text = read_text("README.md")
    assert "<abbr" not in text.lower(), (
        "README must not use <abbr title=…> — GitHub renders no tooltip (D5)"
    )
