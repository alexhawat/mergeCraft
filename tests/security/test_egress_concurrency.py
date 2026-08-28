"""BR1.5 / BR6 — egress resolver concurrency and pinning (MCB-18, D12)."""

from __future__ import annotations

import ipaddress
import socket
import threading
from typing import Any
from unittest.mock import patch

import httpx

_HOST_A = "pinned-host-a.example"
_HOST_B = "pinned-host-b.example"
_ADDR_A = ipaddress.ip_address("93.184.216.34")
_ADDR_B = ipaddress.ip_address("93.184.216.35")


def _record_connect_host(
    host: str,
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    port: int = 443,
) -> list[str]:
    """Drive a pinned transport far enough to observe dial targets on ``wrapped``."""
    from mergecraft.security import egress as egress_module
    from mergecraft.security.egress import pinned_http_transport

    recorded: list[str] = []
    real_factory = egress_module._pinned_network_backend

    def recording_factory(
        hostname: str,
        addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]
        | list[ipaddress.IPv4Address | ipaddress.IPv6Address],
        wrapped: Any,
    ) -> Any:
        def recording_connect_tcp(
            connect_host: str,
            connect_port: int,
            timeout: float | None = None,
            local_address: str | None = None,
            socket_options: Any | None = None,
        ) -> Any:
            _ = (connect_port, timeout, local_address, socket_options)
            recorded.append(connect_host)
            msg = "synthetic connect block"
            raise OSError(msg)

        wrapped.connect_tcp = recording_connect_tcp
        return real_factory(hostname, addresses, wrapped)

    with patch.object(egress_module, "_pinned_network_backend", recording_factory):
        transport = pinned_http_transport(host, [address])
        client = httpx.Client(transport=transport)
        try:
            client.get(f"https://{host}:{port}/", timeout=1.0)
        except (OSError, httpx.RequestError):
            pass
        finally:
            client.close()
    return recorded


def test_overlapping_pins_each_stay_pinned() -> None:
    """MCB-18: overlapping ``pinned_http_transport`` clients must not clobber each other."""
    from mergecraft.security import egress as egress_module
    from mergecraft.security.egress import pinned_http_transport

    recorded: dict[str, list[str]] = {}
    real_factory = egress_module._pinned_network_backend
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def recording_factory(
        hostname: str,
        addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]
        | list[ipaddress.IPv4Address | ipaddress.IPv6Address],
        wrapped: Any,
    ) -> Any:
        bucket = recorded.setdefault(hostname, [])

        def recording_connect_tcp(
            connect_host: str,
            connect_port: int,
            timeout: float | None = None,
            local_address: str | None = None,
            socket_options: Any | None = None,
        ) -> Any:
            _ = (connect_port, timeout, local_address, socket_options)
            bucket.append(connect_host)
            msg = "synthetic connect block"
            raise OSError(msg)

        wrapped.connect_tcp = recording_connect_tcp
        return real_factory(hostname, addresses, wrapped)

    def worker(host: str, address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        try:
            transport = pinned_http_transport(host, [address])
            client = httpx.Client(transport=transport)
            try:
                barrier.wait(timeout=5)
                client.get(f"https://{host}/", timeout=1.0)
            except (OSError, httpx.RequestError):
                pass
            finally:
                client.close()
        except BaseException as exc:
            errors.append(exc)

    with patch.object(egress_module, "_pinned_network_backend", recording_factory):
        threads = [
            threading.Thread(target=worker, args=(_HOST_A, _ADDR_A)),
            threading.Thread(target=worker, args=(_HOST_B, _ADDR_B)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    assert not errors
    assert recorded[_HOST_A][0] == str(_ADDR_A)
    assert recorded[_HOST_B][0] == str(_ADDR_B)


def test_getaddrinfo_is_the_original_object_after_every_test() -> None:
    """MCB-18: per-client pinning must not replace ``socket.getaddrinfo``."""
    original = socket.getaddrinfo
    assert socket.getaddrinfo is original
    _record_connect_host(_HOST_A, _ADDR_A)
    assert socket.getaddrinfo is original


def test_unrelated_resolution_is_unaffected_by_a_guarded_request() -> None:
    """MCB-18: pinning one host must not rewrite unrelated lookups."""
    unrelated = "127.0.0.1"
    before = socket.getaddrinfo(unrelated, 80, type=socket.SOCK_STREAM)
    _record_connect_host(_HOST_A, _ADDR_A)
    after = socket.getaddrinfo(unrelated, 80, type=socket.SOCK_STREAM)
    assert before == after


def test_host_header_and_sni_survive_ip_pinning() -> None:
    """D12: pinned transport must preserve hostname for Host header and TLS SNI."""
    from mergecraft.security.egress import pinned_request_metadata

    metadata = pinned_request_metadata("https://example.com/resource", pinned_ip=_ADDR_A)
    assert metadata.host == "example.com"
    assert metadata.server_hostname == "example.com"
    assert metadata.connect_host == str(_ADDR_A)
