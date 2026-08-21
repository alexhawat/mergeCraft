"""Enterprise HTTP(S) proxy configuration for outbound traffic (#381).

Exports:
    ProxyConfig: Dataclass for proxy settings.
    apply_enterprise_proxy: Apply proxy settings to the process environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

__all__ = [
    "ProxyConfig",
    "apply_enterprise_proxy",
]


@dataclass
class ProxyConfig:
    """Enterprise proxy configuration.

    Attributes:
        https_proxy: HTTPS proxy URL.  Must be http:// or https://.
        no_proxy: Comma-separated list of hosts that bypass the proxy.
    """

    https_proxy: str
    no_proxy: str = field(default="")


def _validate_proxy_url(url: str) -> None:
    """Raise ValueError when *url* is not a valid http(s) proxy URL."""
    if not url:
        msg = "proxy URL must not be empty"
        raise ValueError(msg)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        msg = f"proxy URL scheme must be http or https, got: {url!r}"
        raise ValueError(msg)
    if not parsed.netloc:
        msg = f"proxy URL must include a host: {url!r}"
        raise ValueError(msg)


def apply_enterprise_proxy(config: ProxyConfig) -> None:
    """Apply *config* to the current process environment.

    Sets ``HTTPS_PROXY`` and, when non-empty, ``NO_PROXY``.

    Args:
        config: The proxy configuration to apply.

    Raises:
        ValueError: When the proxy URL is not a valid http(s) URL.
    """
    _validate_proxy_url(config.https_proxy)
    os.environ["HTTPS_PROXY"] = config.https_proxy
    if config.no_proxy:
        os.environ["NO_PROXY"] = config.no_proxy
