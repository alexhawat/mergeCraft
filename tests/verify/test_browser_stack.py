"""Browser-use stack bind and fail-closed behaviour."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mergecraft.browser import BrowserStackUnavailableError, launch_browser_driver
from mergecraft.cli import verify_behavior_cmd


def test_launch_browser_driver_fails_closed_when_cdp_unreachable() -> None:
    with (
        patch("mergecraft.browser.launch.browser_stack_available", return_value=False),
        pytest.raises(BrowserStackUnavailableError, match="unreachable"),
    ):
        launch_browser_driver()


def test_launch_browser_driver_fails_closed_when_driver_not_wired() -> None:
    with (
        patch("mergecraft.browser.launch.browser_stack_available", return_value=True),
        pytest.raises(BrowserStackUnavailableError, match="#752"),
    ):
        launch_browser_driver()


def test_resolve_driver_uses_stub_only_with_allow_stub() -> None:
    driver = verify_behavior_cmd._resolve_driver(allow_stub=True, viewport=None)
    assert driver.__class__.__name__ == "_StubBrowserDriver"


def test_resolve_driver_binds_browser_use_when_available() -> None:
    with (
        patch("mergecraft.browser.launch.browser_stack_available", return_value=True),
        pytest.raises(BrowserStackUnavailableError, match="#752"),
    ):
        verify_behavior_cmd._resolve_driver(allow_stub=False, viewport=None)


def test_resolve_driver_raises_when_cdp_unreachable() -> None:
    with (
        patch("mergecraft.browser.launch.browser_stack_available", return_value=False),
        pytest.raises(BrowserStackUnavailableError, match="unreachable"),
    ):
        verify_behavior_cmd._resolve_driver(allow_stub=False, viewport=None)
