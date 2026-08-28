"""Egress allow-list, SSRF guards, and vulnerability gates (#362).

Network-boundary controls for deployments that can restrict outbound
traffic. Approval still flows only through ``decide_approval()`` (D14).

``PinnedHTTPTransport`` couples to httpx/httpcore private APIs
(``HTTPTransport._pool`` and ``ConnectionPool._network_backend``). Pin
``httpx`` in consuming deployments and re-verify on httpx upgrades.

Exports:
    DEFAULT_EGRESS_ALLOWLIST: Default hosts when egress filtering is on.
    VulnerabilityGateReport: Named scan outcome (not ``make security``).
    allow_egress: True iff the host is on the allow-list.
    container_image_vulnerability_gate: Image scan (Trivy), not Bandit.
    dependency_vulnerability_gate: Dependency advisory scan (pip-audit).
    guard_external_url: Raise when a retrieval URL is an SSRF target.
    pinned_http_transport: Per-client transport that pins DNS without global hooks.
    pinned_request_metadata: Host/SNI/connect metadata for a pinned HTTPS request.
"""

from __future__ import annotations

import ipaddress
import itertools
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpcore
import httpx

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_EGRESS_ALLOWLIST: frozenset[str] = frozenset(
    {
        "api.github.com",
        "github.com",
        "www.github.com",
        "ghcr.io",
        "objects.githubusercontent.com",
    }
)

_METADATA_HOSTS: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata.internal",
        "instance-data",
    }
)
_LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "ip6-localhost", "ip6-loopback"})


class SsrfBlockedError(PermissionError):
    """Raised when an external URL is an SSRF, loopback, or metadata target."""


@dataclass(frozen=True, slots=True)
class VulnerabilityGateReport:
    """Outcome of a named vulnerability gate, distinct from ``make security``.

    ``passed`` is False when the named tool did not run (fail-closed, not a
    fake scan pass).
    """

    name: str
    passed: bool
    command: str
    ran: bool = False

    def __str__(self) -> str:
        if not self.ran:
            return f"{self.name} not_run: {self.command}"
        status = "passed" if self.passed else "failed"
        return f"{self.name} {status}: {self.command}"


def _normalize_host(host: str) -> str:
    return host.strip().rstrip(".").casefold()


def allow_egress(host: str, *, allowlist: frozenset[str] | None = None) -> bool:
    """Return whether outbound traffic to ``host`` is permitted.

    Deployments that cannot filter egress still call this; a denied host
    is False so callers fail closed when they apply the list.
    """
    permitted = allowlist if allowlist is not None else DEFAULT_EGRESS_ALLOWLIST
    return _normalize_host(host) in permitted


