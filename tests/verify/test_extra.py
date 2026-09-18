"""Browser-use stack gate — no Playwright or pip extra required."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from mergecraft.browser.errors import BrowserStackUnavailableError
from mergecraft.cli.app import app
from tests.verify.support import untrusted_fork_event

if TYPE_CHECKING:
    from collections.abc import Iterator

_RUNNER = CliRunner()


@pytest.fixture(autouse=True)
def _browser_stack_unavailable() -> Iterator[None]:
    """Pin the fail-closed path when live browsing is unavailable."""
    with patch("mergecraft.browser.launch.browser_stack_available", return_value=False):
        yield


def test_importing_mergecraft_does_not_require_playwright() -> None:
    """Base import must succeed without Playwright installed."""
    before = {name for name in sys.modules if name.split(".", 1)[0] == "playwright"}
    import mergecraft
    import mergecraft.cli.app as cli_app

    assert mergecraft.__version__
    assert cli_app.app is not None
    after = {name for name in sys.modules if name.split(".", 1)[0] == "playwright"}
    assert after == before


def test_other_commands_work_without_browser_stack() -> None:
    result = _RUNNER.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_require_browser_stack_fails_closed() -> None:
    from mergecraft.verify.extra import require_browser_stack

    with pytest.raises(BrowserStackUnavailableError, match="unreachable"):
        require_browser_stack()


def test_playwright_is_not_a_default_or_dev_dependency() -> None:
    from pathlib import Path

    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "playwright" not in text.lower()
    assert "[browser]" not in text


def test_verify_behavior_cli_errors_when_browser_stack_unavailable() -> None:
    result = _RUNNER.invoke(
        app,
        [
            "verify-behavior",
            "--mode",
            "verify",
            "--url",
            "http://127.0.0.1:8765",
        ],
    )
    combined = f"{result.stdout}\n{result.stderr}\n{result.exception}"
    assert result.exit_code != 0
    assert "browser-use" in combined.lower() or "cdp" in combined.lower()


def test_cli_artifacts_dir_without_browser_stack_is_not_a_pass(tmp_path: Path) -> None:
    """``--artifacts-dir`` must not stub-pass when live browsing is unavailable."""
    artifacts = tmp_path / "arts"
    result = _RUNNER.invoke(
        app,
        [
            "verify-behavior",
            "--mode",
            "verify",
            "--url",
            "http://127.0.0.1:8765/",
            "--artifacts-dir",
            str(artifacts),
        ],
    )
    combined = f"{result.stdout}\n{result.stderr}\n{result.exception}"
    assert result.exit_code != 0
    assert "pass" not in result.stdout.lower()
    assert "browser-use" in combined.lower() or "cdp" in combined.lower()
    report = artifacts / "report.json"
    if report.exists():
        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload.get("status") != "pass"


def test_cli_fork_event_does_not_run_start_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fork ``GITHUB_EVENT_PATH`` must not execute ``--start-command``."""
    sentinel = tmp_path / "started"
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(untrusted_fork_event()), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    artifacts = tmp_path / "arts"
    result = _RUNNER.invoke(
        app,
        [
            "verify-behavior",
            "--mode",
            "verify",
            "--url",
            "http://127.0.0.1:8765/",
            "--artifacts-dir",
            str(artifacts),
            "--start-command",
            f"touch {sentinel}",
        ],
    )
    combined = f"{result.stdout}\n{result.stderr}\n{result.exception}"
    assert not sentinel.exists()
    assert "skipped" in combined.lower() or "untrusted" in combined.lower()
    assert result.exit_code != 0
