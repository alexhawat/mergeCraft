"""Browser-use stack errors.

Exports:
    BrowserStackUnavailableError: Raised when live browsing cannot start.
"""

from __future__ import annotations

_UNAVAILABLE_MESSAGE = (
    "Behaviour verification requires the custom browser-use stack (CDP host Chrome) "
    "plus JEV. Start Chrome with remote debugging and set MERGECRAFT_CDP_URL, or "
    "use --allow-stub for tests. See #752."
)


class BrowserStackUnavailableError(RuntimeError):
    """Raised when the browser-use CDP stack is missing or not wired yet."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or _UNAVAILABLE_MESSAGE)