def _ip_from_host(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    stripped = host.strip("[]")
    try:
        return ipaddress.ip_address(stripped)
    except ValueError:
        pass
    if stripped.isdigit():
        try:
            return ipaddress.IPv4Address(int(stripped))
        except (ValueError, OverflowError):
            return None
    lowered = stripped.casefold()
    if lowered.startswith("0x"):
        try:
            return ipaddress.IPv4Address(int(lowered, 16))
        except (ValueError, OverflowError):
            return None
    parts = stripped.split(".")
    if parts and all(part.isdigit() for part in parts) and 1 <= len(parts) <= 4:
        try:
            packed = socket.inet_aton(stripped)
        except OSError:
            return None
        return ipaddress.IPv4Address(packed)
    return None


def _blocked_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> str | None:
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    check = mapped if mapped is not None else address
    if check.is_loopback:
        return "ssrf: blocked loopback address"
    if check.is_link_local:
        return "ssrf: blocked link-local / metadata address"
    if check.is_private or check.is_reserved or check.is_multicast:
        return "ssrf: blocked non-public address"
    return None


def _resolve_host_addresses(host: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror) as exc:
        msg = f"ssrf: DNS resolve failed for {host!r} (fail-closed)"
        raise SsrfBlockedError(msg) from exc
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        raw = sockaddr[0]
        try:
            addresses.append(ipaddress.ip_address(raw))
        except ValueError:
            continue
    if not addresses:
        msg = f"ssrf: DNS resolve failed for {host!r} (fail-closed)"
        raise SsrfBlockedError(msg)
    return tuple(addresses)


def _validate_retrieval_host(
    host: str,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    """SSRF-check ``host`` and return the validated addresses (DNS resolved once)."""
    if not host:
        raise SsrfBlockedError("ssrf: blocked URL with empty host")
    if host in _LOOPBACK_HOSTS:
        raise SsrfBlockedError("ssrf: blocked loopback host")
    if host in _METADATA_HOSTS:
        raise SsrfBlockedError("ssrf: blocked metadata host")
    literal = _ip_from_host(host)
    if literal is not None:
        reason = _blocked_address(literal)
        if reason is not None:
            raise SsrfBlockedError(reason)
        return (literal,)
    addresses = _resolve_host_addresses(host)
    for resolved in addresses:
        reason = _blocked_address(resolved)
        if reason is not None:
            raise SsrfBlockedError(reason)
    return addresses


def guard_external_url(url: str) -> str:
    """Refuse SSRF targets (loopback, link-local, metadata, file:, odd IP forms).

    DNS that fails to resolve is blocked (fail-closed). Returns the original
    URL when it is acceptable for external retrieval.
    """
    return inspect_external_url(url).url


@dataclass(frozen=True, slots=True)
class GuardedUrl:
    """An SSRF-checked retrieval URL plus the addresses used to validate it."""

    url: str
    host: str
    addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]


def inspect_external_url(url: str) -> GuardedUrl:
    """SSRF-check ``url`` and return the host plus resolved public addresses."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").casefold()
    host = _normalize_host(parsed.hostname or "")
    if scheme not in {"http", "https"}:
        raise SsrfBlockedError(f"ssrf: blocked scheme {scheme or 'missing'!r}")
    addresses = _validate_retrieval_host(host)
    return GuardedUrl(url=url, host=host, addresses=addresses)


@dataclass(frozen=True, slots=True)
class PinnedRequestMetadata:
    """Connection metadata for a guarded HTTPS request pinned to validated IPs."""

    host: str
    server_hostname: str
    connect_host: str


def pinned_request_metadata(
    url: str,
    *,
    pinned_ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> PinnedRequestMetadata:
    """Return Host/SNI/connect targets for a pinned HTTPS request.

    Test and documentation helper: production callers use
    :func:`pinned_http_transport`, which applies the same Host/SNI pinning.
    """
    parsed = urlparse(url)
    host = _normalize_host(parsed.hostname or "")
    return PinnedRequestMetadata(
        host=host,
        server_hostname=host,
        connect_host=str(pinned_ip),
    )


# What a *backend* raises, which is not what the transport above it raises.
# ``httpcore`` maps socket failures to ``httpcore.ConnectError`` /
# ``ConnectTimeout`` inside ``connect_tcp``, and both derive from plain
# ``Exception`` — neither ``OSError`` nor ``httpx.TransportError`` catches
# them. httpx only wraps them into its own hierarchy further up, after this
# code has already run. Catching the wrong pair meant the failover loop
# exited on the first real connection failure while passing a test that
# raised ``OSError``. ``OSError`` is kept for a backend that raises a raw
# socket error without httpcore's mapping.
_CONNECT_ERRORS: tuple[type[BaseException], ...] = (
    httpcore.ConnectError,
    httpcore.ConnectTimeout,
    OSError,
)


def _pinned_network_backend(
    hostname: str,
    addresses: Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address],
    wrapped: Any,
) -> Any:
    """Return a ``NetworkBackend`` that dials validated IPs for ``hostname``."""
    from httpcore._backends.base import NetworkBackend

    normalized_hostname = _normalize_host(hostname)
    pinned_addresses = tuple(addresses)
    address_cycle = itertools.cycle(pinned_addresses) if pinned_addresses else None

    class PinnedNetworkBackend(NetworkBackend):
        def connect_tcp(
            self,
            host: str,
            port: int,
            timeout: float | None = None,
            local_address: str | None = None,
            socket_options: Any | None = None,
        ) -> Any:
            if address_cycle is None or _normalize_host(host) != normalized_hostname:
                return wrapped.connect_tcp(
                    host,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            # Every validated address, not just the first. Resolution can
            # return several and only some be reachable — a stale AAAA on a
            # v4-only runner is the ordinary case — and the transport runs
            # with httpx's default ``retries=0``, so a failure here ends the
            # request. Pinning turned "the client would have failed over" into
            # "the download aborts on the first unreachable answer".
            #
            # The cycle is retained so its rotation still spreads load across
            # calls; the attempt count is bounded by the address count so an
            # all-unreachable set cannot loop.
            # Seeded rather than left ``None``: an ``assert`` here would be
            # stripped under ``-O``, and this way an empty loop raises
            # something a reader can act on instead of an AttributeError.
            last_error: BaseException = RuntimeError(
                f"no validated address reachable for {hostname}"
            )
            for _ in range(len(pinned_addresses)):
                candidate = str(next(address_cycle))
                try:
                    return wrapped.connect_tcp(
                        candidate,
                        port,
                        timeout=timeout,
                        local_address=local_address,
                        socket_options=socket_options,
                    )
                except _CONNECT_ERRORS as exc:
                    last_error = exc
            raise last_error

        def connect_unix_socket(
            self,
            path: str,
            timeout: float | None = None,
            socket_options: Any | None = None,
        ) -> Any:
            return wrapped.connect_unix_socket(
                path,
                timeout=timeout,
                socket_options=socket_options,
            )

        def sleep(self, seconds: float) -> None:
            wrapped.sleep(seconds)

    return PinnedNetworkBackend()


class PinnedHTTPTransport(httpx.HTTPTransport):
    """HTTP transport that connects to validated IPs but keeps hostname Host/SNI."""

    def __init__(
        self,
        hostname: str,
        addresses: Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address],
        **kwargs: Any,
    ) -> None:
        # Coupled to httpx 0.28.x / httpcore: replaces ConnectionPool._network_backend
        # after the public HTTPTransport constructor builds the pool.
        super().__init__(**kwargs)
        self._server_hostname = _normalize_host(hostname)
        wrapped_backend = self._pool._network_backend
        self._pool._network_backend = _pinned_network_backend(
            self._server_hostname,
            addresses,
            wrapped_backend,
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        if _normalize_host(host) == self._server_hostname:
            extensions = dict(request.extensions)
            extensions.setdefault("sni_hostname", host)
            request = httpx.Request(
                method=request.method,
                url=request.url,
                headers=request.headers,
                content=request.content,
                extensions=extensions,
            )
        return super().handle_request(request)


def pinned_http_transport(
    hostname: str,
    addresses: Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address],
    **kwargs: Any,
) -> PinnedHTTPTransport:
    """Build a per-client transport pinned to already-validated addresses."""
    return PinnedHTTPTransport(hostname, addresses, **kwargs)


def dependency_vulnerability_gate() -> VulnerabilityGateReport:
    """Named dependency advisory gate. Does not report a pass without running."""
    return VulnerabilityGateReport(
        name="dependency-osv",
        passed=False,
        ran=False,
        command="uv run pip-audit --vulnerability-service=osv",
    )


def container_image_vulnerability_gate() -> VulnerabilityGateReport:
    """Image scan gate (Trivy). Does not report a pass without running."""
    return VulnerabilityGateReport(
        name="container-image-trivy",
        passed=False,
        ran=False,
        command="trivy image --severity HIGH,CRITICAL --ignore-unfixed",
    )
