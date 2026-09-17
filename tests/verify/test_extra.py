"""Optional ``mergecraft[browser]`` extra — base install stays unchanged."""

from __future__ import annotations

import sys

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from tests.verify.support import V3_XFAIL, V4_XFAIL, import_verify, require_symbol

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


@V3_XFAIL
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


@V4_XFAIL
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
