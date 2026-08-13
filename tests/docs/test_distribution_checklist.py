"""W5 — 0.0.1 distribution checklist (#141)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.ci.workflow_support import REPO_ROOT, read_text

_W5 = pytest.mark.xfail(reason="green after W5: 0.0.1 distribution checklist (#141)", strict=False)

_PAGES = "https://alexhawat.github.io/mergeCraft/"


@_W5
def test_readme_drops_ideal_and_todo_asset_comments() -> None:
    text = read_text("README.md")
    assert "README-ideal.md" not in text
    assert "TODO: add docs/assets/logo.svg" not in text
    assert "TODO: add docs/assets/demo.gif" not in text


@_W5
def test_docs_badge_label_matches_live_github_pages_url() -> None:
    """D14 — keep the live Pages URL; fix the badge label to match."""
    text = read_text("README.md")
    assert _PAGES in text
    assert "docs-mergecraft.dev" not in text
    match = re.search(r"\[!\[Docs\]\((https://img\.shields\.io/badge/[^)]+)\)\]\(([^)]+)\)", text)
    assert match is not None, "Docs badge missing from README"
    label_url, href = match.group(1), match.group(2)
    assert href.rstrip("/") == _PAGES.rstrip("/")
    assert "mergecraft.dev" not in label_url or "github.io" in label_url


@_W5
def test_docs_assets_readme_names_required_binaries() -> None:
    """D17 — agent names logo.svg / demo.gif; does not invent the binaries."""
    path = REPO_ROOT / "docs" / "assets" / "README.md"
    assert path.is_file(), "docs/assets/README.md missing"
    text = path.read_text(encoding="utf-8")
    assert "logo.svg" in text
    assert "demo.gif" in text


@_W5
def test_prototype_residue_removed_or_documented() -> None:
    spike = REPO_ROOT / "docs" / "meat-spike.md"
    assert not spike.exists(), "docs/meat-spike.md must be removed"
    leftover = REPO_ROOT / "meat_python_plus"
    if leftover.exists():
        docs = (REPO_ROOT / "docs").rglob("*.md")
        mentioned = any("meat_python_plus" in path.read_text(encoding="utf-8") for path in docs)
        assert mentioned, "meat_python_plus/ remains but is not documented"


def test_yes_package_not_renamed_unless_d15_allows() -> None:
    """D15 — ``src/mergecraft/yes/`` stays unless W5 proves zero consumers."""
    yes_dir = REPO_ROOT / "src" / "mergecraft" / "yes"
    assert yes_dir.is_dir(), "src/mergecraft/yes/ was renamed; D15 forbids that in this program"


@_W5
def test_python_314_requirement_documented() -> None:
    """D16 — Python >=3.14 stays hard; Docker is the supported path without it."""
    text = read_text("README.md")
    assert "3.14" in text
    assert re.search(r"Docker", text)


@_W5
def test_docs_assets_dir_exists() -> None:
    assets = REPO_ROOT / "docs" / "assets"
    assert assets.is_dir()
    readme: Path = assets / "README.md"
    assert readme.is_file()
