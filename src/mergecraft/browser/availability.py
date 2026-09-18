"""Probe whether a Chrome DevTools Protocol endpoint is reachable.

Exports:
    cdp_base_url: Resolved CDP HTTP base URL.
    browser_stack_available: True when ``/json/version`` responds.
"""

from __future__ import annotations

import os
from typing import Final

import httpx

_DEFAULT_CDP_URL: Final[str] = "http://127.0.0.1:9222"
_PROBE_TIMEOUT_S: Final[float] = 0.5


def cdp_base_url() -> str:
    """Return the CDP HTTP base URL from ``MERGECRAFT_CDP_URL`` or the default.

    Returns:
        str: Base URL without a trailing slash.

    Examples:
        >>> isinstance(cdp_base_url(), str)
        True
    """
    raw = os.environ.get("MERGECRAFT_CDP_URL", _DEFAULT_CDP_URL).strip()
    return raw.rstrip("/") or _DEFAULT_CDP_URL


def browser_stack_available(*, timeout_s: float = _PROBE_TIMEOUT_S) -> bool:
    """Return whether a CDP endpoint answers ``/json/version``.

    Args:
        timeout_s (float, optional): HTTP probe timeout. Defaults to ``0.5``.

    Returns:
        bool: ``True`` when the endpoint responds with HTTP 200.

    Examples:
        >>> isinstance(browser_stack_available(), bool)
        True
    """
    url = f"{cdp_base_url()}/json/version"
    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(url)
    except httpx.HTTPError:
        return False
    return response.status_code == 200
