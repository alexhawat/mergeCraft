"""W7.1 — enterprise HTTP(S) proxy support (#381).

Intended public API (W7.2): ``mergecraft.enterprise.proxy``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

_PROXY_ENV = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "NO_PROXY",
    "no_proxy",
)


@pytest.fixture(autouse=True)
def _restore_proxy_env() -> Iterator[None]:
    """``apply_enterprise_proxy`` writes ``os.environ``; pytest ``delenv`` of a
    missing key does not record undo, so later analyzer downloads would inherit
    ``http://proxy.example:8080``.
    """
    saved = {key: os.environ.get(key) for key in _PROXY_ENV}
    for key in _PROXY_ENV:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key in _PROXY_ENV:
            previous = saved[key]
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def test_apply_enterprise_proxy_sets_https_proxy() -> None:
    """Happy: applying a proxy config exports HTTPS_PROXY for outbound HTTPS."""
    from mergecraft.enterprise.proxy import ProxyConfig, apply_enterprise_proxy

    apply_enterprise_proxy(ProxyConfig(https_proxy="http://proxy.example:8080"))
    exported = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    assert exported == "http://proxy.example:8080"


def test_apply_enterprise_proxy_honours_no_proxy() -> None:
    """Edge: empty no_proxy is accepted; a host list is exported as NO_PROXY."""
    from mergecraft.enterprise.proxy import ProxyConfig, apply_enterprise_proxy

    apply_enterprise_proxy(ProxyConfig(https_proxy="http://proxy.example:8080", no_proxy=""))
    apply_enterprise_proxy(
        ProxyConfig(https_proxy="http://proxy.example:8080", no_proxy="localhost,.internal")
    )
    exported = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")
    assert "localhost" in (exported or "")


@pytest.mark.parametrize("bad", ["", "not-a-url", "ftp://proxy.example:8080"])
def test_invalid_proxy_url_raises(bad: str) -> None:
    """Error: invalid or non-HTTP(S) proxy URLs raise ValueError naming proxy."""
    from mergecraft.enterprise.proxy import ProxyConfig, apply_enterprise_proxy

    with pytest.raises(ValueError, match="proxy"):
        apply_enterprise_proxy(ProxyConfig(https_proxy=bad))
