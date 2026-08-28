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

import httpcore
import pytest

from mergecraft.security.egress import _pinned_network_backend

_HOST = "example.test"
_ADDRS = [ipaddress.ip_address("192.0.2.1"), ipaddress.ip_address("192.0.2.2")]


# The exception types a *backend* actually raises. httpcore maps socket
# failures to these inside ``connect_tcp``, and both derive from plain
# ``Exception`` -- so the earlier version of this file, which raised
# ``OSError``, passed while the production catch missed every real failure.
# Parametrising over all three is the point: the test must fail if the catch
# narrows again.
_BACKEND_ERRORS = (
    httpcore.ConnectError,
    httpcore.ConnectTimeout,
    OSError,
)


class _Wrapped:
    """Records dial attempts; fails for every host in ``unreachable``."""

    def __init__(self, unreachable: set[str], error: type[BaseException] = OSError) -> None:
        self.unreachable = unreachable
        self.error = error
        self.attempts: list[str] = []

    def connect_tcp(self, host: str, port: int, **_: Any) -> str:
        self.attempts.append(host)
        if host in self.unreachable:
            raise self.error(f"no route to {host}")
        return f"stream:{host}"

    def connect_unix_socket(self, path: str, **_: Any) -> str:  # pragma: no cover
        return f"unix:{path}"


@pytest.mark.parametrize("error", _BACKEND_ERRORS, ids=lambda e: e.__name__)
def test_first_address_unreachable_falls_over_to_the_second(
    error: type[BaseException],
) -> None:
    """Every error class a backend can raise must trigger failover."""
    wrapped = _Wrapped(unreachable={"192.0.2.1"}, error=error)
    backend = _pinned_network_backend(_HOST, _ADDRS, wrapped)

    assert backend.connect_tcp(_HOST, 443) == "stream:192.0.2.2"
    assert wrapped.attempts == ["192.0.2.1", "192.0.2.2"]


@pytest.mark.parametrize("error", _BACKEND_ERRORS, ids=lambda e: e.__name__)
def test_every_address_unreachable_raises_the_last_error(
    error: type[BaseException],
) -> None:
    """Failover must not swallow a genuine outage into a silent success."""
    wrapped = _Wrapped(unreachable={"192.0.2.1", "192.0.2.2"}, error=error)
    backend = _pinned_network_backend(_HOST, _ADDRS, wrapped)

    with pytest.raises(error, match="no route"):
        backend.connect_tcp(_HOST, 443)

    assert wrapped.attempts == ["192.0.2.1", "192.0.2.2"], "each address tried once"


def test_attempts_are_bounded_by_the_address_count() -> None:
    """The cycle is infinite; the retry loop must not be."""
    wrapped = _Wrapped(unreachable={"192.0.2.1", "192.0.2.2"}, error=httpcore.ConnectError)
    backend = _pinned_network_backend(_HOST, _ADDRS, wrapped)

    with pytest.raises(httpcore.ConnectError, match="no route"):
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
