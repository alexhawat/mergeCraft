"""``mergecraft opencode install|doctor`` — asset copy, config patch, diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mergecraft.cli import opencode_cmd
from mergecraft.cli.app import app
from mergecraft.config.io import load_config_dict

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()


def _seed_repo(tmp_path: Path) -> Path:
    config_dir = tmp_path / ".mergecraft"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text("models:\n- anthropic/claude-sonnet\n", encoding="utf-8")
    return config_path


def test_assets_root_resolves_from_source_checkout() -> None:
    root = opencode_cmd.assets_root()
    assert (root / "commands" / "mergecraft" / "review.md").is_file()
    assert (root / "agents" / "mergecraft" / "reviewer.md").is_file()


def test_install_copies_assets_writes_config_and_sets_harness(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = _seed_repo(tmp_path)

    result = runner.invoke(app, ["opencode", "install"])

    assert result.exit_code == 0, result.output
    opencode = tmp_path / ".opencode"
    assert (opencode / "commands" / "mergecraft" / "review-deep.md").is_file()
    assert (opencode / "agents" / "mergecraft" / "reviewer.md").is_file()
    assert (opencode / "plugins" / "mergecraft" / "index.ts").is_file()

    payload = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert payload["mcp"]["servers"]["mergecraft"]["type"] == "local"
    assert payload["mcp"]["servers"]["mergecraft"]["command"][0] == "mergecraft"
    assert load_config_dict(config_path)["harness"] == "opencode"


def test_install_is_idempotent_and_force_refreshes(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_repo(tmp_path)
    first = runner.invoke(app, ["opencode", "install"])
    assert first.exit_code == 0
    marker = tmp_path / ".opencode" / "commands" / "mergecraft" / "review.md"
    marker.write_text("stale\n", encoding="utf-8")

    second = runner.invoke(app, ["opencode", "install"])
    assert second.exit_code == 0
    assert marker.read_text(encoding="utf-8") == "stale\n"

    forced = runner.invoke(app, ["opencode", "install", "--force"])
    assert forced.exit_code == 0
    assert marker.read_text(encoding="utf-8") != "stale\n"


def test_install_patches_existing_strict_json_config(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_repo(tmp_path)
    existing = tmp_path / ".opencode" / "opencode.json"
    existing.parent.mkdir(parents=True)
    existing.write_text(json.dumps({"$schema": "x", "model": "anthropic/claude"}), encoding="utf-8")

    result = runner.invoke(app, ["opencode", "install"])
    assert result.exit_code == 0
    payload = json.loads(existing.read_text(encoding="utf-8"))
    assert payload["model"] == "anthropic/claude"
    assert payload["mcp"]["servers"]["mergecraft"]["type"] == "local"


def test_install_patches_project_root_json_config(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_repo(tmp_path)
    root_config = tmp_path / "opencode.json"
    root_config.write_text(
        json.dumps({"$schema": "x", "model": "anthropic/claude"}), encoding="utf-8"
    )

    result = runner.invoke(app, ["opencode", "install"])

    assert result.exit_code == 0, result.output
    payload = json.loads(root_config.read_text(encoding="utf-8"))
    assert payload["model"] == "anthropic/claude"
    assert payload["mcp"]["servers"]["mergecraft"]["type"] == "local"
    assert not (tmp_path / ".opencode" / "opencode.json").exists()


def test_install_leaves_project_root_jsonc_and_creates_no_shadow(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_repo(tmp_path)
    original = '{\n  // keep me\n  "model": "anthropic/claude"\n}\n'
    root_config = tmp_path / "opencode.jsonc"
    root_config.write_text(original, encoding="utf-8")

    result = runner.invoke(app, ["opencode", "install"])

    assert result.exit_code == 0
    assert root_config.read_text(encoding="utf-8") == original
    assert not (tmp_path / ".opencode" / "opencode.json").exists()
    assert not (tmp_path / ".opencode" / "opencode.jsonc").exists()


def test_install_leaves_jsonc_comments_intact(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_repo(tmp_path)
    original = '{\n  // keep me\n  "model": "anthropic/claude"\n}\n'
    jsonc = tmp_path / "opencode.jsonc"
    jsonc.write_text(original, encoding="utf-8")

    result = runner.invoke(app, ["opencode", "install"])
    assert result.exit_code == 0
    assert jsonc.read_text(encoding="utf-8") == original
    # The manual snippet is offered instead of rewriting JSONC.
    snippet = opencode_cmd._mcp_snippet(jsonc)
    assert '"mcp"' in snippet
    assert '"servers"' in snippet
    assert "mergecraft" in snippet


def test_install_global_uses_home_config(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    _seed_repo(tmp_path)

    result = runner.invoke(app, ["opencode", "install", "--global"])
    assert result.exit_code == 0
    home_opencode = tmp_path / ".config" / "opencode"
    assert (home_opencode / "commands" / "mergecraft" / "review.md").is_file()
    assert (home_opencode / "opencode.json").is_file()
    # --global must not touch the project harness.
    assert load_config_dict(tmp_path / ".mergecraft" / "config.yaml").get("harness") is None


def test_install_without_repo_config_hints_init(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["opencode", "install"])
    assert result.exit_code == 0
    assert "mergecraft init" in result.output


def test_install_no_router_skips_harness_patch(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = _seed_repo(tmp_path)
    result = runner.invoke(app, ["opencode", "install", "--no-router"])
    assert result.exit_code == 0
    assert load_config_dict(config_path).get("harness") is None


def test_doctor_strict_fails_when_unwired(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["opencode", "doctor", "--strict"])
    assert result.exit_code == 1
    assert "missing" in result.output


def test_doctor_succeeds_after_install(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_repo(tmp_path)
    assert runner.invoke(app, ["opencode", "install"]).exit_code == 0
    monkeypatch.setattr(
        opencode_cmd.shutil,
        "which",
        lambda name: "/usr/local/bin/mergecraft" if name == "mergecraft" else None,
    )
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "pylf_v2_us_test")

    result = runner.invoke(app, ["opencode", "doctor", "--strict"])

    assert result.exit_code == 0, result.output
    assert "all checks passed" in result.output


def test_install_honors_target(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    project = tmp_path / "consumer"
    (project / ".mergecraft").mkdir(parents=True)
    (project / ".mergecraft" / "config.yaml").write_text(
        "models:\n- anthropic/claude-sonnet\n", encoding="utf-8"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = runner.invoke(app, ["opencode", "install", "--target", str(project)])

    assert result.exit_code == 0, result.output
    assert (project / ".opencode" / "commands" / "mergecraft" / "review.md").is_file()
    assert (project / "opencode.json").is_file()
    assert load_config_dict(project / ".mergecraft" / "config.yaml")["harness"] == "opencode"
    assert not (elsewhere / ".opencode").exists()


def test_doctor_honors_target(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    project = tmp_path / "consumer"
    (project / ".mergecraft").mkdir(parents=True)
    (project / ".mergecraft" / "config.yaml").write_text(
        "models:\n- anthropic/claude-sonnet\n", encoding="utf-8"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert runner.invoke(app, ["opencode", "install", "--target", str(project)]).exit_code == 0
    monkeypatch.setattr(
        opencode_cmd.shutil,
        "which",
        lambda name: "/usr/local/bin/mergecraft" if name == "mergecraft" else None,
    )
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "pylf_v2_us_test")

    result = runner.invoke(app, ["opencode", "doctor", "--target", str(project), "--strict"])

    assert result.exit_code == 0, result.output
