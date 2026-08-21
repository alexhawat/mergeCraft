"""Egress allow-list, SSRF guards, and vulnerability gates (#362).

Network-boundary controls for deployments that can restrict outbound
traffic. Approval still flows only through ``decide_approval()`` (D14).

Exports:
    DEFAULT_EGRESS_ALLOWLIST: Default hosts when egress filtering is on.
    VulnerabilityGateReport: Named scan outcome (not ``make security``).
    allow_egress: True iff the host is on the allow-list.
    container_image_vulnerability_gate: Image scan (Trivy), not Bandit.
    dependency_vulnerability_gate: Dependency advisory scan (pip-audit).
    guard_external_url: Raise when a retrieval URL is an SSRF target.
"""

from __future__ import annotations

import contextlib
import ipaddress
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

DEFAULT_EGRESS_ALLOWLIST: frozenset[str] = frozenset(
    {
        "api.github.com",
        "github.com",
        "www.github.com",
        "ghcr.io",
        "objects.githubusercontent.com",
    }
)

_BLOCKED_SCHEMES: frozenset[str] = frozenset(
    {"file", "ftp", "gopher", "dict", "data", "javascript"}
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
    if check == ipaddress.ip_address("169.254.169.254"):
        return "ssrf: blocked metadata address"
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


def _ssrf_reason(host: str, scheme: str) -> str | None:
    if scheme in _BLOCKED_SCHEMES:
        if scheme == "file":
            return "ssrf: blocked file: URL"
        return f"ssrf: blocked scheme {scheme!r}"
    if not host:
        return "ssrf: blocked URL with empty host"
    if host in _LOOPBACK_HOSTS:
        return "ssrf: blocked loopback host"
    if host in _METADATA_HOSTS:
        return "ssrf: blocked metadata host"
    address = _ip_from_host(host)
    if address is not None:
        return _blocked_address(address)
    for resolved in _resolve_host_addresses(host):
        reason = _blocked_address(resolved)
        if reason is not None:
            return reason
    return None


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
    reason = _ssrf_reason(host, scheme)
    if reason is not None:
        raise SsrfBlockedError(reason)
    if scheme not in {"http", "https"}:
        raise SsrfBlockedError(f"ssrf: blocked scheme {scheme or 'missing'!r}")
    literal = _ip_from_host(host)
    if literal is not None:
        addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...] = (literal,)
    else:
        addresses = _resolve_host_addresses(host)
        for resolved in addresses:
            blocked = _blocked_address(resolved)
            if blocked is not None:
                raise SsrfBlockedError(blocked)
    return GuardedUrl(url=url, host=host, addresses=addresses)


@contextlib.contextmanager
def pin_host_resolution(
    host: str,
    addresses: Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address],
) -> Iterator[None]:
    """Force ``socket.getaddrinfo`` for ``host`` to the already-validated IPs."""
    normalized = _normalize_host(host)
    pinned = tuple(addresses)
    original = socket.getaddrinfo

    def _pinned(
        name: str,
        port: Any,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[Any, ...]]:
        if _normalize_host(str(name)) != normalized:
            return original(name, port, family, type, proto, flags)
        port_i = 0
        if port is not None and str(port).isdigit():
            port_i = int(port)
        results: list[tuple[Any, ...]] = []
        for address in pinned:
            if isinstance(address, ipaddress.IPv6Address):
                sock_family = socket.AF_INET6
                sockaddr: tuple[Any, ...] = (str(address), port_i, 0, 0)
            else:
                sock_family = socket.AF_INET
                sockaddr = (str(address), port_i)
            if family not in {0, sock_family}:
                continue
            results.append((sock_family, type or socket.SOCK_STREAM, proto, "", sockaddr))
        if not results:
            msg = f"ssrf: no pinned address for {host!r} (fail-closed)"
            raise SsrfBlockedError(msg)
        return results

    socket.getaddrinfo = _pinned  # type: ignore[assignment]  # — stdlib getaddrinfo is overloaded; pin to validated IPs
    try:
        yield
    finally:
        socket.getaddrinfo = original


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
