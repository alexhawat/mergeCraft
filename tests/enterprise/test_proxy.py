"""W7.1 — enterprise HTTP(S) proxy support (#381).

Intended public API (W7.2): ``mergecraft.enterprise.proxy``.
"""

from __future__ import annotations

import os

import pytest


def test_apply_enterprise_proxy_sets_https_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy: applying a proxy config exports HTTPS_PROXY for outbound HTTPS."""
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    from mergecraft.enterprise.proxy import ProxyConfig, apply_enterprise_proxy

    apply_enterprise_proxy(ProxyConfig(https_proxy="http://proxy.example:8080"))
    exported = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    assert exported == "http://proxy.example:8080"


def test_apply_enterprise_proxy_honours_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Edge: empty no_proxy is accepted; a host list is exported as NO_PROXY."""
    monkeypatch.delenv("NO_PROXY", raising=False)
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
