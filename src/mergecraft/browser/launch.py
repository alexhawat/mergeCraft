"""Public entrypoint for live behaviour-verification browsing.

The product path is a CDP-backed driver over a host Chrome endpoint — not
Playwright and not a managed browser launch. Reachability is probed once; a
reachable endpoint yields a lazily-constructed driver, and an unreachable one
fails closed with an actionable message.

Exports:
    launch_browser_driver: Return a live ``BrowserDriver`` or raise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.browser.availability import browser_stack_available, cdp_base_url
from mergecraft.browser.cdp import CdpBrowserDriver
from mergecraft.browser.errors import BrowserStackUnavailableError

if TYPE_CHECKING:
    from mergecraft.verify.driver import BrowserDriver


def launch_browser_driver(
    *,
    width: int | None = None,
    height: int | None = None,
) -> BrowserDriver:
    """Bind a live CDP-backed browser driver for ``verify-behavior``.

    Args:
        width (int | None, optional): Viewport width in pixels. Defaults to
            ``None``.
        height (int | None, optional): Viewport height in pixels. Defaults to
            ``None``.

    Returns:
        BrowserDriver: Lazy CDP driver. Construction probes ``/json/version``
        but opens no websocket — the first command does.

    Raises:
        BrowserStackUnavailableError: When the CDP endpoint is unreachable.

    Examples:
        >>> callable(launch_browser_driver)
        True
    """
    if not browser_stack_available():
        raise BrowserStackUnavailableError(
            "Chrome DevTools Protocol endpoint is unreachable at "
            f"{cdp_base_url()}. Start Chrome with --remote-debugging-port and "
            "set MERGECRAFT_CDP_URL if needed."
        )
    return CdpBrowserDriver(cdp_base_url(), width=width, height=height)
