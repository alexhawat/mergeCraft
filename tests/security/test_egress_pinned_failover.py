"""A pinned transport must try every validated address, not only the first.

``_pinned_network_backend`` dials IPs that ``guard_external_url`` already
validated, so DNS cannot be re-resolved to something else mid-request. It took
one address per ``connect_tcp`` and let the failure propagate, and the
transport runs with httpx's default ``retries=0`` — so an unreachable first
answer ended the request. Resolution routinely returns several addresses with
only some reachable (a stale AAAA on a v4-only runner is the ordinary case), so
pinning turned "the client fails over" into "the download aborts".
"""

from __future__ import annotations

import ipaddress
from typing import Any

import pytest

from mergecraft.security.egress import _pinned_network_backend

_HOST = "example.test"
_ADDRS = [ipaddress.ip_address("192.0.2.1"), ipaddress.ip_address("192.0.2.2")]


class _Wrapped:
    """Records dial attempts; fails for every host in ``unreachable``."""

    def __init__(self, unreachable: set[str]) -> None:
        self.unreachable = unreachable
        self.attempts: list[str] = []

    def connect_tcp(self, host: str, port: int, **_: Any) -> str:
        self.attempts.append(host)
        if host in self.unreachable:
            msg = f"no route to {host}"
            raise OSError(msg)
        return f"stream:{host}"

    def connect_unix_socket(self, path: str, **_: Any) -> str:  # pragma: no cover
        return f"unix:{path}"


def test_first_address_unreachable_falls_over_to_the_second() -> None:
    wrapped = _Wrapped(unreachable={"192.0.2.1"})
    backend = _pinned_network_backend(_HOST, _ADDRS, wrapped)

    assert backend.connect_tcp(_HOST, 443) == "stream:192.0.2.2"
    assert wrapped.attempts == ["192.0.2.1", "192.0.2.2"]


def test_every_address_unreachable_raises_the_last_error() -> None:
    """Failover must not swallow a genuine outage into a silent success."""
    wrapped = _Wrapped(unreachable={"192.0.2.1", "192.0.2.2"})
    backend = _pinned_network_backend(_HOST, _ADDRS, wrapped)

    with pytest.raises(OSError, match="no route"):
        backend.connect_tcp(_HOST, 443)

    assert wrapped.attempts == ["192.0.2.1", "192.0.2.2"], "each address tried once"


def test_attempts_are_bounded_by_the_address_count() -> None:
    """The cycle is infinite; the retry loop must not be."""
    wrapped = _Wrapped(unreachable={"192.0.2.1", "192.0.2.2"})
    backend = _pinned_network_backend(_HOST, _ADDRS, wrapped)

    with pytest.raises(OSError, match="no route"):
        backend.connect_tcp(_HOST, 443)

    assert len(wrapped.attempts) == len(_ADDRS)


def test_a_reachable_first_address_dials_once() -> None:
    """Guard the guard: failover must not add a round trip to the happy path."""
    wrapped = _Wrapped(unreachable=set())
    backend = _pinned_network_backend(_HOST, _ADDRS, wrapped)

    assert backend.connect_tcp(_HOST, 443) == "stream:192.0.2.1"
    assert wrapped.attempts == ["192.0.2.1"]


def test_another_host_is_passed_through_unpinned() -> None:
    """Pinning applies to the validated host only; nothing else is rewritten."""
    wrapped = _Wrapped(unreachable=set())
    backend = _pinned_network_backend(_HOST, _ADDRS, wrapped)

    assert backend.connect_tcp("other.test", 443) == "stream:other.test"
    assert wrapped.attempts == ["other.test"]


def test_no_validated_addresses_passes_through() -> None:
    """An empty address set must not divide by zero or loop zero times."""
    wrapped = _Wrapped(unreachable=set())
    backend = _pinned_network_backend(_HOST, [], wrapped)

    assert backend.connect_tcp(_HOST, 443) == f"stream:{_HOST}"
