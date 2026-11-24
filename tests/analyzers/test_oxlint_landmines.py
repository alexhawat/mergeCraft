"""Oxlint landmines opt-in: config detection, plan patching, and parser fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mergecraft.analyzers import oxlint_landmines
from mergecraft.analyzers.parsers.oxlint_json import parse_oxlint_json
from mergecraft.analyzers.registry import get_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.config.settings import AnalyzerOverride, AnalyzersSettings

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_LANDMINES_JSON = _FIXTURES / "native" / "oxlint-landmines-sample.json"
_BATCH_Y = _FIXTURES / "batch-y"


def _settings(*, landmines: bool | None) -> AnalyzersSettings:
    return AnalyzersSettings(
        overrides={"oxlint": AnalyzerOverride(landmines=landmines)},
    )


def test_landmines_opt_in_defaults_off() -> None:
    assert oxlint_landmines.landmines_opt_in(None) is False
    assert oxlint_landmines.landmines_opt_in(AnalyzersSettings()) is False
    assert oxlint_landmines.landmines_opt_in(_settings(landmines=False)) is False


def test_landmines_opt_in_explicit_true() -> None:
    assert oxlint_landmines.landmines_opt_in(_settings(landmines=True)) is True


def test_oxlint_config_uses_landmines_detects_extends(tmp_path: Path) -> None:
    (tmp_path / ".oxlintrc.json").write_text(
        json.dumps({"extends": ["./node_modules/@interfere/landmines/configs/recommended.json"]}),
        encoding="utf-8",
    )
    assert oxlint_landmines.oxlint_config_uses_landmines(tmp_path) is True


def test_oxlint_config_uses_landmines_detects_js_plugins(tmp_path: Path) -> None:
    (tmp_path / "oxlint.json").write_text(
        json.dumps(
            {
                "jsPlugins": [{"name": "landmines", "specifier": "@interfere/landmines"}],
            }
        ),
        encoding="utf-8",
    )
    assert oxlint_landmines.oxlint_config_uses_landmines(tmp_path) is True


def test_apply_oxlint_landmines_noop_when_repo_already_configured(tmp_path: Path) -> None:
    (tmp_path / ".oxlintrc.json").write_text(
        '{"extends":["./node_modules/@interfere/landmines/configs/recommended.json"]}\n',
        encoding="utf-8",
    )
    manifest = get_manifest("oxlint")
    plan = AnalyzerPlan(
        manifest_id="oxlint",
        mode="repo-native",
        argv=tuple(manifest.command),
    )
    scratch = tmp_path / "scratch"
    patched = oxlint_landmines.apply_oxlint_landmines(
        plan,
        repo_root=tmp_path,
        scratch_dir=scratch,
        analyzers_settings=_settings(landmines=True),
    )
    assert patched.argv == plan.argv
    assert "-c" not in patched.argv


def _landmines_toolchain_installed() -> bool:
    return oxlint_landmines.landmines_toolchain() is not None


@pytest.mark.skipif(
    not _landmines_toolchain_installed(),
    reason="scripts/node_modules oxlint + landmines not installed",
)
def test_apply_oxlint_landmines_injects_config(tmp_path: Path) -> None:
    manifest = get_manifest("oxlint")
    plan = AnalyzerPlan(
        manifest_id="oxlint",
        mode="repo-native",
        argv=tuple(manifest.command),
    )
    scratch = tmp_path / "scratch"
    patched = oxlint_landmines.apply_oxlint_landmines(
        plan,
        repo_root=tmp_path,
        scratch_dir=scratch,
        analyzers_settings=_settings(landmines=True),
    )
    assert patched.mode == "repo-native"
    assert "-c" in patched.argv
    config_path = patched.argv[patched.argv.index("-c") + 1]
    payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    assert "extends" in payload
    assert any("landmines" in entry for entry in payload["extends"])
    assert patched.config_note is not None
    assert "landmines" in patched.config_note.casefold()


def test_oxlint_landmines_parser_maps_rules_and_help(tmp_path: Path) -> None:
    manifest = get_manifest("oxlint")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "widget.test.ts").write_text("// fixture\n", encoding="utf-8")
    raw = _LANDMINES_JSON.read_text(encoding="utf-8")
    findings = parse_oxlint_json(raw, manifest=manifest, repo_root=tmp_path)
    assert len(findings) == 3
    by_rule = {finding.rule_id: finding for finding in findings}
    sleep = by_rule["landmines/no-fixed-sleep"]
    assert sleep.severity == "Major"
    assert "Await the operation" in sleep.message
    assert sleep.start_line == 4
    mock = by_rule["landmines/no-test-doubles"]
    assert "MSW" in mock.message


def test_batch_y_js_oxlint_landmines_fixture_tree_exists() -> None:
    repo = _BATCH_Y / "js-oxlint-landmines"
    assert (repo / "src" / "widget.test.ts").is_file()
    assert (repo / "package.json").is_file()
