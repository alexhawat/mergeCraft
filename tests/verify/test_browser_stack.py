"""CDP bind and fail-closed behaviour for the live browser driver.

The live-driver cases are real passes now that the CDP-backed
``BrowserDriver`` exists; the refusal cases guard the fail-closed contract
that must not regress. The one case needing a real Chrome is skip-gated and
named (R-D11) — never a quiet deselect.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from mergecraft.browser import BrowserStackUnavailableError, launch_browser_driver
from mergecraft.browser.availability import browser_stack_available, cdp_base_url
from mergecraft.browser.cdp import CdpBrowserDriver
from mergecraft.cli import verify_behavior_cmd
from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE
from mergecraft.verify.models import Viewport
from tests.verify.support import import_verify, require_symbol

_RUNNER = CliRunner()
_CDP_SKIP_REASON = (
    "CDP unavailable: no Chrome DevTools Protocol endpoint answered "
    f"{cdp_base_url()}/json/version — start Chrome with --remote-debugging-port "
    "and set MERGECRAFT_CDP_URL to run this live check"
)


def _close_quietly(driver: object) -> None:
    closer = getattr(driver, "close", None)
    if callable(closer):
        closer()


def test_launch_browser_driver_fails_closed_when_cdp_unreachable() -> None:
    """Unreachable CDP still raises, and the message names the endpoint and the fix."""
    monkeypatch_url = "http://127.0.0.1:9777"
    with (
        patch("mergecraft.browser.launch.browser_stack_available", return_value=False),
        patch("mergecraft.browser.launch.cdp_base_url", return_value=monkeypatch_url),
        pytest.raises(BrowserStackUnavailableError) as exc_info,
    ):
        launch_browser_driver()
    message = str(exc_info.value)
    assert "unreachable" in message
    assert monkeypatch_url in message
    assert "remote-debugging-port" in message
    assert "MERGECRAFT_CDP_URL" in message


def test_launch_browser_driver_returns_live_driver_when_cdp_reachable(
    fake_cdp_endpoint: str,
) -> None:
    """A reachable CDP endpoint returns a protocol driver, not a raise.

    Construction must be lazy: it may probe the endpoint but must not require a
    live browser session to build the driver object. ``fake_cdp_endpoint``
    answers the discovery routes so the probe is deterministic.

    The concrete-type assertion is the no-op detector: an empty class that merely
    satisfies the ``BrowserDriver`` protocol (so ``isinstance`` and the stub-name
    check both pass) is still not the CDP driver, and this fails against it
    without needing a real Chrome.
    """
    assert browser_stack_available() is True
    driver_mod = import_verify("driver")
    protocol = require_symbol(driver_mod, "BrowserDriver")
    driver = launch_browser_driver()
    try:
        assert isinstance(driver, protocol)
        assert driver.__class__.__name__ != "_StubBrowserDriver"
        assert type(driver) is CdpBrowserDriver
    finally:
        _close_quietly(driver)


def test_resolve_driver_uses_stub_only_with_allow_stub() -> None:
    driver = verify_behavior_cmd._resolve_driver(allow_stub=True, viewport=None)
    assert driver.__class__.__name__ == "_StubBrowserDriver"


def test_resolve_driver_binds_live_driver_when_cdp_reachable(fake_cdp_endpoint: str) -> None:
    """Removing the live bind from ``_resolve_driver`` must fail this test."""
    assert browser_stack_available() is True
    driver_mod = import_verify("driver")
    protocol = require_symbol(driver_mod, "BrowserDriver")
    driver = verify_behavior_cmd._resolve_driver(
        allow_stub=False,
        viewport=Viewport(width=800, height=600),
    )
    try:
        assert isinstance(driver, protocol)
        assert driver.__class__.__name__ != "_StubBrowserDriver"
        assert type(driver) is CdpBrowserDriver
    finally:
        _close_quietly(driver)


def test_resolve_driver_raises_when_cdp_unreachable() -> None:
    with (
        patch("mergecraft.browser.launch.browser_stack_available", return_value=False),
        pytest.raises(BrowserStackUnavailableError, match="unreachable"),
    ):
        verify_behavior_cmd._resolve_driver(allow_stub=False, viewport=None)


def test_unreachable_cdp_cli_exits_configuration_not_pass() -> None:
    """Without ``--allow-stub`` the CLI refuses; it never reports a green verify."""
    with patch("mergecraft.browser.launch.browser_stack_available", return_value=False):
        result = _RUNNER.invoke(
            app,
            ["verify-behavior", "--mode", "verify", "--url", "http://127.0.0.1:8765/"],
        )
    combined = f"{result.stdout}\n{result.stderr}\n{result.exception}".lower()
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert "pass" not in result.stdout.lower()
    assert "unreachable" in combined or "cdp" in combined


def test_unreachable_cdp_artifacts_run_is_never_a_passing_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-D3: no configuration produces a stub-pass green verify.

    R-D11 / R7-F4: the report the refusal writes must *name* the skip, and the
    operator remedy in that name must survive redaction. So the first
    ``skipped_or_unverified`` entry carries a ``cdp_unavailable:`` prefix and
    the literal ``--remote-debugging-port`` — the latter is otherwise shaped
    like a secret and is kept only by ``redact._KNOWN_SAFE_LITERALS``.

    Even with ``--artifacts-dir`` set (which must not opt into the stub), the
    run refuses and the report it writes is not ``pass``.
    """
    monkeypatch.setenv("MERGECRAFT_CDP_URL", "http://127.0.0.1:9777")
    artifacts = tmp_path / "arts"
    with patch("mergecraft.browser.launch.browser_stack_available", return_value=False):
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
    assert result.exit_code != 0
    report = artifacts / "report.json"
    assert report.exists(), "the refusal must write a report that names the skip"
    payload: Any = json.loads(report.read_text(encoding="utf-8"))
    assert payload.get("status") != "pass"
    reasons = payload.get("skipped_or_unverified")
    assert isinstance(reasons, list)
    assert reasons, "the skip reason must be recorded"
    reason = reasons[0]
    assert "cdp_unavailable:" in reason
    assert "--remote-debugging-port" in reason


@pytest.mark.skipif(not browser_stack_available(), reason=_CDP_SKIP_REASON)
async def test_live_cdp_driver_navigates_and_extracts() -> None:
    """Real Chrome check, gated and named — never a quiet deselect."""
    driver = launch_browser_driver()
    try:
        await driver.navigate("data:text/html,<p>live-cdp-ok</p>")
        assert "live-cdp-ok" in await driver.extract_text()
    finally:
        _close_quietly(driver)
