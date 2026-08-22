"""RV1.6 — ``mergecraft init`` scaffold contracts (RED until RV6).

Pins published Action ref, ``pull_request`` trigger, ``models`` list config, and pin
consistency across init output, ``defaults.yaml``, and the landing README.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from tests.ci.workflow_support import REPO_ROOT, read_text
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
DEFAULTS_YAML = REPO_ROOT / "scripts" / "example_workflows" / "defaults.yaml"
README = REPO_ROOT / "README.md"
_ACTION_USES = re.compile(r"uses:\s*alexhawat/mergeCraft@(\S+)", re.IGNORECASE)
_RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+(?:a\d+|b\d+|rc\d+)?$", re.IGNORECASE)


def _init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "init@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Init Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("init scaffold\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def _readme_example_one_ref() -> str | None:
    text = read_text("README.md")
    match = re.search(
        r"### Example 1[^\n]*\n(.*?)(?=\n### Example 2|\n## [^\#]|\Z)",
        text,
        re.DOTALL,
    )
    if not match:
        return None
    uses = _ACTION_USES.search(match.group(1))
    return uses.group(1).rstrip("#").strip() if uses else None


def _defaults_pin() -> str:
    data = yaml.safe_load(DEFAULTS_YAML.read_text(encoding="utf-8"))
    pin = data.get("action_pin_minimal")
    assert isinstance(pin, str), "defaults.yaml missing action_pin_minimal"
    return pin.strip()


def test_scaffolded_workflow_references_published_action(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output
    workflow = (tmp_path / ".github" / "workflows" / "mergecraft.yml").read_text(encoding="utf-8")
    assert "uses: ./" not in workflow, "init must not emit uses: ./ in consumer repos (V8)"
    assert "alexhawat/mergeCraft@" in workflow


def test_scaffolded_workflow_triggers_on_pull_request(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output
    workflow = (tmp_path / ".github" / "workflows" / "mergecraft.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s*pull_request\s*:", workflow, re.MULTILINE), (
        "init scaffold must include a pull_request trigger (D13)"
    )


def test_scaffolded_config_uses_models_list(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output
    config_path = tmp_path / ".mergecraft" / "config.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "models" in data
    assert isinstance(data["models"], list), (
        "init must scaffold models: list, not singular model: (D13)"
    )
    assert "model" not in data or data.get("model") is None


def test_scaffolded_workflow_pin_matches_defaults_yaml(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output
    workflow = (tmp_path / ".github" / "workflows" / "mergecraft.yml").read_text(encoding="utf-8")
    uses = _ACTION_USES.search(workflow)
    assert uses, "scaffolded workflow missing uses: alexhawat/mergeCraft@…"
    init_pin = uses.group(1).rstrip("#").strip()
    defaults_pin = _defaults_pin()
    readme_pin = _readme_example_one_ref()
    assert init_pin == defaults_pin, (
        f"init pin {init_pin!r} must match defaults.yaml {defaults_pin!r}"
    )
    if readme_pin is not None:
        assert init_pin == readme_pin, (
            f"init pin {init_pin!r} must match README Example 1 {readme_pin!r}"
        )
