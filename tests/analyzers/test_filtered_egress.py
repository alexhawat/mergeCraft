"""W3 Step 3 — allowlisted CONNECT proxy and filtered netns wrap (not HTTP_PROXY)."""

from __future__ import annotations

import socket
import threading

import pytest

from mergecraft.analyzers.egress import (
    AllowlistConnectProxy,
    FilteredEgressSetupError,
    FilteredNetnsSession,
    allowlist_hosts,
    filtered_egress_available,
    host_is_allowlisted,
    probe_filtered_egress,
    reset_filtered_egress_cache,
    resolve_allowlist_ips,
    wrap_argv_for_filtered_netns,
)


def _echo_backend() -> tuple[socket.socket, int]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])

    def _accept() -> None:
        conn, _addr = listener.accept()
        try:
            data = conn.recv(1024)
            conn.sendall(data)
        finally:
            conn.close()
            listener.close()

    threading.Thread(target=_accept, daemon=True).start()
    return listener, port


def test_allowlist_hosts_strips_scheme_and_port() -> None:
    hosts = allowlist_hosts(["https://api.osv.dev", "deps.dev:443"])
    assert "api.osv.dev" in hosts
    assert "deps.dev" in hosts


def test_host_is_allowlisted_matches_parent_suffix() -> None:
    allowed = allowlist_hosts(["osv.dev"])
    assert host_is_allowlisted("api.osv.dev", allowed)
    assert not host_is_allowlisted("evil.example", allowed)


def test_resolve_allowlist_ips_includes_loopback() -> None:
    ips = resolve_allowlist_ips(["127.0.0.1"])
    assert "127.0.0.1" in ips


def test_wrap_argv_for_filtered_netns_drops_net() -> None:
    wrapped = wrap_argv_for_filtered_netns(["unshare", "--net", "true"], "mc-eg-test")
    assert wrapped == ["ip", "netns", "exec", "mc-eg-test", "unshare", "true"]


def test_allowlisted_connect_reaches_backend() -> None:
    _listener, port = _echo_backend()
    with AllowlistConnectProxy(["127.0.0.1"]) as proxy:
        client = socket.create_connection((proxy.host, proxy.port), timeout=5)
        client.sendall(f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\n\r\n".encode())
        status = client.recv(1024)
        assert status.startswith(b"HTTP/1.1 200"), status
        client.sendall(b"ping")
        echoed = client.recv(1024)
        assert echoed == b"ping"
        client.close()


def test_non_allowlisted_connect_is_forbidden() -> None:
    with AllowlistConnectProxy(["api.osv.dev"]) as proxy:
        client = socket.create_connection((proxy.host, proxy.port), timeout=5)
        client.sendall(b"CONNECT evil.example:443 HTTP/1.1\r\n\r\n")
        status = client.recv(1024)
        assert status.startswith(b"HTTP/1.1 403"), status
        client.close()


def test_probe_does_not_fake_availability_on_this_host() -> None:
    """macOS / unprivileged containers report unavailable rather than lying."""
    reset_filtered_egress_cache()
    probe = probe_filtered_egress()
    if not probe.available:
        assert probe.reason
        assert "unavailable" in probe.reason
    else:
        assert probe.network_namespace
        assert probe.veth
        assert probe.ip_netns
        assert probe.iptables


def test_session_start_fails_closed_when_unavailable() -> None:
    reset_filtered_egress_cache()
    if filtered_egress_available():
        pytest.skip("filtered egress is available on this host")
    with pytest.raises(FilteredEgressSetupError):
        FilteredNetnsSession(["127.0.0.1"]).start()
