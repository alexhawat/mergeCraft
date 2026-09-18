"""``mergecraft verify-behavior`` flag surface and mode entry points."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from mergecraft.cli import verify_behavior_cmd
from mergecraft.cli.app import app
from tests.verify.fake_driver import FakeBrowserDriver
from tests.verify.support import CLI_FLAGS, SAMPLE_YAML_INPUT

if TYPE_CHECKING:
    from collections.abc import Iterator

_RUNNER = CliRunner()


@pytest.fixture(autouse=True)
def _browser_stack_unavailable() -> Iterator[None]:
    """These cases pin the fail-closed path, not a live browser-use launch."""
    with patch("mergecraft.browser.launch.browser_stack_available", return_value=False):
        yield


def test_verify_behavior_is_registered() -> None:
    result = _RUNNER.invoke(app, ["verify-behavior", "--help"])
    assert result.exit_code == 0
    assert "verify-behavior" in result.stdout or "reproduce" in result.stdout.lower()


def test_cli_exposes_issue_61_flags_plus_absorbed_extras() -> None:
    result = _RUNNER.invoke(app, ["verify-behavior", "--help"])
    assert result.exit_code == 0
    text = result.stdout
    for flag in CLI_FLAGS:
        assert flag in text, flag


def test_cli_verify_mode_errors_when_browser_stack_unavailable(tmp_path: Path) -> None:
    artifacts = tmp_path / "arts"
    criteria = tmp_path / "criteria.md"
    criteria.write_text("- Clear button removes the image\n", encoding="utf-8")
    result = _RUNNER.invoke(
        app,
        [
            "verify-behavior",
            "--mode",
            "verify",
            "--url",
            "http://127.0.0.1:8765/",
            "--criteria-file",
            str(criteria),
            "--artifacts-dir",
            str(artifacts),
            "--start-command",
            "true",
        ],
    )
    combined = f"{result.stdout}\n{result.stderr}\n{result.exception}"
    assert result.exit_code != 0
    assert "browser-use" in combined.lower() or "cdp" in combined.lower()
    assert "pass" not in result.stdout.lower()


def test_cli_allow_stub_writes_a_report(tmp_path: Path) -> None:
    artifacts = tmp_path / "arts"
    criteria = tmp_path / "criteria.md"
    criteria.write_text("- stub page is visible\n", encoding="utf-8")
    result = _RUNNER.invoke(
        app,
        [
            "verify-behavior",
            "--mode",
            "verify",
            "--url",
            "http://127.0.0.1:8765/",
            "--criteria-file",
            str(criteria),
            "--artifacts-dir",
            str(artifacts),
            "--allow-stub",
        ],
    )
    assert result.exit_code in {0, 1}
    assert list(artifacts.rglob("*.json"))


def test_cli_reproduce_mode_accepts_issue_file(tmp_path: Path) -> None:
    issue = tmp_path / "issue.md"
    issue.write_text("## Repro\n1. Open upload\n2. Click Clear\n", encoding="utf-8")
    artifacts = tmp_path / "arts"
    result = _RUNNER.invoke(
        app,
        [
            "verify-behavior",
            "--mode",
            "reproduce",
            "--url",
            "http://127.0.0.1:8765/",
            "--issue-file",
            str(issue),
            "--artifacts-dir",
            str(artifacts),
            "--base",
            "origin/main",
            "--viewport",
            "1280x720",
            "--allow-stub",
        ],
    )
    assert result.exit_code in {0, 1}
    assert list(artifacts.rglob("*.json"))


def test_cli_accepts_yaml_input(tmp_path: Path) -> None:
    yaml_path = tmp_path / "spec.yaml"
    yaml_path.write_text(SAMPLE_YAML_INPUT, encoding="utf-8")
    result = _RUNNER.invoke(app, ["verify-behavior", "--input", str(yaml_path)])
    combined = f"{result.stdout}\n{result.stderr}\n{result.exception}"
    assert result.exit_code != 0
    assert "browser-use" in combined.lower() or "cdp" in combined.lower()


def test_cli_action_failure_writes_report_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed browser actions must still write ``report.json`` under artifacts."""

    class FailingDriver(FakeBrowserDriver):
        async def click(self, selector: str) -> None:
            _ = selector
            raise RuntimeError("selector timeout")

    def fake_resolve(*, allow_stub: bool, viewport: Any) -> FakeBrowserDriver:
        _ = allow_stub
        _ = viewport
        return FailingDriver()

    monkeypatch.setattr(verify_behavior_cmd, "_resolve_driver", fake_resolve)
    artifacts = tmp_path / "arts"
    input_yaml = tmp_path / "spec.yaml"
    yaml_body = (
        SAMPLE_YAML_INPUT.replace(
            "artifacts_dir: .mergecraft/artifacts/manual/fixture",
            f"artifacts_dir: {artifacts}",
        )
        .replace(
            "credential_env_names:\n  - APP_TEST_PASSWORD",
            "credential_env_names: []",
        )
        .replace(
            "startup_command: python -m http.server 8765",
            "startup_command: ''",
        )
    )
    input_yaml.write_text(yaml_body, encoding="utf-8")
    result = _RUNNER.invoke(
        app,
        [
            "verify-behavior",
            "--input",
            str(input_yaml),
        ],
    )
    assert result.exit_code != 0
    report_path = artifacts / "report.json"
    assert report_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert any(item.get("result", "").startswith("error:") for item in payload["steps"])
