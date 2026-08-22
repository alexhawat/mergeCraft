"""RV1.4 — authentication reference table contracts (green after RV4).

Pins the recommended-model column, live slug discipline, the custom OpenAI-compatible
provider row, and parity between the Typer ``auth`` app and documented provider rows.
"""

from __future__ import annotations

import re

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


def _auth_doc_table_text() -> str:
    return AUTH_DOC.read_text(encoding="utf-8")


def _provider_table_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    in_provider = False
    for line in _auth_doc_table_text().splitlines():
        if not line.strip().startswith("|"):
            if in_provider:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= {"-", ":"}:
            continue
        if cells[0].lower() == "provider":
            in_provider = True
            rows = [cells]
            continue
        if in_provider:
            rows.append(cells)
    return rows


def _recommended_model_column_index(header: list[str]) -> int:
    for idx, cell in enumerate(header):
        lowered = cell.lower()
        if "recommended" in lowered and "model" in lowered:
            return idx
    msg = "provider table missing Recommended model column"
    raise AssertionError(msg)


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


def test_auth_table_has_recommended_model_column() -> None:
    rows = _provider_table_rows()
    assert rows, "docs/authentication.md provider table missing header row"
    header = rows[0]
    joined = " ".join(header).lower()
    assert "recommended" in joined
    assert "model" in joined, "auth reference must add a Recommended model column (A3)"


def test_recommended_slugs_are_real() -> None:
    rows = _provider_table_rows()
    assert rows, "docs/authentication.md provider table missing"
    model_col = _recommended_model_column_index(rows[0])
    matrix_slugs = _matrix_slugs()
    invented: list[str] = []
    for row in rows[1:]:
        if len(row) <= model_col:
            continue
        for slug in _MODEL_SLUG.findall(row[model_col]):
            if slug not in matrix_slugs:
                invented.append(slug)
    assert not invented, (
        f"recommended-model slugs must appear in docs/compatibility-matrix.md: {invented}"
    )


def test_custom_openai_compatible_row_present() -> None:
    table_rows = _provider_table_rows()
    haystack = _auth_doc_table_text()
    assert "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL" in haystack
    assert "MERGECRAFT_CUSTOM_PROVIDER_API_KEY" in haystack
    custom_rows = [
        row
        for row in table_rows
        if "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL" in " ".join(row)
        or "openai-compatible" in " ".join(row).lower()
    ]
    assert custom_rows, (
        "docs/authentication.md must include an OpenAI-compatible custom provider row (A3)"
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
