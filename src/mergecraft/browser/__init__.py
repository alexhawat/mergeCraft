"""Custom browser-use stack for behaviour verification (CDP + JEV).

Exports:
    BrowserStackUnavailableError: Raised when live browsing cannot start.
    launch_browser_driver: Public live-driver entrypoint (CDP host Chrome).
"""

from __future__ import annotations

from mergecraft.browser.errors import BrowserStackUnavailableError
from mergecraft.browser.launch import launch_browser_driver

__all__ = [
    "BrowserStackUnavailableError",
    "launch_browser_driver",
]
