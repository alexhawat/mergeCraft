"""SARIF 2.1.0 ingest and export (D3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.analyzers.support import FIXTURES_DIR, import_module


@pytest.mark.parametrize(
    "fixture_name",
    [
        "sarif/actionlint-minimal.sarif.json",
        "sarif/zizmor-minimal.sarif.json",
        "sarif/hadolint-minimal.sarif.json",
    ],
)
def test_ingest_recorded_sarif_fixtures(fixture_name: str) -> None:
    sarif = import_module("mergecraft.analyzers.parsers.sarif")
    manifest = import_module("mergecraft.analyzers.manifest")
    raw = (FIXTURES_DIR / fixture_name).read_text(encoding="utf-8")
    tool = fixture_name.split("/")[1].split("-")[0]
    m = manifest.load_manifest_file(Path(f"src/mergecraft/analyzers/catalog/{tool}.yaml"))
    findings = sarif.parse_sarif(raw, manifest=m, repo_root=Path("."))
    assert len(findings) >= 1
    assert all(f.source == "analyzer" for f in findings)


def test_sarif_level_maps_to_taxonomy_severity() -> None:
    sarif = import_module("mergecraft.analyzers.parsers.sarif")
    manifest = import_module("mergecraft.analyzers.manifest")
    raw = (FIXTURES_DIR / "sarif/actionlint-minimal.sarif.json").read_text(encoding="utf-8")
    m = manifest.load_manifest_file(
        Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml")
    )
    findings = sarif.parse_sarif(raw, manifest=m, repo_root=Path("."))
    assert findings[0].severity == "Major"


def test_artifact_location_resolves_to_repo_relative_path() -> None:
    sarif = import_module("mergecraft.analyzers.parsers.sarif")
    manifest = import_module("mergecraft.analyzers.manifest")
    raw = (FIXTURES_DIR / "sarif/hadolint-minimal.sarif.json").read_text(encoding="utf-8")
    m = manifest.load_manifest_file(
        Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml")
    )
    findings = sarif.parse_sarif(raw, manifest=m, repo_root=Path("."))
    assert findings[0].path == "Dockerfile"


_MINIMAL_RUNS = [
    {
        "tool": {
            "driver": {
                "name": "actionlint",
                "rules": [{"id": "syntax-check", "defaultConfiguration": {"level": "error"}}],
            }
        },
        "results": [
            {
                "ruleId": "syntax-check",
                "level": "error",
                "message": {"text": "unexpected key"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": ".github/workflows/broken.yml",
                                "uriBaseId": "%SRCROOT%",
                            },
                            "region": {"startLine": 2, "endLine": 2},
                        }
                    }
                ],
            }
        ],
    }
]


def _sarif_document(*, version: str | None, runs: list[object]) -> str:
    document: dict[str, object] = {"runs": runs}
    if version is not None:
        document["version"] = version
    return json.dumps(document)


def _parse_sarif_raw(raw: str):
    sarif = import_module("mergecraft.analyzers.parsers.sarif")
    manifest = import_module("mergecraft.analyzers.manifest")
    m = manifest.load_manifest_file(
        Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml")
    )
    return sarif.parse_sarif(raw, manifest=m, repo_root=Path("."))


@pytest.mark.xfail(reason="green after TP4: reject SARIF 2.0.0 with runs", strict=False)
def test_sarif_2_0_0_with_nonempty_runs_raises_unsupported_version() -> None:
    raw = _sarif_document(version="2.0.0", runs=_MINIMAL_RUNS)
    with pytest.raises(ValueError, match="unsupported SARIF version"):
        _parse_sarif_raw(raw)


def test_sarif_2_1_0_with_same_runs_parses() -> None:
    raw = _sarif_document(version="2.1.0", runs=_MINIMAL_RUNS)
    findings = _parse_sarif_raw(raw)
    assert len(findings) >= 1
    assert findings[0].severity == "Major"


def test_sarif_2_1_0_with_empty_runs_returns_no_findings() -> None:
    raw = _sarif_document(version="2.1.0", runs=[])
    assert _parse_sarif_raw(raw) == []


@pytest.mark.xfail(reason="green after TP4: reject missing SARIF version", strict=False)
def test_sarif_missing_version_raises_unsupported_version() -> None:
    raw = _sarif_document(version=None, runs=_MINIMAL_RUNS)
    with pytest.raises(ValueError, match="unsupported SARIF version"):
        _parse_sarif_raw(raw)


def test_export_round_trips_to_valid_sarif() -> None:
    sarif_mod = import_module("mergecraft.analyzers.sarif")
    finding_mod = import_module("mergecraft.analyzers.finding")
    sample = finding_mod.make_finding(
        tool="actionlint",
        rule_id="syntax-check",
        category="Maintainability & Code Quality",
        severity="Major",
        confidence="certain",
        message="broken workflow",
        path=".github/workflows/broken.yml",
        start_line=2,
        end_line=2,
        source="analyzer",
    )
    exported = sarif_mod.export_sarif([sample])
    sarif_mod.validate_sarif_document(exported)
