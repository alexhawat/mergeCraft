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

The Action image typically lacks ``CAP_NET_ADMIN`` / ``CAP_SYS_ADMIN``, so
``filtered_egress_available()`` is False there and the untrusted path stays
fail-closed (named skip). Capable Linux runners (``ip netns`` plus veth plus
iptables) run isolated-to-allowlist instead.
"""

from __future__ import annotations

import contextlib
import functools
import ipaddress
import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Iterable

_VETH_PROBE_PREFIX = "mcfg"
_FALLBACK_DNS_RESOLVERS: tuple[str, ...] = ("1.1.1.1",)
_RESOLV_CONF_PATH = Path("/etc/resolv.conf")
_SESSION_ID_RE = re.compile(r"mc-eg-(\d+)-(\d+)")
_SUBNET_OCTET_MAX = 250


@dataclass(frozen=True, slots=True)
class FilteredEgressProbe:
    """Result of probing whether this runtime can enforce filtered egress."""

    network_namespace: bool
    veth: bool
    ip_netns: bool
    iptables: bool
    available: bool
    reason: str


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
    return shutil.which("iptables") is not None


@functools.lru_cache(maxsize=1)
def probe_filtered_egress() -> FilteredEgressProbe:
    """Probe netns + veth + iptables. Nothing is faked when a primitive is missing."""
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
        )
    missing: list[str] = []
    if not net:
        missing.append("unshare --net")
    if net and not veth:
        missing.append("veth (CAP_NET_ADMIN)")
    if veth and not ip_netns:
        missing.append("ip netns (CAP_SYS_ADMIN)")
    if ip_netns and not iptables:
        missing.append("iptables")
    reason = "filtered egress unavailable: " + ", ".join(missing)
    logger.info("{}", reason)
    return FilteredEgressProbe(
        network_namespace=net,
        veth=veth,
        ip_netns=ip_netns,
        iptables=iptables,
        available=False,
        reason=reason,
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
    cleaned = [part for part in argv if part != "--net"]
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


def _pid_alive(pid: int) -> bool:
    """True when ``pid`` names a live process (or one we lack permission to see)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # Any other errno (e.g. EPERM for a live-but-foreign pid) means the
        # process exists; only ESRCH (ProcessLookupError) says it does not.
        return True
    return True


def _stale_session_ids() -> set[str]:
    """``mc-eg-<pid>-<suffix>`` ids tagged on rules whose pid is now dead."""
    stale: set[str] = set()
    try:
        result = subprocess.run(
            ["iptables-save"], capture_output=True, text=True, timeout=5, check=False
        )
    except OSError:
        return stale
    for match in _SESSION_ID_RE.finditer(result.stdout):
        session_id = match.group(0)
        if session_id in stale:
            continue
        if not _pid_alive(int(match.group(1))):
            stale.add(session_id)
    return stale


def _delete_rules_matching(show_argv: list[str], delete_prefix: list[str], needle: str) -> None:
    """Convert each ``-A ...`` line containing ``needle`` to a ``-D`` and run it."""
    result = subprocess.run(show_argv, capture_output=True, text=True, timeout=5, check=False)
    for line in result.stdout.splitlines():
        if needle not in line or not line.startswith("-A "):
            continue
        argv = [*delete_prefix, *line[len("-A ") :].split()]
        with contextlib.suppress(OSError):
            subprocess.run(argv, check=False, capture_output=True, timeout=5)


