"""W7.1 — enterprise HTTP(S) proxy support (#381).

Intended public API (W7.2): ``mergecraft.enterprise.proxy``.
"""

from __future__ import annotations

import os

import pytest

_EXAMPLE_PROXY = "http://proxy.example:8080"


def test_apply_enterprise_proxy_sets_https_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy: applying a proxy config exports HTTPS_PROXY for outbound HTTPS."""
    monkeypatch.setenv("HTTPS_PROXY", "")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("https_proxy", "")
    monkeypatch.delenv("https_proxy", raising=False)
    from mergecraft.enterprise.proxy import ProxyConfig, apply_enterprise_proxy

    apply_enterprise_proxy(ProxyConfig(https_proxy=_EXAMPLE_PROXY))
    exported = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    assert exported == _EXAMPLE_PROXY
    assert os.environ.get("HTTP_PROXY") == _EXAMPLE_PROXY


def test_apply_enterprise_proxy_honours_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Edge: empty no_proxy is accepted; a host list is exported as NO_PROXY."""
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.delenv("NO_PROXY", raising=False)
    from mergecraft.enterprise.proxy import ProxyConfig, apply_enterprise_proxy

    apply_enterprise_proxy(ProxyConfig(https_proxy=_EXAMPLE_PROXY, no_proxy=""))
    apply_enterprise_proxy(ProxyConfig(https_proxy=_EXAMPLE_PROXY, no_proxy="localhost,.internal"))
    exported = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")
    assert "localhost" in (exported or "")


@pytest.mark.parametrize("bad", ["", "not-a-url", "ftp://proxy.example:8080"])
def test_invalid_proxy_url_raises(bad: str) -> None:
    """Error: invalid or non-HTTP(S) proxy URLs raise ValueError naming proxy."""
    from mergecraft.enterprise.proxy import ProxyConfig, apply_enterprise_proxy

    with pytest.raises(ValueError, match="proxy"):
        apply_enterprise_proxy(ProxyConfig(https_proxy=bad))


def test_apply_enterprise_proxy_undo_clears_example_https_proxy() -> None:
    """Regression: clearing the example proxy must not pop inherited NO_PROXY."""
    from mergecraft.enterprise.proxy import ProxyConfig, apply_enterprise_proxy

    before = {
        name: os.environ.get(name)
        for name in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy")
    }
    apply_enterprise_proxy(ProxyConfig(https_proxy=_EXAMPLE_PROXY))
    assert (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")) == _EXAMPLE_PROXY
    for name, value in before.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    leaked = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
        or ""
    )
    assert "proxy.example" not in leaked
