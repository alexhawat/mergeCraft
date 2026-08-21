"""W8.1 RED — generated six-axis support matrix (#382, D19).

Pins generator / manifest / ``make docs-check`` behaviour. Does not treat a
hand-maintained markdown table as the source of truth.
``docs/compatibility-matrix.md`` stays the existing contributor notes page.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from tests.ci.workflow_support import REPO_ROOT, read_text

_W82 = pytest.mark.xfail(
    reason="green after W8.2: generated six-axis support matrix (#382)",
    strict=False,
)

_SUPPORT_MATRIX_PATH = "docs/support-matrix.md"
_GENERATOR = "support-matrix"
_SIX_AXES = ("os", "scm", "language", "analyzer", "provider", "model")


def _manifest() -> dict[str, Any]:
    data = yaml.safe_load((REPO_ROOT / "docs" / "manifest.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _pages() -> list[dict[str, Any]]:
    pages = _manifest().get("pages")
    assert isinstance(pages, list)
    rows: list[dict[str, Any]] = []
    for row in pages:
        assert isinstance(row, dict)
        rows.append(row)
    return rows


def test_gen_docs_still_dispatches_rd1_generators() -> None:
    """GREEN (D19): extend the RD1 generator; do not fork a second docs system."""
    text = read_text("scripts/gen_docs.py")
    assert "gen_reference_docs" in text
    assert "gen_docs_index" in text
    assert "gen_llms_full" in text


def test_compatibility_matrix_stays_ungenerated_contributor_notes() -> None:
    """GREEN (D19): do not hand-edit compatibility-matrix.md into the six-axis page."""
    row = next(item for item in _pages() if item.get("path") == "docs/compatibility-matrix.md")
    assert row.get("generator") in (None, "null")
    text = read_text("docs/compatibility-matrix.md")
    lowered = text.casefold()
    missing = [axis for axis in _SIX_AXES if axis not in lowered]
    assert missing, (
        "docs/compatibility-matrix.md must not become the six-axis generated matrix; "
        f"unexpectedly covered {_SIX_AXES}"
    )


@_W82
def test_support_matrix_registered_in_manifest_as_generated() -> None:
    """Happy: the six-axis page is a manifest row with a non-null RD1 generator."""
    row = next(
        (item for item in _pages() if item.get("path") == _SUPPORT_MATRIX_PATH),
        None,
    )
    assert row is not None, f"docs/manifest.yaml missing {_SUPPORT_MATRIX_PATH}"
    assert row.get("generator") == _GENERATOR
    assert row.get("generator") not in (None, "null", "")


@_W82
def test_gen_docs_dispatches_support_matrix_generator() -> None:
    """Integration: ``scripts/gen_docs.py`` invokes the support-matrix generator."""
    text = read_text("scripts/gen_docs.py")
    assert "support-matrix" in text or "gen_support_matrix" in text
    assert "gen_reference_docs" in text


@_W82
def test_generated_support_matrix_covers_six_axes() -> None:
    """Happy: generated page names OS, SCM, languages, analyzers, providers, models."""
    path = REPO_ROOT / _SUPPORT_MATRIX_PATH
    assert path.is_file(), f"missing generated {_SUPPORT_MATRIX_PATH}"
    lowered = path.read_text(encoding="utf-8").casefold()
    missing = [axis for axis in _SIX_AXES if axis not in lowered]
    assert not missing, f"{_SUPPORT_MATRIX_PATH} missing axes: {missing}"


@_W82
def test_support_matrix_header_marks_generated_not_hand_edited() -> None:
    """Edge: the generated page must not be a hand-maintained table."""
    text = (REPO_ROOT / _SUPPORT_MATRIX_PATH).read_text(encoding="utf-8")
    collapsed = text.casefold()
    assert "generated" in collapsed
    assert "do not edit" in collapsed or "do not hand" in collapsed


@_W82
def test_docs_check_covers_support_matrix_via_gen_docs() -> None:
    """Functional: ``make docs-check`` already runs ``scripts/gen_docs.py --check``."""
    makefile = read_text("Makefile")
    assert "scripts/gen_docs.py --check" in makefile or "scripts/gen_docs.py" in makefile
    assert "docs-check" in makefile
    text = read_text("scripts/gen_docs.py")
    assert "--check" in text
    assert "support-matrix" in text or "gen_support_matrix" in text
