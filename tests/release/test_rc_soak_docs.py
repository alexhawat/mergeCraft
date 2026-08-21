"""W8.1 — RC / soak process documentation (#382).

Out of scope: the docs system itself (RD1); config schema versioning.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from tests.ci.workflow_support import REPO_ROOT, read_text

_W82 = pytest.mark.xfail(
    reason="green after W8.2: RC/soak process doc (#382)",
    strict=False,
)

_RELEASE_PROCESS = "docs/release-process.md"


def _pages() -> list[dict[str, Any]]:
    data = yaml.safe_load((REPO_ROOT / "docs" / "manifest.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    pages = data.get("pages")
    assert isinstance(pages, list)
    return [row for row in pages if isinstance(row, dict)]


@_W82
def test_release_process_page_registered_in_manifest() -> None:
    """Happy: RC/soak lives on a docs page registered in the RD1 manifest."""
    row = next((item for item in _pages() if item.get("path") == _RELEASE_PROCESS), None)
    assert row is not None, f"docs/manifest.yaml missing {_RELEASE_PROCESS}"


@_W82
def test_release_process_doc_names_rc_and_soak() -> None:
    """Happy: the process doc names release candidates and soak periods."""
    text = read_text(_RELEASE_PROCESS).casefold()
    assert "release candidate" in text or "\nrc " in text or " rc/" in text or "rc/" in text
    assert "soak" in text


@_W82
def test_release_process_mentions_changelog_and_migration_notes() -> None:
    """Happy: per-release changelog and migration notes are part of the process."""
    text = read_text(_RELEASE_PROCESS).casefold()
    assert "changelog" in text
    assert "migration" in text


@_W82
def test_missing_release_process_page_is_a_hard_failure() -> None:
    """Error: the process page must exist as a real file, not only a manifest stub."""
    path = REPO_ROOT / _RELEASE_PROCESS
    assert path.is_file(), f"missing {_RELEASE_PROCESS}"
    assert path.read_text(encoding="utf-8").strip(), f"{_RELEASE_PROCESS} is empty"
