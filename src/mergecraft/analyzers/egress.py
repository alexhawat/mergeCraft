"""Filtered analyzer egress — netns + host FORWARD allowlist, never HTTP_PROXY.

Chosen enforcement (plan 15 W3 Step 3): a dedicated netns whose only route is
a veth, with host ``FORWARD`` limited to allowlisted destinations. A CONNECT
proxy encodes the same hostname policy for tests. DNS-only filtering was
rejected as bypassable by literal IPs. Classic seccomp-BPF cannot
dereference ``sockaddr``. ``HTTP_PROXY`` as the wall is rejected: Go
analyzers (``osv-scanner``, ``trivy``) ignore it, so the kernel filter is
the wall, not a proxy env var.

The Action image typically lacks ``CAP_NET_ADMIN`` / ``CAP_SYS_ADMIN``, so
``filtered_egress_available()`` is False there and the untrusted path stays
fail-closed (named skip). Capable Linux runners (``ip netns`` plus veth plus
iptables) run isolated-to-allowlist instead.
"""

from __future__ import annotations

import contextlib
import functools
import os
import shutil
import socket
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Iterable

_VETH_PROBE_PREFIX = "mcfg"
_DNS_RESOLVERS: tuple[str, ...] = ("1.1.1.1",)


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


class AllowlistConnectProxy:
    """Loopback CONNECT proxy that permits only allowlisted destinations.

    Enforcement is the proxy's CONNECT policy, not ``HTTP_PROXY`` in the
    analyzer environment. Production isolation uses ``FilteredNetnsSession``;
    this class is the hostname allowlist the tests prove.
    """

    def __init__(self, allowed_hosts: Iterable[str]) -> None:
        self._allowed = allowlist_hosts(allowed_hosts)
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.host = "127.0.0.1"
        self.port = 0

    def start(self) -> None:
        """Bind loopback and serve CONNECT in a daemon thread."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, 0))
        listener.listen(64)
        listener.settimeout(0.2)
        self._sock = listener
        self.port = int(listener.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, name="mc-egress-proxy", daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Stop accepting new connections."""
        self._stop.set()
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> AllowlistConnectProxy:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _serve(self) -> None:
        listener = self._sock
        if listener is None:
            return
        while not self._stop.is_set():
            try:
                conn, _addr = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(10.0)
            header = _read_http_head(conn)
            dest_host, dest_port = _parse_connect_target(header)
            if dest_host is None or not host_is_allowlisted(dest_host, self._allowed):
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                return
            try:
                upstream = socket.create_connection((dest_host, dest_port), timeout=10.0)
            except OSError:
                conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                return
            conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            _splice(conn, upstream)
        except OSError:
            return
        finally:
            conn.close()


def _read_http_head(conn: socket.socket) -> bytes:
    buf = bytearray()
    while b"\r\n\r\n" not in buf and len(buf) < 8192:
        chunk = conn.recv(1024)
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


def _parse_connect_target(header: bytes) -> tuple[str | None, int]:
    first = header.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    parts = first.split()
    if len(parts) < 2 or parts[0].upper() != "CONNECT":
        return None, 0
    hostport = parts[1]
    if hostport.startswith("[") and "]" in hostport:
        host, _, port_s = hostport[1:].partition("]")
        port_s = port_s.lstrip(":") or "443"
    elif ":" in hostport:
        host, _, port_s = hostport.rpartition(":")
    else:
        host, port_s = hostport, "443"
    try:
        port = int(port_s)
    except ValueError:
        return None, 0
    return host, port


