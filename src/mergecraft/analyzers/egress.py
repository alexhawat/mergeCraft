"""Filtered analyzer egress — netns + host FORWARD allowlist, never HTTP_PROXY.

Chosen enforcement (plan 15 W3 Step 3): a dedicated netns whose only route is
a veth, with host ``FORWARD`` limited to allowlisted destinations. DNS-only
filtering was rejected as bypassable by literal IPs. Classic seccomp-BPF
cannot dereference ``sockaddr``. ``HTTP_PROXY`` as the wall is rejected: Go
analyzers (``osv-scanner``, ``trivy``) ignore it, so the kernel filter is the
wall, not a proxy env var. A loopback CONNECT proxy that encodes the same
hostname policy for tests lives in
``tests/analyzers/support_allowlist_proxy.py`` — it is test scaffolding
production never runs, so it does not ship in ``src/`` (#606).

Enforcement is by IP address, not hostname: the FORWARD rules below cannot
see SNI or a Host header. A CDN-hosted allowlist entry (``api.osv.dev``, the
trivy DB) shares its IP with every other domain the CDN serves — all of
which become reachable too. Read this as a hostname policy enforced at IP
granularity, not a hostname-precise filter (#606).

FORWARD rules run inside a dedicated chain entered from the *top* of
``FORWARD`` (``iptables -I FORWARD 1 ...``), never appended to the end of
``FORWARD`` directly. iptables is first-match-wins, so appending would let
any pre-existing broad ``ACCEPT`` earlier in the chain — firewalld, libvirt,
a CNI plugin, a self-hosted runner's own config — silently shadow the
allowlist while ``iptables`` itself reports success. Entering from the top
makes the dedicated chain authoritative for this veth regardless of what
else is in ``FORWARD`` (#606).

IPv6 is disabled inside the netns (``sysctl -w net.ipv6.conf.*.disable_ipv6``)
rather than left unfiltered by omission. ``iptables`` only inspects IPv4, so
without an explicit deny the v6 path would depend on the netns never
acquiring a v6 address or route rather than on a rule that stops it (#606).

DNS is permitted to the configured resolvers — by default the host's own
``/etc/resolv.conf`` nameservers rather than a hardcoded public resolver,
see ``default_dns_resolvers()`` — for *any* query name. That is a known,
accepted residual risk, not an oversight: untrusted analyzer code can still
exfiltrate data by encoding it into DNS labels resolved through an allowed
resolver. Nothing here inspects DNS payloads or restricts query names; only
non-DNS egress to non-allowlisted destinations is blocked (#606).

The kernel backend typically lacks ``CAP_NET_ADMIN`` / ``CAP_SYS_ADMIN`` in
the GitHub Action image, so that path stays fail-closed unless an operator
opts into ``MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME``. The Action image
instead uses the userspace backend (user+net namespace + parent TCP relay)
when ``unshare --user --map-root-user --net`` and ``iptables`` work — Go
scanners cannot bypass it by ignoring ``HTTP_PROXY``.
"""

from __future__ import annotations

import functools
import ipaddress
import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol
from urllib.parse import urlparse

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Iterable

EgressBackend = Literal["none", "kernel", "userspace"]


class EgressSession(Protocol):
    """Kernel or userspace filtered-egress session."""

    def start(self) -> None: ...

    def close(self) -> None: ...

    def wrap_argv(self, argv: list[str]) -> list[str]: ...


_VETH_PROBE_PREFIX = "mcfg"
_FALLBACK_DNS_RESOLVERS: tuple[str, ...] = ("1.1.1.1",)
_RESOLV_CONF_PATH = Path("/etc/resolv.conf")
_SUBNET_OCTET_MAX = 250
_SETUP_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class FilteredEgressProbe:
    """Result of probing whether this runtime can enforce filtered egress."""

    network_namespace: bool
    veth: bool
    ip_netns: bool
    iptables: bool
    available: bool
    reason: str
    backend: EgressBackend = "none"
    user_namespace: bool = False


class FilteredEgressSetupError(Exception):
    """Filtered netns could not be applied; callers must skip, not unwrap."""


