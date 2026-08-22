"""RV1.4 — authentication reference table contracts (RED until RV4).

Pins the recommended-model column, live slug discipline, the custom OpenAI-compatible
provider row, and parity between the Typer ``auth`` app and documented provider rows.
"""

from __future__ import annotations

import re

import pytest

from mergecraft.cli.auth_cmd import app as auth_app
from tests.ci.workflow_support import REPO_ROOT, read_text

README = REPO_ROOT / "README.md"
AUTH_DOC = REPO_ROOT / "docs" / "authentication.md"
COMPAT_MATRIX = REPO_ROOT / "docs" / "compatibility-matrix.md"

_AUTH_TABLE_REGION_RE = re.compile(
    r"^##\s+Authentication\s*\n(.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
_MODEL_SLUG = re.compile(r"`([a-z0-9]+/[a-z0-9._-]+)`", re.IGNORECASE)


def _auth_table_region(text: str) -> str | None:
    match = _AUTH_TABLE_REGION_RE.search(text)
    return match.group(1) if match else None


def _auth_subcommands() -> set[str]:
    names: set[str] = set()
    for command in auth_app.registered_commands:
        if command.hidden:
            continue
        assert command.name, "unnamed auth subcommand"
        names.add(command.name)
    return names


def _matrix_slugs() -> set[str]:
    text = COMPAT_MATRIX.read_text(encoding="utf-8")
    return {m.group(1) for m in _MODEL_SLUG.finditer(text)}


def _table_rows(region: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in region.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append(cells)
    return rows


@pytest.mark.xfail(reason="green after RV4: recommended-model column (A3)", strict=False)
def test_auth_table_has_recommended_model_column() -> None:
    readme_region = _auth_table_region(read_text("README.md"))
    assert readme_region is not None, "README missing ## Authentication section"
    header = next(
        (row for row in _table_rows(readme_region) if row[0].lower() == "provider"),
        None,
    )
    assert header is not None, "README auth table missing header row"
    joined = " ".join(header).lower()
    assert "recommended" in joined
    assert "model" in joined, "README auth table must add a Recommended model column (A3)"


@pytest.mark.xfail(reason="green after RV4: recommended slugs are live only", strict=False)
def test_recommended_slugs_are_real() -> None:
    readme_region = _auth_table_region(read_text("README.md"))
    assert readme_region is not None
    matrix_slugs = _matrix_slugs()
    invented: list[str] = []
    for row in _table_rows(readme_region):
        if row[0].lower() == "provider" or row[0].startswith("---"):
            continue
        for slug in _MODEL_SLUG.findall(" ".join(row)):
            if slug not in matrix_slugs:
                invented.append(slug)
    assert not invented, (
        f"recommended-model slugs must appear in docs/compatibility-matrix.md: {invented}"
    )


@pytest.mark.xfail(
    reason="green after RV4: custom OpenAI-compatible provider row (A3)",
    strict=False,
)
def test_custom_openai_compatible_row_present() -> None:
    readme_region = _auth_table_region(read_text("README.md"))
    assert readme_region is not None, "README missing ## Authentication section"
    haystack = readme_region + "\n" + AUTH_DOC.read_text(encoding="utf-8")
    assert "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL" in haystack
    assert "MERGECRAFT_CUSTOM_PROVIDER_API_KEY" in haystack
    table_rows = _table_rows(readme_region)
    custom_rows = [
        row
        for row in table_rows
        if "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL" in " ".join(row)
        or "openai-compatible" in " ".join(row).lower()
    ]
    assert custom_rows, (
        "README auth table must include an OpenAI-compatible custom provider row (A3)"
    )
    assert "docs/authentication.md" in read_text("README.md")


def test_every_auth_subcommand_has_a_row() -> None:
    readme_region = _auth_table_region(read_text("README.md"))
    assert readme_region is not None
    auth_doc_region = _auth_table_region(AUTH_DOC.read_text(encoding="utf-8"))
    documented = (readme_region + "\n" + (auth_doc_region or "")).lower()
    missing = sorted(
        name for name in _auth_subcommands() if f"mergecraft auth {name}" not in documented
    )
    assert not missing, f"auth tables missing rows for auth subcommands: {missing}"
