"""Behaviour of the autouse hermeticity guards in ``tests/support/hermetic.py``."""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path

import pytest

from tests.support import hermetic


def test_non_loopback_connect_is_blocked() -> None:
    with pytest.raises(hermetic.NetworkBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=1)
    hermetic._VIOLATIONS.clear()  # the raise above is the expected outcome


def test_dns_lookup_of_external_host_is_blocked() -> None:
    with pytest.raises(hermetic.NetworkBlockedError):
        socket.getaddrinfo("api.github.com", 443)
    hermetic._VIOLATIONS.clear()


def test_loopback_connect_is_allowed() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=2):
            pass


@pytest.mark.network
def test_network_marker_lifts_the_guard() -> None:
    # With the guard lifted the lookup reaches the resolver (``.invalid`` never resolves).
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("nonexistent.invalid", 80)


def test_ambient_environment_is_scrubbed() -> None:
    for name in os.environ:
        assert not name.startswith(("MERGECRAFT_LIVE", "GITHUB_", "OTEL_", "OPENAI_"))
    assert "GITHUB_TOKEN" not in os.environ
    assert "GH_TOKEN" not in os.environ


def test_home_and_xdg_live_outside_the_checkout() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "MERGECRAFT_TRACE_DIR"):
        assert not Path(os.environ[name]).resolve().is_relative_to(root)
    assert Path.home() == Path(os.environ["HOME"])


@pytest.mark.timeout(1)
def test_per_test_timeout_interrupts_a_hang() -> None:
    with pytest.raises(hermetic.TestTimeoutError):
        time.sleep(5)