def allowlist_hosts(entries: Iterable[str]) -> frozenset[str]:
    """Return hostname allowlist entries (strip URL schemes and ports)."""
    hosts: set[str] = set()
    for raw in entries:
        item = raw.strip()
        if not item:
            continue
        if "://" in item:
            parsed = urlparse(item)
            host = parsed.hostname or ""
        else:
            host = item.split("/", 1)[0]
            host = host.split(":", 1)[0]
        host = host.strip(".").casefold()
        if host:
            hosts.add(host)
    return frozenset(hosts)


def host_is_allowlisted(host: str, allowed: frozenset[str]) -> bool:
    """Return True when ``host`` matches an allowlist entry (exact or parent)."""
    candidate = host.strip(".").casefold()
    if not candidate:
        return False
    if candidate in allowed:
        return True
    return any(candidate.endswith(f".{entry}") for entry in allowed)


def _can_unshare_net() -> bool:
    try:
        completed = subprocess.run(
            ["unshare", "--net", "true"],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _can_create_veth() -> bool:
    if shutil.which("ip") is None:
        return False
    suffix = os.getpid() % 10_000
    host_name = f"{_VETH_PROBE_PREFIX}{suffix}h"
    peer_name = f"{_VETH_PROBE_PREFIX}{suffix}c"
    created = subprocess.run(
        ["ip", "link", "add", host_name, "type", "veth", "peer", "name", peer_name],
        check=False,
        capture_output=True,
        timeout=5,
    )
    if created.returncode != 0:
        return False
    subprocess.run(
        ["ip", "link", "delete", host_name],
        check=False,
        capture_output=True,
        timeout=5,
    )
    return True


def _can_ip_netns() -> bool:
    if shutil.which("ip") is None:
        return False
    name = f"{_VETH_PROBE_PREFIX}ns{os.getpid() % 10_000}"
    created = subprocess.run(
        ["ip", "netns", "add", name],
        check=False,
        capture_output=True,
        timeout=5,
    )
    if created.returncode != 0:
        return False
    subprocess.run(
        ["ip", "netns", "delete", name],
        check=False,
        capture_output=True,
        timeout=5,
    )
    return True


def _can_iptables() -> bool:
    return shutil.which("iptables") is not None and shutil.which("setpriv") is not None


def _probe_kernel_filtered_egress() -> FilteredEgressProbe:
    """Probe host netns + veth + iptables. Requires the isolated-runtime opt-in."""
    net = _can_unshare_net()
    veth = _can_create_veth() if net else False
    ip_netns = _can_ip_netns() if veth else False
    iptables = _can_iptables() if ip_netns else False
    if net and veth and ip_netns and iptables:
        return FilteredEgressProbe(
            network_namespace=True,
            veth=True,
            ip_netns=True,
            iptables=True,
            available=True,
            reason="",
            backend="kernel",
        )
    missing: list[str] = []
    if not net:
        missing.append("unshare --net")
    if net and not veth:
        missing.append("veth (CAP_NET_ADMIN)")
    if veth and not ip_netns:
        missing.append("ip netns (CAP_SYS_ADMIN)")
    if ip_netns and not iptables:
        missing.append("iptables / setpriv")
    reason = "filtered egress unavailable: " + ", ".join(missing)
    logger.info("{}", reason)
    return FilteredEgressProbe(
        network_namespace=net,
        veth=veth,
        ip_netns=ip_netns,
        iptables=iptables,
        available=False,
        reason=reason,
        backend="none",
    )


@functools.lru_cache(maxsize=1)
def probe_filtered_egress() -> FilteredEgressProbe:
    """Probe userspace first, then the opt-in kernel backend."""
    from mergecraft.analyzers.egress_userspace import probe_userspace_egress

    userspace = probe_userspace_egress()
    want_kernel = os.environ.get("MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME") == "1"
    if want_kernel:
        kernel = _probe_kernel_filtered_egress()
        if kernel.available:
            return kernel
        if userspace.available:
            return userspace
        return kernel
    if userspace.available:
        return userspace
    reason = (
        "filtered egress unavailable: kernel backend requires an operator-owned "
        f"isolated runtime; {userspace.reason}"
    )
    return FilteredEgressProbe(
        network_namespace=userspace.network_namespace,
        veth=False,
        ip_netns=False,
        iptables=userspace.iptables,
        available=False,
        reason=reason,
        backend="none",
        user_namespace=userspace.user_namespace,
    )


def filtered_egress_available() -> bool:
    """True when this runtime can enforce an allowlist inside the sandbox."""
    return probe_filtered_egress().available


def reset_filtered_egress_cache() -> None:
    """Clear the filtered-egress probe cache (tests / xdist)."""
    probe_filtered_egress.cache_clear()


def resolve_allowlist_ips(entries: Iterable[str]) -> frozenset[str]:
    """Resolve allowlist hostnames to IPv4 addresses (fail-closed if none)."""
    ips: set[str] = set()
    for host in allowlist_hosts(entries):
        try:
            infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        except OSError:
            continue
        for info in infos:
            ip = info[4][0]
            if isinstance(ip, str) and ip:
                ips.add(ip)
    return frozenset(ips)


def wrap_argv_for_filtered_netns(argv: list[str], ns_name: str) -> list[str]:
    """Join a named netns and drop ``--net`` so unshare does not replace it."""
    cleaned = list(argv)
    offset = 1 if cleaned and cleaned[0] == "sudo" else 0
    if len(cleaned) > offset and cleaned[offset] == "unshare":
        # Only strip our wrapper option; an analyzer may itself accept --net.
        end = next(
            (i for i in range(offset + 1, len(cleaned)) if not cleaned[i].startswith("-")),
            len(cleaned),
        )
        cleaned = (
            cleaned[: offset + 1]
            + [part for part in cleaned[offset + 1 : end] if part != "--net"]
            + cleaned[end:]
        )
    return ["ip", "netns", "exec", ns_name, *cleaned]


def _is_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return True


def _parse_resolv_conf(path: Path = _RESOLV_CONF_PATH) -> tuple[str, ...]:
    """Return IPv4 ``nameserver`` entries from a resolv.conf, in file order, deduped.

    IPv6 nameservers are skipped: they feed directly into ``iptables -d``
    ACCEPT rules (finding 3/4), and ``iptables`` rejects an IPv6 address
    outright, which would abort session setup rather than just skip that
    one resolver.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ()
    resolvers: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        parts = stripped.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            ip = parts[1].strip()
            if ip and _is_ipv4(ip) and ip not in resolvers:
                resolvers.append(ip)
    return tuple(resolvers)


def default_dns_resolvers() -> tuple[str, ...]:
    """Host resolvers for the netns' DNS allowlist (#606 finding 3).

    Defaults to the host's own ``/etc/resolv.conf`` nameservers rather than
    a hardcoded public resolver: a fixed ``1.1.1.1`` leaks every analyzer's
    resolution to Cloudflare and breaks outright on runners where 1.1.1.1
    is itself blocked by egress policy — a common corporate CI
    configuration. Override with ``MERGECRAFT_EGRESS_DNS_RESOLVERS``
    (comma-separated IPv4 addresses) when the host file is not
    representative. Falls back to a public resolver only when the host has
    neither an override nor a parseable IPv4 ``resolv.conf`` entry (e.g. an
    IPv6-only resolver setup).

    DNS to an allowed resolver remains permitted for *any* query name —
    changing the resolver narrows who receives the query, it does not close
    the DNS-tunneling exfiltration channel documented in the module
    docstring.
    """
    override = os.environ.get("MERGECRAFT_EGRESS_DNS_RESOLVERS", "").strip()
    if override:
        resolvers = tuple(
            ip.strip() for ip in override.split(",") if ip.strip() and _is_ipv4(ip.strip())
        )
        if resolvers:
            return resolvers
    parsed = _parse_resolv_conf()
    if parsed:
        return parsed
    return _FALLBACK_DNS_RESOLVERS


@dataclass(slots=True)
class FilteredNetnsSession:
    """Host-side veth + named netns + iptables FORWARD allowlist.

    Enforcement is the kernel filter, not ``HTTP_PROXY``. Setup failure must
    skip the analyzer; it must never fall back to host networking.
    """

    allowed_hosts: list[str]
    dns_resolvers: tuple[str, ...] = field(default_factory=default_dns_resolvers)
    ns_name: str = field(init=False)
    _host_veth: str = field(init=False)
    _peer_veth: str = field(init=False)
    _host_ip: str = field(init=False)
    _peer_ip: str = field(init=False)
    _cidr: str = field(init=False)
    _comment: str = field(init=False)
    _chain: str = field(init=False)
    _chain_created: bool = field(default=False, init=False)
    _cleanup_commands: list[list[str]] = field(default_factory=list, init=False)
    _netns_created: bool = field(default=False, init=False)
    _veth_created: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        suffix = secrets.token_hex(4)
        session_id = f"mc-eg-{suffix}"
        self.ns_name = session_id
        self._comment = session_id
        # Random session identity separates overlapping sessions in one process.
        self._chain = session_id
        self._host_veth = f"mcfh{suffix}"
        self._peer_veth = f"mcfp{suffix}"
        # _host_ip / _peer_ip / _cidr are resolved in start() via a
        # collision-checked search (see _select_subnet) rather than a bare
        # pid modulo, which collided 1-in-250 across concurrent processes.
        self._host_ip = ""
        self._peer_ip = ""
        self._cidr = ""

    def start(self) -> None:
        """Serialize subnet allocation and create only this session's state.

        The lock is host-owned, never supplied by repository contents. Each
        session still has independent rules and cleanup after setup completes.
        """
        probe = probe_filtered_egress()
        if probe.backend != "kernel":
            raise FilteredEgressSetupError(
                probe.reason or "kernel filtered egress is not the active backend"
            )

        import fcntl

        if self._netns_created:
            raise FilteredEgressSetupError("session is already started")
        if not _SETUP_LOCK.acquire(timeout=10):
            raise FilteredEgressSetupError("timed out waiting for session allocation")
        try:
            try:
                fd = os.open(
                    "/run/mergecraft-egress.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
                )
                with os.fdopen(fd, "w") as lock:
                    deadline = time.monotonic() + 10
                    while True:
                        try:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            if time.monotonic() >= deadline:
                                raise FilteredEgressSetupError(
                                    "timed out waiting for host session allocation"
                                ) from None
                            time.sleep(0.05)
                    self._start_locked()
            finally:
                _SETUP_LOCK.release()
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.close()
            raise FilteredEgressSetupError(f"filtered egress setup failed: {exc}") from exc

    def _start_locked(self) -> None:
        """Create the namespace while holding the allocation lock."""
        try:
            probe = probe_filtered_egress()
            if probe.backend != "kernel":
                raise FilteredEgressSetupError(
                    probe.reason or "kernel filtered egress is not the active backend"
                )
            # Never sweep other sessions: PID reuse is not proof of ownership.
            self._enable_forward()
            ips = resolve_allowlist_ips(self.allowed_hosts)
            if not ips:
                raise FilteredEgressSetupError("allowlist resolved to no addresses")
            self._select_subnet()
            self._cmd(["ip", "netns", "add", self.ns_name])
            self._netns_created = True
            self._cmd(
                [
                    "ip",
                    "link",
                    "add",
                    self._host_veth,
                    "type",
                    "veth",
                    "peer",
                    "name",
                    self._peer_veth,
                ]
            )
            self._veth_created = True
            self._cmd(["ip", "link", "set", self._peer_veth, "netns", self.ns_name])
            self._cmd(["ip", "addr", "add", f"{self._host_ip}/30", "dev", self._host_veth])
            self._cmd(["ip", "link", "set", self._host_veth, "up"])
            self._ns(["ip", "addr", "add", f"{self._peer_ip}/30", "dev", self._peer_veth])
            self._ns(["ip", "link", "set", self._peer_veth, "up"])
            self._ns(["ip", "link", "set", "lo", "up"])
            self._disable_ipv6()
            self._ns(["ip", "route", "add", "default", "via", self._host_ip])
            self._write_ns_resolv()
            self._apply_filter(ips)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Tear down iptables, veth, and the named netns."""
        self._flush_iptables()
        if self._veth_created and self._cleanup_command(["ip", "link", "delete", self._host_veth]):
            self._veth_created = False
        if self._netns_created and self._cleanup_command(["ip", "netns", "delete", self.ns_name]):
            self._netns_created = False
            try:
                shutil.rmtree(f"/etc/netns/{self.ns_name}")
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning("filtered egress resolver cleanup failed: {}", exc)

    def _cleanup_command(self, argv: list[str]) -> bool:
        """Report failed cleanup and retain ownership for a later retry."""
        try:
            self._cmd(argv)
        except (FilteredEgressSetupError, OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("filtered egress cleanup incomplete for {}: {}", self.ns_name, exc)
            return False
        return True

    def __enter__(self) -> FilteredNetnsSession:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def wrap_argv(self, argv: list[str]) -> list[str]:
        """Prefix argv with ``ip netns exec`` and drop ``--net``."""
        return wrap_argv_for_filtered_netns(argv, self.ns_name)

    def _cmd(self, argv: list[str]) -> None:
        if argv and argv[0] == "iptables":
            argv = [argv[0], "-w", "5", *argv[1:]]
        completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=10)
        if completed.returncode != 0:
            err = (completed.stderr or completed.stdout or "").strip()
            raise FilteredEgressSetupError(f"{' '.join(argv)}: {err}")

    def _ns(self, argv: list[str]) -> None:
        self._cmd(["ip", "netns", "exec", self.ns_name, *argv])

    def _select_subnet(self) -> None:
        """Pick a ``/30`` in ``10.255.0.0/16`` not already assigned on the host.

        Replaces a bare ``os.getpid() % 250`` (#606 nit): two concurrent
        ``mergecraft`` processes on the same host had a 1-in-250 chance of
        picking the same subnet, with overlapping routes and MASQUERADE
        rules. This checks the host's actual addresses first and only
        falls back to the pid-derived octet as a starting point for the
        search, not as the answer itself.
        """
        used = self._used_third_octets()
        start = (os.getpid() % _SUBNET_OCTET_MAX) + 1
        for delta in range(_SUBNET_OCTET_MAX):
            candidate = ((start - 1 + delta) % _SUBNET_OCTET_MAX) + 1
            if candidate not in used:
                self._host_ip = f"10.255.{candidate}.1"
                self._peer_ip = f"10.255.{candidate}.2"
                self._cidr = f"10.255.{candidate}.0/30"
                return
        raise FilteredEgressSetupError("no free 10.255.0.0/16 /30 subnet for filtered egress")

    @staticmethod
    def _used_third_octets() -> set[int]:
        """Exclude connected and routed subnets; inspection failure is unsafe."""
        try:
            result = subprocess.run(
                ["ip", "-j", "-4", "route", "show", "table", "all"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            routes = json.loads(result.stdout)
            if not isinstance(routes, list):
                raise ValueError("route output is not a list")
            networks = []
            for row in routes:
                destination = row.get("dst", "default")
                if destination != "default":
                    networks.append(ipaddress.ip_network(destination, strict=False))
            return {
                octet
                for octet in range(1, _SUBNET_OCTET_MAX + 1)
                if any(
                    ipaddress.ip_network(f"10.255.{octet}.0/30").overlaps(net) for net in networks
                )
            }
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError) as exc:
            raise FilteredEgressSetupError(f"cannot safely inspect existing routes: {exc}") from exc

    def _disable_ipv6(self) -> None:
        """Disable IPv6 inside the netns (#606 finding 3).

        ``iptables`` only inspects IPv4, so an unfiltered v6 path would
        otherwise depend on the netns never acquiring a v6 address/route
        rather than on an explicit deny. This closes that path outright.
        """
        for scope in ("all", "default", "lo"):
            self._ns(["sysctl", "-w", f"net.ipv6.conf.{scope}.disable_ipv6=1"])

    def _write_ns_resolv(self) -> None:
        path = Path("/etc/netns") / self.ns_name
        lines = "".join(f"nameserver {ip}\n" for ip in self.dns_resolvers)
        try:
            path.mkdir(parents=True, exist_ok=True)
            (path / "resolv.conf").write_text(lines, encoding="utf-8")
        except OSError as exc:
            raise FilteredEgressSetupError(f"cannot write netns resolv.conf: {exc}") from exc

    def _enable_forward(self) -> None:
        """Require operator-enabled routing without changing shared host policy."""
        try:
            enabled = Path("/proc/sys/net/ipv4/ip_forward").read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise FilteredEgressSetupError(f"cannot inspect ip_forward: {exc}") from exc
        if enabled != "1":
            raise FilteredEgressSetupError(
                "filtered egress requires operator-enabled IPv4 forwarding"
            )

    def _ipt_chain(self, spec: list[str]) -> None:
        self._cmd(["iptables", "-A", self._chain, *spec])

    def _apply_filter(self, dest_ips: frozenset[str]) -> None:
        """Build the allowlist inside a dedicated chain entered from the top of FORWARD.

        Finding 1: appending straight to ``FORWARD`` is first-match-wins,
        so a pre-existing broad ``ACCEPT`` earlier in the chain (firewalld,
        libvirt, a CNI plugin, a self-hosted runner's own rules) would
        silently shadow an appended ``DROP`` — ``iptables`` reports success
        either way. A dedicated chain entered via ``-I FORWARD 1`` is
        authoritative for this veth regardless of what else is in
        ``FORWARD``. Two jump rules are needed — one per direction — since
        a forwarded packet matches ``-i host_veth`` (egress, container to
        WAN) or ``-o host_veth`` (return traffic, WAN to container) but
        never both.
        """
        comment = ["-m", "comment", "--comment", self._comment]
        self._cmd(["iptables", "-N", self._chain])
        self._chain_created = True
        self._cleanup_commands.extend(
            [["iptables", "-X", self._chain], ["iptables", "-F", self._chain]]
        )
        # INPUT is a different route from FORWARD: always deny host services.
        input_rule = ["INPUT", "-i", self._host_veth, *comment, "-j", "DROP"]
        self._cmd(["iptables", "-I", "INPUT", "1", *input_rule[1:]])
        self._cleanup_commands.append(["iptables", "-D", *input_rule])
        for direction in ("-o", "-i"):
            rule = ["FORWARD", direction, self._host_veth, *comment, "-j", self._chain]
            self._cmd(["iptables", "-I", "FORWARD", "1", *rule[1:]])
            self._cleanup_commands.append(["iptables", "-D", *rule])

        self._ipt_chain(
            ["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", *comment, "-j", "ACCEPT"]
        )
        for ip in self.dns_resolvers:
            self._ipt_chain(["-p", "udp", "-d", ip, "--dport", "53", *comment, "-j", "ACCEPT"])
            self._ipt_chain(["-p", "tcp", "-d", ip, "--dport", "53", *comment, "-j", "ACCEPT"])
        for ip in sorted(dest_ips):
            self._ipt_chain(["-d", ip, *comment, "-j", "ACCEPT"])
        self._ipt_chain([*comment, "-j", "DROP"])

        nat_rule = ["POSTROUTING", "-s", self._cidr, *comment, "-j", "MASQUERADE"]
        self._cmd(["iptables", "-t", "nat", "-A", *nat_rule])
        self._cleanup_commands.append(["iptables", "-t", "nat", "-D", *nat_rule])

    def _flush_iptables(self) -> None:
        """Remove only successfully created rules, preserving failed undo work."""
        failed = []
        for command in reversed(self._cleanup_commands):
            if not self._cleanup_command(command):
                failed.append(command)
        self._cleanup_commands = list(reversed(failed))
        self._chain_created = bool(failed)


def start_filtered_egress_session(allowed_hosts: list[str]) -> EgressSession:
    """Start the kernel or userspace backend selected by ``probe_filtered_egress``."""
    probe = probe_filtered_egress()
    if probe.backend == "kernel":
        kernel = FilteredNetnsSession(allowed_hosts)
        kernel.start()
        return kernel
    if probe.backend == "userspace":
        from mergecraft.analyzers.egress_userspace import UserspaceEgressSession

        userspace = UserspaceEgressSession(allowed_hosts)
        userspace.start()
        return userspace
    raise FilteredEgressSetupError(probe.reason)


__all__ = [
    "EgressSession",
    "FilteredEgressProbe",
    "FilteredEgressSetupError",
    "FilteredNetnsSession",
    "allowlist_hosts",
    "default_dns_resolvers",
    "filtered_egress_available",
    "host_is_allowlisted",
    "probe_filtered_egress",
    "reset_filtered_egress_cache",
    "resolve_allowlist_ips",
    "start_filtered_egress_session",
    "wrap_argv_for_filtered_netns",
]