def _sweep_session(session_id: str) -> None:
    """Remove FORWARD jump rules, the dedicated chain, the NAT rule, and any
    leftover veth/netns tagged with one dead session id."""
    _delete_rules_matching(["iptables", "-S", "FORWARD"], ["iptables", "-D", "FORWARD"], session_id)
    with contextlib.suppress(OSError):
        subprocess.run(["iptables", "-F", session_id], check=False, capture_output=True, timeout=5)
    with contextlib.suppress(OSError):
        subprocess.run(["iptables", "-X", session_id], check=False, capture_output=True, timeout=5)
    _delete_rules_matching(
        ["iptables", "-t", "nat", "-S", "POSTROUTING"],
        ["iptables", "-t", "nat", "-D", "POSTROUTING"],
        session_id,
    )
    match = _SESSION_ID_RE.match(session_id)
    if match is not None:
        veth_suffix = int(match.group(2))
        with contextlib.suppress(OSError):
            subprocess.run(
                ["ip", "link", "delete", f"mcfh{veth_suffix}"],
                check=False,
                capture_output=True,
                timeout=5,
            )
    with contextlib.suppress(OSError):
        subprocess.run(
            ["ip", "netns", "delete", session_id], check=False, capture_output=True, timeout=5
        )
    with contextlib.suppress(OSError):
        shutil.rmtree(f"/etc/netns/{session_id}", ignore_errors=True)


