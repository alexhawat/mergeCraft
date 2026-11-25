"""Oxlint landmines opt-in: config detection, plan patching, and parser fixtures."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mergecraft.analyzers import oxlint_landmines
from mergecraft.analyzers.parsers.oxlint_json import parse_oxlint_json
from mergecraft.analyzers.registry import get_manifest
from mergecraft.analyzers.resolve import FILES_TOKEN, AnalyzerPlan
from mergecraft.config.settings import AnalyzerOverride, AnalyzersSettings

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_LANDMINES_JSON = _FIXTURES / "native" / "oxlint-landmines-sample.json"
_BATCH_Y = _FIXTURES / "batch-y"


def _landmines_toolchain_installed() -> bool:
    return oxlint_landmines.landmines_toolchain() is not None


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


def test_inject_config_pins_recommended_rules_over_the_repo_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".oxlintrc.json").write_text("{}\n", encoding="utf-8")
    recommended = tmp_path / "recommended.json"
    recommended.write_text(
        json.dumps({"rules": {"landmines/no-fixed-sleep": "error"}}), encoding="utf-8"
    )
    out = oxlint_landmines.write_landmines_inject_config(
        scratch_dir=tmp_path / "scratch", repo_root=repo, landmines_recommended=recommended
    )
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "extends": [str((repo / ".oxlintrc.json").resolve()), str(recommended.resolve())],
        "overrides": [{"files": ["**/*"], "rules": {"landmines/no-fixed-sleep": "error"}}],
    }


def _apply(repo: Path, scratch: Path) -> AnalyzerPlan:
    return oxlint_landmines.apply_oxlint_landmines(
        AnalyzerPlan(
            manifest_id="oxlint",
            mode="repo-native",
            argv=tuple(get_manifest("oxlint").command),
        ),
        repo_root=repo,
        scratch_dir=scratch,
        analyzers_settings=_settings(landmines=True),
    )


_PLUGIN = [{"name": "landmines", "specifier": "@interfere/landmines"}]
_OFF = {"landmines/no-fixed-sleep": "off"}


@pytest.mark.skipif(
    not _landmines_toolchain_installed(),
    reason="scripts/node_modules oxlint + landmines not installed",
)
@pytest.mark.parametrize(
    "repo_config",
    [
        {},
        {"rules": _OFF},
        {"jsPlugins": _PLUGIN, "rules": _OFF},
        {"extends": ["./node_modules/@interfere/landmines/configs/recommended.json"]},
        {
            "extends": ["./node_modules/@interfere/landmines/configs/recommended.json"],
            "rules": _OFF,
        },
        {"overrides": [{"files": ["**/*.test.ts"], "rules": _OFF}]},
        {"overrides": [{"files": ["*"], "jsPlugins": _PLUGIN, "rules": _OFF}]},
        {"ignorePatterns": ["**/*.test.ts"]},
    ],
)
def test_repo_config_cannot_turn_injected_landmines_off(
    tmp_path: Path, repo_config: dict[str, object]
) -> None:
    toolchain = oxlint_landmines.landmines_toolchain()
    assert toolchain is not None
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "node_modules").symlink_to(toolchain[1].parents[3], target_is_directory=True)
    (repo / ".oxlintrc.json").write_text(json.dumps(repo_config), encoding="utf-8")
    target = repo / "src" / "widget.test.ts"
    target.write_text(
        'import { test } from "vitest";\n'
        'test("x", async () => {\n'
        "  await new Promise((r) => setTimeout(r, 500));\n"
        "});\n",
        encoding="utf-8",
    )
    patched = _apply(repo, tmp_path / "scratch")
    assert patched.mode == "repo-native", patched.reason
    argv = [str(target) if arg == FILES_TOKEN else arg for arg in patched.argv]
    run = subprocess.run(argv, cwd=repo, capture_output=True, text=True, check=False, timeout=60)
    codes = {item["code"] for item in json.loads(run.stdout)["diagnostics"]}
    assert "landmines(no-fixed-sleep)" in codes


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
