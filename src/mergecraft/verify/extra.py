"""Browser-use stack gate for behaviour verification.

Uses CDP availability probes — never Playwright or ``mergecraft[browser]``.

Exports:
    BrowserStackUnavailableError: Raised when live browsing cannot start.
    require_browser_stack: Raise when the stack is unavailable.
"""

from __future__ import annotations

from mergecraft.browser.errors import BrowserStackUnavailableError
from mergecraft.browser.launch import launch_browser_driver

__all__ = [
    "BrowserStackUnavailableError",
    "launch_browser_driver",
    "require_browser_stack",
]


def require_browser_stack() -> None:
    """Raise when the browser-use stack cannot start a live driver.

    Raises:
        BrowserStackUnavailableError: When ``launch_browser_driver`` would fail.

    Examples:
        >>> from mergecraft.verify.extra import BrowserStackUnavailableError
        >>> issubclass(BrowserStackUnavailableError, RuntimeError)
        True
    """
    launch_browser_driver()
