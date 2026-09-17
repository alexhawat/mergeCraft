"""Optional ``mergecraft[browser]`` extra gate.

Uses ``importlib.util.find_spec`` so importing this module never loads
Playwright. A ``sys.modules['playwright'] is None`` entry is treated as absent.

Exports:
    BrowserExtraMissingError: Raised when Playwright is not available.
    require_browser_extra: Raise that error when the extra is missing.
"""

from __future__ import annotations

import importlib.util
import sys

_MISSING_MESSAGE = (
    "Playwright is not installed. Install the mergecraft[browser] extra "
    "to run behaviour verification."
)
_UNSET = object()


class BrowserExtraMissingError(RuntimeError):
    """Raised when the optional ``mergecraft[browser]`` extra is not installed."""


def require_browser_extra() -> None:
    """Raise when the Playwright package is missing or masked as absent.

    A module entry of ``None`` in ``sys.modules`` counts as missing, matching
    tests that hide an installed extra.

    Raises:
        BrowserExtraMissingError: When ``playwright`` cannot be imported. The
            message names ``mergecraft[browser]``.

    Examples:
        >>> from mergecraft.verify.extra import BrowserExtraMissingError
        >>> issubclass(BrowserExtraMissingError, RuntimeError)
        True
    """
    loaded = sys.modules.get("playwright", _UNSET)
    if loaded is None:
        raise BrowserExtraMissingError(_MISSING_MESSAGE)
    if loaded is _UNSET and importlib.util.find_spec("playwright") is None:
        raise BrowserExtraMissingError(_MISSING_MESSAGE)
