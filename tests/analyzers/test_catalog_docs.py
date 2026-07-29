"""C6 catalog documentation enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import CATALOG_ANALYZER_IDS, import_module

REPO_ROOT = Path(__file__).resolve().parents[2]


def _catalog_manifests():
    registry = import_module("mergecraft.analyzers.registry")
    return registry.load_catalog()


def test_every_manifest_has_analyzers_doc_row() -> None:
    docs = import_module("mergecraft.analyzers.catalog_docs")
    analyzers_md = REPO_ROOT / "docs" / "ANALYZERS.md"
    assert analyzers_md.is_file(), "docs/ANALYZERS.md must exist (C6.6)"

    doc_ids = docs.parse_analyzers_doc(analyzers_md)
    catalog_ids = {m.id for m in _catalog_manifests()}
    missing = sorted(catalog_ids - doc_ids)
    assert not missing, f"manifests missing ANALYZERS.md rows: {missing}"


def test_every_manifest_has_fixture() -> None:
    docs = import_module("mergecraft.analyzers.catalog_docs")
    fixture_root = REPO_ROOT / "tests" / "analyzers" / "fixtures"

    for manifest in _catalog_manifests():
        assert docs.manifest_has_fixture(manifest, fixture_root=fixture_root), (
            f"{manifest.id} must have a test fixture (C5/C6)"
        )


def test_every_manifest_has_complete_severity_map() -> None:
    docs = import_module("mergecraft.analyzers.catalog_docs")

    for manifest in _catalog_manifests():
        assert docs.severity_map_complete(manifest), (
            f"{manifest.id} severity_map must cover every native level (C5/C6)"
        )


def test_catalog_analyzers_include_planned_expansion_ids() -> None:
    catalog_ids = {m.id for m in _catalog_manifests()}
    missing = sorted(set(CATALOG_ANALYZER_IDS) - catalog_ids)
    assert not missing, f"catalog expansion manifests not yet present: {missing}"


def test_manifest_missing_fixture_fails_ci_gate(tmp_path: Path) -> None:
    docs = import_module("mergecraft.analyzers.catalog_docs")
    bad_manifest = tmp_path / "orphan.yaml"
    bad_manifest.write_text(
        "id: orphan-tool\ncategory: lint\nlanguages: [python]\n"
        "detect:\n  files: ['*.py']\ncommand: ['true']\n"
        "scope: diff\nparser: ruff_json\nsupports_fix: false\n"
        "default_enabled: false\nversion: '0.0.0'\nruntime: repo-native\n"
        "timeout_s: 60\ntrust: trusted\nseverity_map:\n  error: Major\n"
        "  warning: Minor\nprovenance: {}\nnetwork_allowlist: []\n",
        encoding="utf-8",
    )
    with pytest.raises(docs.CatalogIntegrityError, match="fixture"):
        docs.validate_manifest_ship_gate(bad_manifest, fixture_root=tmp_path)
