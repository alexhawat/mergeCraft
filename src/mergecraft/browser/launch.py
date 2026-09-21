"""Public entrypoint for live behaviour-verification browsing.

The product path is custom browser-use (CDP) plus JEV — not Playwright. Until
the CDP driver is fully wired (#752), this module fails closed even when a CDP
endpoint is reachable.

Exports:
    launch_browser_driver: Return a live ``BrowserDriver`` or raise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.browser.availability import browser_stack_available, cdp_base_url
from mergecraft.browser.errors import BrowserStackUnavailableError

if TYPE_CHECKING:
    from mergecraft.verify.driver import BrowserDriver


def launch_browser_driver(
    *,
    width: int | None = None,
    height: int | None = None,
) -> BrowserDriver:
    """Bind a live browser driver for ``verify-behavior``.

    Args:
        width (int | None, optional): Viewport width in pixels. Reserved for the
            browser-use driver. Defaults to ``None``.
        height (int | None, optional): Viewport height in pixels. Reserved for the
            browser-use driver. Defaults to ``None``.

    Returns:
        BrowserDriver: Live CDP-backed driver once wired.

    Raises:
        BrowserStackUnavailableError: When CDP is unreachable or the driver is
            not wired yet.

    Examples:
        >>> callable(launch_browser_driver)
        True
    """
    _ = width
    _ = height
    if not browser_stack_available():
        raise BrowserStackUnavailableError(
            "Chrome DevTools Protocol endpoint is unreachable at "
            f"{cdp_base_url()}. Start Chrome with --remote-debugging-port and "
            "set MERGECRAFT_CDP_URL if needed."
        )
    raise BrowserStackUnavailableError(
        "browser-use CDP driver is not wired yet (#752). "
        "Live behaviour verification requires the custom browser-use + JEV stack."
    )
