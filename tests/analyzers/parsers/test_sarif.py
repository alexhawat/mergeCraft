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


# --------------------------------------------------------------------------- #
# A URI that cannot be mapped into the repo must be labelled as such, never
# shortened into a plausible-looking file that happens to exist at the root.
# --------------------------------------------------------------------------- #

_OUTSIDE_LABEL = "outside repository root"
_ACTIONLINT_MANIFEST = Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml")


def _sarif_document(uri: str, *, uri_base_id: str | None = None) -> str:
    artifact: dict[str, str] = {"uri": uri}
    if uri_base_id is not None:
        artifact["uriBaseId"] = uri_base_id
    return json.dumps(
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "actionlint"}},
                    "results": [
                        {
                            "ruleId": "syntax-check",
                            "level": "warning",
                            "message": {"text": "outside-root fixture"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": artifact,
                                        "region": {"startLine": 3},
                                    }
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def _actionlint_manifest() -> object:
    manifest = import_module("mergecraft.analyzers.manifest")
    return manifest.load_manifest_file(_ACTIONLINT_MANIFEST)


def test_file_uri_outside_the_root_is_not_shortened_to_a_basename(tmp_path: Path) -> None:
    """The basename of an out-of-root ``file://`` can be a real, unrelated file."""
    sarif = import_module("mergecraft.analyzers.parsers.sarif")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README").write_text("a real file at the repo root\n", encoding="utf-8")

    findings = sarif.parse_sarif(
        _sarif_document("file:///etc/README"),
        manifest=_actionlint_manifest(),
        repo_root=repo_root,
    )

    assert findings[0].path != "README"
    assert any(_OUTSIDE_LABEL in line for line in findings[0].evidence)


def test_bare_absolute_path_outside_the_root_keeps_its_path_and_is_labelled(
    tmp_path: Path,
) -> None:
    """A runner path is kept verbatim and labelled, never stripped of its prefix."""
    sarif = import_module("mergecraft.analyzers.parsers.sarif")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    uri = "/home/runner/work/mergeCraft/mergeCraft/README"

    findings = sarif.parse_sarif(
        _sarif_document(uri), manifest=_actionlint_manifest(), repo_root=repo_root
    )

    assert findings[0].path == uri
    assert any(_OUTSIDE_LABEL in line for line in findings[0].evidence)


def test_srcroot_escape_error_names_the_uri(tmp_path: Path) -> None:
    """The rejection is correct; the message must say which URI caused it."""
    sarif = import_module("mergecraft.analyzers.parsers.sarif")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    with pytest.raises(ValueError, match=r"passwd") as exc_info:
        sarif.parse_sarif(
            _sarif_document("../../etc/passwd", uri_base_id="%SRCROOT%"),
            manifest=_actionlint_manifest(),
            repo_root=repo_root,
        )

    assert "../../etc/passwd" in str(exc_info.value)


def test_file_uri_inside_the_root_still_resolves_repo_relative(tmp_path: Path) -> None:
    """A path that does map into the repo keeps resolving to its relative form."""
    sarif = import_module("mergecraft.analyzers.parsers.sarif")
    repo_root = tmp_path / "repo"
    target = repo_root / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n", encoding="utf-8")

    findings = sarif.parse_sarif(
        _sarif_document(f"file://{target}"),
        manifest=_actionlint_manifest(),
        repo_root=repo_root,
    )

    assert findings[0].path == "src/app.py"
