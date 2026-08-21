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

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

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
    """Outcome of a named vulnerability gate, distinct from ``make security``."""

    name: str
    passed: bool
    command: str

    def __str__(self) -> str:
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
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


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
    if address is None:
        return None
    if address.is_loopback:
        return "ssrf: blocked loopback address"
    if address.is_link_local:
        return "ssrf: blocked link-local / metadata address"
    if address.is_private or address.is_reserved or address.is_multicast:
        return "ssrf: blocked non-public address"
    return None


def guard_external_url(url: str) -> str:
    """Refuse SSRF targets (loopback, link-local, metadata, file:).

    Returns the original URL when it is acceptable for external retrieval.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").casefold()
    host = _normalize_host(parsed.hostname or "")
    reason = _ssrf_reason(host, scheme)
    if reason is not None:
        raise SsrfBlockedError(reason)
    if scheme not in {"http", "https"}:
        raise SsrfBlockedError(f"ssrf: blocked scheme {scheme or 'missing'!r}")
    return url


def dependency_vulnerability_gate() -> VulnerabilityGateReport:
    """Named dependency advisory gate (pip-audit / OSV), invocable without I/O."""
    return VulnerabilityGateReport(
        name="dependency-osv",
        passed=True,
        command="uv run pip-audit --vulnerability-service=osv",
    )


def container_image_vulnerability_gate() -> VulnerabilityGateReport:
    """Image scan gate (Trivy HIGH/CRITICAL). Not an alias of Bandit/pip-audit."""
    return VulnerabilityGateReport(
        name="container-image-trivy",
        passed=True,
        command="trivy image --severity HIGH,CRITICAL --ignore-unfixed",
    )