def _copy_socket(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        return
    finally:
        with contextlib.suppress(OSError):
            dst.shutdown(socket.SHUT_WR)


def _splice(left: socket.socket, right: socket.socket) -> None:
    t1 = threading.Thread(target=_copy_socket, args=(left, right), daemon=True)
    t2 = threading.Thread(target=_copy_socket, args=(right, left), daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=30.0)
    t2.join(timeout=30.0)
    left.close()
    right.close()


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


@dataclass(slots=True)
class FilteredNetnsSession:
    """Host-side veth + named netns + iptables FORWARD allowlist.

    Enforcement is the kernel filter, not ``HTTP_PROXY``. Setup failure must
    skip the analyzer; it must never fall back to host networking.
    """

    allowed_hosts: list[str]
    ns_name: str = field(init=False)
    _host_veth: str = field(init=False)
    _peer_veth: str = field(init=False)
    _host_ip: str = field(init=False)
    _peer_ip: str = field(init=False)
    _cidr: str = field(init=False)
    _comment: str = field(init=False)
    _iptables_specs: list[list[str]] = field(init=False)
    _forward_was: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        suffix = os.getpid() % 10_000
        self.ns_name = f"mc-eg-{os.getpid()}-{suffix}"
        self._host_veth = f"mcfh{suffix}"
        self._peer_veth = f"mcfp{suffix}"
        octet = (os.getpid() % 250) + 1
        self._host_ip = f"10.255.{octet}.1"
        self._peer_ip = f"10.255.{octet}.2"
        self._cidr = f"10.255.{octet}.0/30"
        self._comment = f"mc-eg-{os.getpid()}-{suffix}"
        self._iptables_specs = []

    def start(self) -> None:
        """Create the netns and apply the FORWARD allowlist."""
        try:
            if not filtered_egress_available():
                raise FilteredEgressSetupError(probe_filtered_egress().reason)
            ips = resolve_allowlist_ips(self.allowed_hosts)
            if not ips:
                raise FilteredEgressSetupError("allowlist resolved to no addresses")
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

    def _write_ns_resolv(self) -> None:
        path = Path("/etc/netns") / self.ns_name
        try:
            path.mkdir(parents=True, exist_ok=True)
            (path / "resolv.conf").write_text("nameserver 1.1.1.1\n", encoding="utf-8")
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

    def _ipt(self, spec: list[str]) -> None:
        self._cmd(["iptables", *spec])
        self._iptables_specs.append(spec)

    def _apply_filter(self, dest_ips: frozenset[str]) -> None:
        comment = ["-m", "comment", "--comment", self._comment]
        self._ipt(
            [
                "-A",
                "FORWARD",
                "-i",
                self._host_veth,
                "-m",
                "conntrack",
                "--ctstate",
                "ESTABLISHED,RELATED",
                *comment,
                "-j",
                "ACCEPT",
            ]
        )
        self._ipt(
            [
                "-A",
                "FORWARD",
                "-o",
                self._host_veth,
                "-m",
                "conntrack",
                "--ctstate",
                "ESTABLISHED,RELATED",
                *comment,
                "-j",
                "ACCEPT",
            ]
        )
        for ip in _DNS_RESOLVERS:
            self._ipt(
                [
                    "-A",
                    "FORWARD",
                    "-i",
                    self._host_veth,
                    "-p",
                    "udp",
                    "-d",
                    ip,
                    "--dport",
                    "53",
                    *comment,
                    "-j",
                    "ACCEPT",
                ]
            )
            self._ipt(
                [
                    "-A",
                    "FORWARD",
                    "-i",
                    self._host_veth,
                    "-p",
                    "tcp",
                    "-d",
                    ip,
                    "--dport",
                    "53",
                    *comment,
                    "-j",
                    "ACCEPT",
                ]
            )
        for ip in sorted(dest_ips):
            self._ipt(
                [
                    "-A",
                    "FORWARD",
                    "-i",
                    self._host_veth,
                    "-d",
                    ip,
                    *comment,
                    "-j",
                    "ACCEPT",
                ]
            )
        self._ipt(["-A", "FORWARD", "-i", self._host_veth, *comment, "-j", "DROP"])
        self._ipt(
            ["-t", "nat", "-A", "POSTROUTING", "-s", self._cidr, *comment, "-j", "MASQUERADE"]
        )

    def _flush_iptables(self) -> None:
        for spec in reversed(self._iptables_specs):
            deleted: list[str] = []
            replaced = False
            for token in spec:
                if not replaced and token in {"-I", "-A"}:
                    deleted.append("-D")
                    replaced = True
                else:
                    deleted.append(token)
            with contextlib.suppress(OSError):
                subprocess.run(
                    ["iptables", *deleted],
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
        self._iptables_specs.clear()


__all__ = [
    "AllowlistConnectProxy",
    "FilteredEgressProbe",
    "FilteredEgressSetupError",
    "FilteredNetnsSession",
    "allowlist_hosts",
    "filtered_egress_available",
    "host_is_allowlisted",
    "probe_filtered_egress",
    "reset_filtered_egress_cache",
    "resolve_allowlist_ips",
    "wrap_argv_for_filtered_netns",
]
