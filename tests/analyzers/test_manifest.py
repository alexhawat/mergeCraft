"""Manifest schema validation (D1, D2, D7, D10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import MANIFEST_FIXTURES, import_module

pytestmark = pytest.mark.xfail(reason="green after W2: manifest schema", strict=False)


def test_valid_manifest_round_trips_yaml() -> None:
    manifest_mod = import_module("mergecraft.analyzers.manifest")
    raw = (MANIFEST_FIXTURES / "valid-actionlint.yaml").read_text(encoding="utf-8")
    parsed = manifest_mod.load_manifest_yaml(raw)
    assert parsed.id == "actionlint"
    assert parsed.trust == "untrusted"
    assert parsed.severity_map["error"] == "Major"
    dumped = manifest_mod.dump_manifest_yaml(parsed)
    reparsed = manifest_mod.load_manifest_yaml(dumped)
    assert reparsed.model_dump() == parsed.model_dump()


def test_unknown_top_level_key_rejected() -> None:
    manifest_mod = import_module("mergecraft.analyzers.manifest")
    raw = (MANIFEST_FIXTURES / "valid-actionlint.yaml").read_text(encoding="utf-8")
    with pytest.raises(manifest_mod.ManifestValidationError, match="extra"):
        manifest_mod.load_manifest_yaml(raw + "\nunexpectedKey: true\n")


@pytest.mark.parametrize(
    ("severity_key", "taxonomy_value"),
    [
        ("error", "Major"),
        ("warning", "Minor"),
        ("note", "Trivial"),
    ],
)
def test_severity_map_values_must_be_taxonomy_members(
    severity_key: str, taxonomy_value: str
) -> None:
    manifest_mod = import_module("mergecraft.analyzers.manifest")
    base = (MANIFEST_FIXTURES / "valid-actionlint.yaml").read_text(encoding="utf-8")
    manifest = manifest_mod.load_manifest_yaml(base)
    assert manifest.severity_map[severity_key] == taxonomy_value


def test_unmapped_analyzer_severity_is_validation_error_not_default() -> None:
    manifest_mod = import_module("mergecraft.analyzers.manifest")
    raw = (MANIFEST_FIXTURES / "invalid-unmapped-severity.yaml").read_text(encoding="utf-8")
    with pytest.raises(manifest_mod.ManifestValidationError, match=r"banana|severity_map"):
        manifest_mod.load_manifest_yaml(raw)


def test_provenance_requires_sha256_per_declared_platform() -> None:
    manifest_mod = import_module("mergecraft.analyzers.manifest")
    raw = (MANIFEST_FIXTURES / "valid-actionlint.yaml").read_text(encoding="utf-8")
    manifest = manifest_mod.load_manifest_yaml(raw.replace("sha256:", 'sha256: ""'))
    with pytest.raises(manifest_mod.ManifestValidationError, match=r"sha256|provenance"):
        manifest_mod.validate_manifest(manifest)


@pytest.mark.parametrize("trust", ["trusted", "untrusted"])
def test_trust_must_be_known_tier(trust: str) -> None:
    manifest_mod = import_module("mergecraft.analyzers.manifest")
    raw = (MANIFEST_FIXTURES / "valid-actionlint.yaml").read_text(encoding="utf-8")
    manifest = manifest_mod.load_manifest_yaml(raw.replace("trust: untrusted", f"trust: {trust}"))
    manifest_mod.validate_manifest(manifest)


def test_unknown_trust_tier_rejected() -> None:
    manifest_mod = import_module("mergecraft.analyzers.manifest")
    raw = (MANIFEST_FIXTURES / "valid-actionlint.yaml").read_text(encoding="utf-8")
    with pytest.raises(manifest_mod.ManifestValidationError, match="trust"):
        manifest_mod.load_manifest_yaml(raw.replace("trust: untrusted", "trust: superuser"))


def test_catalog_yaml_files_round_trip_at_runtime() -> None:
    manifest_mod = import_module("mergecraft.analyzers.manifest")
    catalog_dir = Path("src/mergecraft/analyzers/catalog")
    yaml_files = sorted(catalog_dir.glob("*.yaml"))
    assert yaml_files, "catalog must ship at least one manifest after W2"
    for path in yaml_files:
        parsed = manifest_mod.load_manifest_file(path)
        manifest_mod.validate_manifest(parsed)
        assert parsed.id
