"""Isolate enterprise runtime ContextVar and proxy/CA env between tests."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

_NETWORK_ENV = (
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "no_proxy",
    "ALL_PROXY",
    "all_proxy",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
)


@pytest.fixture(autouse=True)
def _reset_enterprise_runtime() -> Iterator[None]:
    from mergecraft.enterprise.runtime import reset_enterprise_runtime

    reset_enterprise_runtime()
    yield
    reset_enterprise_runtime()


@pytest.fixture(autouse=True)
def _restore_network_env() -> Iterator[None]:
    """Preserve inherited proxy/CA env; do not pop CI ``NO_PROXY`` on teardown."""
    original = {name: os.environ.get(name) for name in _NETWORK_ENV}
    yield
    for name, value in original.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
