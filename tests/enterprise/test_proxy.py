"""W7.1 — enterprise HTTP(S) proxy support (#381).

Intended public API (W7.2): ``mergecraft.enterprise.proxy``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

_PROXY_ENV = (
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "no_proxy",
)

_EXAMPLE_PROXY = "http://proxy.example:8080"


@pytest.fixture(autouse=True)
def _record_proxy_env_undo(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Ensure monkeypatch undoes proxy env even when vars were unset.

    ``delenv(..., raising=False)`` on a missing key records no undo, so
    ``apply_enterprise_proxy`` would otherwise leak ``HTTPS_PROXY`` into
    later tests (coverage-gate / ``--randomly-seed=424242``).
    """
    for name in _PROXY_ENV:
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name, raising=False)
    yield
    for name in _PROXY_ENV:
        os.environ.pop(name, None)


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


def test_apply_enterprise_proxy_undo_clears_example_https_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: monkeypatch undo must drop the example HTTPS_PROXY host."""
    from mergecraft.enterprise.proxy import ProxyConfig, apply_enterprise_proxy

    apply_enterprise_proxy(ProxyConfig(https_proxy=_EXAMPLE_PROXY))
    assert (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")) == _EXAMPLE_PROXY
    monkeypatch.undo()
    leaked = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
        or ""
    )
    assert "proxy.example" not in leaked
