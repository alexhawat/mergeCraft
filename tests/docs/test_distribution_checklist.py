"""W5 — 0.0.1 distribution checklist (#141)."""

from __future__ import annotations

import re
from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT, read_text

_PAGES = "https://alexhawat.github.io/mergeCraft/"


def test_readme_drops_ideal_and_todo_asset_comments() -> None:
    text = read_text("README.md")
    assert "README-ideal.md" not in text
    assert "readme_test.md" not in text
    assert "TODO: add docs/assets/logo.svg" not in text
    assert "TODO: add docs/assets/demo.gif" not in text


def test_docs_site_badge_and_links_are_gone() -> None:
    """Superseded by the showcase-readiness plan's D5, 2026-08-13.

    The GitHub Pages docs site was never published (no ``mkdocs.yml``, no Pages
    workflow) — a badge and nav links pointing at it 404'd. D5 deletes the
    badge and repoints every docs link at the in-repo ``docs/`` tree instead
    of building the site. This replaces the older D14 assertion that the
    badge must exist and point at ``_PAGES``.
    """
    text = read_text("README.md")
    assert _PAGES not in text
    assert "docs-mergecraft.dev" not in text
    assert re.search(r"\[!\[Docs\]\(", text) is None, "Docs badge should be gone (D5)"


def test_docs_assets_readme_names_required_binaries() -> None:
    """D17, superseded by showcase-readiness G1 (2026-08-14).

    ``assets/brand/`` is now tracked in git (mark/wordmark shipped), so
    ``docs/assets/README.md`` no longer asks the operator to supply ``logo.svg`` —
    only the demo capture remains outstanding. The original D17 intent (name the
    binary, don't invent a placeholder) still holds for what's left.
    """
    path = REPO_ROOT / "docs" / "assets" / "README.md"
    assert path.is_file(), "docs/assets/README.md missing"
    text = path.read_text(encoding="utf-8")
    assert "logo.svg" not in text, "logo.svg is shipped in assets/brand/, not operator-supplied"
    assert "demo.gif" in text


def test_distribution_checklist_matches_shipped_assets() -> None:
    """Showcase-readiness G1 (2026-08-14): a PR review caught this drifting once already —

    ``docs/distribution.md`` and ``docs/assets/README.md`` must describe the assets
    workflow the README actually uses (tracked ``assets/brand/`` + an outstanding demo
    capture under ``assets/``), not the pre-G1 "operator supplies docs/assets/logo.svg"
    flow the README no longer follows.
    """
    distribution = read_text("docs/distribution.md")
    assert _PAGES not in distribution
    assert "docs/assets/logo.svg" not in distribution
    assert "assets/brand" in distribution

    assets_readme = (REPO_ROOT / "docs" / "assets" / "README.md").read_text(encoding="utf-8")
    assert "assets/brand" in assets_readme
    assert "assets/demo.gif" in assets_readme


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


def test_python_311_floor_documented() -> None:
    """D16/W14 — Python >=3.11 floor; Docker remains for pinned runtimes."""
    readme = read_text("README.md")
    distribution = read_text("docs/distribution.md")
    assert "3.11" in readme
    assert "3.11" in distribution
    assert re.search(r"Docker", readme)


def test_docs_assets_dir_exists() -> None:
    assets = REPO_ROOT / "docs" / "assets"
    assert assets.is_dir()
    readme: Path = assets / "README.md"
    assert readme.is_file()
