"""Custom browser-use stack for behaviour verification (CDP + JEV).

Exports:
    BrowserStackUnavailableError: Raised when live browsing cannot start.
    browser_stack_available: Probe whether CDP responds.
    cdp_base_url: Resolved CDP HTTP base URL.
    launch_browser_driver: Public live-driver entrypoint (fail closed until wired).
"""

from __future__ import annotations

from mergecraft.browser.availability import browser_stack_available, cdp_base_url
from mergecraft.browser.errors import BrowserStackUnavailableError
from mergecraft.browser.launch import launch_browser_driver

__all__ = [
    "BrowserStackUnavailableError",
    "browser_stack_available",
    "cdp_base_url",
    "launch_browser_driver",
]
