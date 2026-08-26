"""BR1.5 / BR6 — egress resolver concurrency and pinning (MCB-18, D12)."""

from __future__ import annotations

import ipaddress
import socket
import threading

_HOST_A = "pinned-host-a.example"
_HOST_B = "pinned-host-b.example"
_ADDR_A = ipaddress.ip_address("93.184.216.34")
_ADDR_B = ipaddress.ip_address("93.184.216.35")


def test_overlapping_pins_each_stay_pinned() -> None:
    """MCB-18: overlapping ``pin_host_resolution`` contexts must not clobber each other."""
    from mergecraft.security.egress import pin_host_resolution

    barrier = threading.Barrier(2)
    results: dict[str, str] = {}
    errors: list[BaseException] = []

    def worker(host: str, address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        try:
            with pin_host_resolution(host, [address]):
                barrier.wait(timeout=5)
                resolved = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)[0][4][0]
                results[host] = resolved
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(_HOST_A, _ADDR_A)),
        threading.Thread(target=worker, args=(_HOST_B, _ADDR_B)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors
    assert results[_HOST_A] == str(_ADDR_A)
    assert results[_HOST_B] == str(_ADDR_B)


def test_getaddrinfo_is_the_original_object_after_every_test() -> None:
    """MCB-18: resolver monkeypatch must always restore ``socket.getaddrinfo``."""
    from mergecraft.security.egress import pin_host_resolution

    original = socket.getaddrinfo
    with pin_host_resolution(_HOST_A, [_ADDR_A]):
        assert socket.getaddrinfo is not original
    assert socket.getaddrinfo is original


def test_unrelated_resolution_is_unaffected_by_a_guarded_request() -> None:
    """MCB-18: pinning one host must not rewrite unrelated lookups."""
    from mergecraft.security.egress import pin_host_resolution

    unrelated = "127.0.0.1"
    with pin_host_resolution(_HOST_A, [_ADDR_A]):
        before = socket.getaddrinfo(unrelated, 80, type=socket.SOCK_STREAM)
    after = socket.getaddrinfo(unrelated, 80, type=socket.SOCK_STREAM)
    assert before == after


def test_host_header_and_sni_survive_ip_pinning() -> None:
    """D12: pinned transport must preserve hostname for Host header and TLS SNI."""
    from mergecraft.security.egress import pinned_request_metadata

    metadata = pinned_request_metadata("https://example.com/resource", pinned_ip=_ADDR_A)
    assert metadata.host == "example.com"
    assert metadata.server_hostname == "example.com"
    assert metadata.connect_host == str(_ADDR_A)
