"""Verification honors the named workspace across actual startup and policy."""

from __future__ import annotations

import asyncio
import json
import shlex
import sys
import time
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.verify.runner import run_verify_behavior
from tests.verify.fake_driver import FakeBrowserDriver
from tests.verify.support import make_input


async def test_relative_start_command_runs_in_named_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller, target = tmp_path / "caller", tmp_path / "target"
    script = "from pathlib import Path\nPath('started').write_text(str(Path.cwd()))\n"
    for root in (caller, target):
        root.mkdir()
        (root / "app.py").write_text(script, encoding="utf-8")
    monkeypatch.chdir(caller)

    class WaitingDriver(FakeBrowserDriver):
        async def navigate(self, url: str) -> None:
            def wait_for_start() -> None:
                deadline = time.monotonic() + 3
                while not any((root / "started").exists() for root in (caller, target)):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("fixture application did not start")
                    time.sleep(0.01)

            await asyncio.to_thread(wait_for_start)
            await super().navigate(url)

    await run_verify_behavior(
        make_input(
            repo_path="../target",
            startup_command=shlex.join([sys.executable, "app.py"]),
            credential_env_names=[],
            acceptance_criteria=[],
            artifacts_dir="",
        ),
        driver=WaitingDriver(),
        offline=True,
        shell="enabled",
    )

    assert (target / "started").read_text(encoding="utf-8") == str(target.resolve())
    assert not (caller / "started").exists()
    assert Path.cwd() == caller


@pytest.mark.parametrize(
    ("target_policy", "reason"),
    [
        ("shell: disabled\n", "shell disabled"),
        ("shell: enabled\nverify_behavior:\n  enabled: false\n", "enabled is false"),
    ],
)
def test_target_policy_blocks_before_browser_or_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_policy: str,
    reason: str,
) -> None:
    caller, target = tmp_path / "caller", tmp_path / "target"
    for root, policy in (
        (caller, "shell: enabled\nverify_behavior:\n  enabled: true\n"),
        (target, target_policy),
    ):
        config = root / ".mergecraft"
        config.mkdir(parents=True)
        (config / "config.yaml").write_text(policy, encoding="utf-8")
    monkeypatch.chdir(caller)
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    artifacts = tmp_path / "artifacts"
    spec = make_input(repo_path="../target", artifacts_dir=str(artifacts), credential_env_names=[])
    input_path = tmp_path / "input.yaml"
    input_path.write_text(yaml.safe_dump(spec.model_dump(mode="json")), encoding="utf-8")

    def unexpected_driver(**kwargs: object) -> None:
        raise AssertionError("target policy must block before acquiring a browser")

    monkeypatch.setattr("mergecraft.cli.verify_behavior_cmd._resolve_driver", unexpected_driver)
    result = CliRunner().invoke(app, ["verify-behavior", "--input", str(input_path)])

    assert result.exit_code == 1, result.output
    report = json.loads((artifacts / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "skipped"
    assert any(reason in item for item in report["skipped_or_unverified"])
    assert Path.cwd() == caller


def test_missing_repository_is_a_named_input_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    spec = make_input(repo_path="missing", startup_command="", credential_env_names=[])
    input_path = tmp_path / "input.yaml"
    input_path.write_text(yaml.safe_dump(spec.model_dump(mode="json")), encoding="utf-8")
    result = CliRunner().invoke(app, ["verify-behavior", "--input", str(input_path)])
    assert result.exit_code == 2, result.output
    assert "repo_path" in result.output
    assert "does not exist" in result.output
