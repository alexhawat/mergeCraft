"""Optional ``mergecraft[browser]`` extra — base install stays unchanged."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from tests.verify.support import import_verify, require_symbol, untrusted_fork_event

_RUNNER = CliRunner()


def test_importing_mergecraft_does_not_require_playwright() -> None:
    """Base import must succeed without the browser extra (already true today)."""
    before = {name for name in sys.modules if name.split(".", 1)[0] == "playwright"}
    import mergecraft
    import mergecraft.cli.app as cli_app

    assert mergecraft.__version__
    assert cli_app.app is not None
    after = {name for name in sys.modules if name.split(".", 1)[0] == "playwright"}
    assert after == before


def test_other_commands_work_without_browser_extra() -> None:
    result = _RUNNER.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_require_browser_extra_names_install_extra() -> None:
    extra = import_verify("extra")
    error_cls = require_symbol(extra, "BrowserExtraMissingError")
    require = require_symbol(extra, "require_browser_extra")
    hidden = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "playwright" or name.startswith("playwright.")
    }
    sys.modules["playwright"] = None  # type: ignore[assignment]
    try:
        with pytest.raises(error_cls, match=r"mergecraft\[browser\]"):
            require()
    finally:
        sys.modules.pop("playwright", None)
        sys.modules.update(hidden)


def test_verify_behavior_cli_errors_when_extra_absent() -> None:
    """The command names ``mergecraft[browser]`` rather than dumping ImportError."""
    hidden = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "playwright" or name.startswith("playwright.")
    }
    sys.modules["playwright"] = None  # type: ignore[assignment]
    try:
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
    finally:
        sys.modules.pop("playwright", None)
        sys.modules.update(hidden)
    combined = f"{result.stdout}\n{result.stderr}\n{result.exception}"
    assert result.exit_code != 0
    assert "mergecraft[browser]" in combined


def test_cli_artifacts_dir_without_playwright_is_not_a_pass(tmp_path: Path) -> None:
    """``--artifacts-dir`` must not stub-pass when Playwright is hidden."""
    hidden = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "playwright" or name.startswith("playwright.")
    }
    sys.modules["playwright"] = None  # type: ignore[assignment]
    artifacts = tmp_path / "arts"
    try:
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
    finally:
        sys.modules.pop("playwright", None)
        sys.modules.update(hidden)
    combined = f"{result.stdout}\n{result.stderr}\n{result.exception}"
    assert result.exit_code != 0
    assert "pass" not in result.stdout.lower()
    assert "mergecraft[browser]" in combined
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
    hidden = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "playwright" or name.startswith("playwright.")
    }
    sys.modules["playwright"] = None  # type: ignore[assignment]
    try:
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
    finally:
        sys.modules.pop("playwright", None)
        sys.modules.update(hidden)
    combined = f"{result.stdout}\n{result.stderr}\n{result.exception}"
    assert not sentinel.exists()
    assert "skipped" in combined.lower() or "untrusted" in combined.lower()
    assert result.exit_code != 0