def sweep_orphaned_filtered_egress() -> None:
    """Best-effort cleanup of state a killed ``FilteredNetnsSession`` left behind (#606 finding 6).

    ``close()`` only runs on a clean exit; SIGKILL (CI cancellation, OOM, a
    job timeout) skips it and leaves the FORWARD jump rules, the dedicated
    chain, the NAT rule, and the veth/netns pair behind. Every rule this
    module creates is tagged ``mc-eg-<pid>-<suffix>`` in an iptables
    comment; this sweeps whatever still carries that tag for a pid that is
    no longer alive. Called at the start of every new session so leftovers
    self-heal instead of accumulating; failures here are logged and
    swallowed rather than blocking the new session.

    This does not restore host-global ``ip_forward`` to its pre-session
    value — that value is only ever recorded in the dead process's own
    memory, not on disk, so a killed session's original setting cannot be
    recovered here. Leaving ``ip_forward`` enabled is not itself a hole:
    once the orphaned FORWARD/NAT rules are removed, forwarding follows the
    host's own default policy like any other traffic.
    """
    if shutil.which("iptables") is None:
        return
    for session_id in _stale_session_ids():
        _sweep_session(session_id)


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
    _forward_was: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        suffix = os.getpid() % 10_000
        session_id = f"mc-eg-{os.getpid()}-{suffix}"
        self.ns_name = session_id
        self._comment = session_id
        # A dedicated iptables chain (finding 1). ``session_id`` is at most
        # ~18 chars (pid up to 7 digits, suffix 4), well under the 28-char
        # iptables chain-name limit, and doubles as the comment tag so a
        # sweep can find both from one string.
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
        """Create the netns and apply the FORWARD allowlist."""
        try:
            if not filtered_egress_available():
                raise FilteredEgressSetupError(probe_filtered_egress().reason)
            try:
                sweep_orphaned_filtered_egress()
            except Exception as exc:  # best-effort self-heal — must never block a new session
                logger.warning("filtered-egress startup sweep failed (non-fatal): {}", exc)
            ips = resolve_allowlist_ips(self.allowed_hosts)
            if not ips:
                raise FilteredEgressSetupError("allowlist resolved to no addresses")
            self._select_subnet()
            self._cmd(["ip", "netns", "add", self.ns_name])
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
            self._cmd(["ip", "link", "set", self._peer_veth, "netns", self.ns_name])
            self._cmd(["ip", "addr", "add", f"{self._host_ip}/30", "dev", self._host_veth])
            self._cmd(["ip", "link", "set", self._host_veth, "up"])
            self._ns(["ip", "addr", "add", f"{self._peer_ip}/30", "dev", self._peer_veth])
            self._ns(["ip", "link", "set", self._peer_veth, "up"])
            self._ns(["ip", "link", "set", "lo", "up"])
            self._disable_ipv6()
            self._ns(["ip", "route", "add", "default", "via", self._host_ip])
            self._write_ns_resolv()
            self._enable_forward()
            self._apply_filter(ips)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Tear down iptables, veth, and the named netns."""
        self._flush_iptables()
        for argv in (
            ["ip", "link", "delete", self._host_veth],
            ["ip", "netns", "delete", self.ns_name],
        ):
            with contextlib.suppress(OSError):
                subprocess.run(argv, check=False, capture_output=True, timeout=5)
        with contextlib.suppress(OSError):
            shutil.rmtree(f"/etc/netns/{self.ns_name}", ignore_errors=True)
        if self._forward_was is not None and self._forward_was != "1":
            with contextlib.suppress(OSError):
                Path("/proc/sys/net/ipv4/ip_forward").write_text(
                    f"{self._forward_was}\n", encoding="utf-8"
                )
        self._forward_was = None

    def __enter__(self) -> FilteredNetnsSession:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def wrap_argv(self, argv: list[str]) -> list[str]:
        """Prefix argv with ``ip netns exec`` and drop ``--net``."""
        return wrap_argv_for_filtered_netns(argv, self.ns_name)

    def _cmd(self, argv: list[str]) -> None:
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
        used: set[int] = set()
        try:
            result = subprocess.run(
                ["ip", "-4", "addr", "show"], capture_output=True, text=True, timeout=5, check=False
            )
        except OSError:
            return used
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line.startswith("inet 10.255."):
                continue
            addr = line.split()[1].split("/")[0]
            parts = addr.split(".")
            if len(parts) == 4:
                with contextlib.suppress(ValueError):
                    used.add(int(parts[2]))
        return used

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
        path = Path("/proc/sys/net/ipv4/ip_forward")
        try:
            self._forward_was = path.read_text(encoding="utf-8").strip()
            if self._forward_was != "1":
                path.write_text("1\n", encoding="utf-8")
        except OSError as exc:
            raise FilteredEgressSetupError(f"cannot enable ip_forward: {exc}") from exc

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
        self._cmd(
            ["iptables", "-I", "FORWARD", "1", "-o", self._host_veth, *comment, "-j", self._chain]
        )
        self._cmd(
            ["iptables", "-I", "FORWARD", "1", "-i", self._host_veth, *comment, "-j", self._chain]
        )

        self._ipt_chain(
            ["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", *comment, "-j", "ACCEPT"]
        )
        for ip in self.dns_resolvers:
            self._ipt_chain(["-p", "udp", "-d", ip, "--dport", "53", *comment, "-j", "ACCEPT"])
            self._ipt_chain(["-p", "tcp", "-d", ip, "--dport", "53", *comment, "-j", "ACCEPT"])
        for ip in sorted(dest_ips):
            self._ipt_chain(["-d", ip, *comment, "-j", "ACCEPT"])
        self._ipt_chain([*comment, "-j", "DROP"])

        self._cmd(
            [
                "iptables",
                "-t",
                "nat",
                "-A",
                "POSTROUTING",
                "-s",
                self._cidr,
                *comment,
                "-j",
                "MASQUERADE",
            ]
        )

    def _flush_iptables(self) -> None:
        if not self._chain_created:
            return
        comment = ["-m", "comment", "--comment", self._comment]
        for direction in ("-o", "-i"):
            argv = [
                "iptables",
                "-D",
                "FORWARD",
                direction,
                self._host_veth,
                *comment,
                "-j",
                self._chain,
            ]
            with contextlib.suppress(OSError):
                subprocess.run(argv, check=False, capture_output=True, timeout=5)
        with contextlib.suppress(OSError):
            subprocess.run(
                ["iptables", "-F", self._chain], check=False, capture_output=True, timeout=5
            )
        with contextlib.suppress(OSError):
            subprocess.run(
                ["iptables", "-X", self._chain], check=False, capture_output=True, timeout=5
            )
        with contextlib.suppress(OSError):
            subprocess.run(
                [
                    "iptables",
                    "-t",
                    "nat",
                    "-D",
                    "POSTROUTING",
                    "-s",
                    self._cidr,
                    *comment,
                    "-j",
                    "MASQUERADE",
                ],
                check=False,
                capture_output=True,
                timeout=5,
            )
        self._chain_created = False


__all__ = [
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
    "sweep_orphaned_filtered_egress",
    "wrap_argv_for_filtered_netns",
]
