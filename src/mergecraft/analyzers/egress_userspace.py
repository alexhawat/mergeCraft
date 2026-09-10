"""Userspace filtered egress for runtimes without host CAP_NET_ADMIN (#538).

The GitHub Action image typically cannot create a host veth or mutate
``FORWARD``. This backend keeps the analyzer in a user+net namespace whose
only outbound path is a parent-side TCP relay. Go scanners cannot bypass it
by ignoring ``HTTP_PROXY`` — they have no other route.

The kernel netns + FORWARD path in ``egress.py`` stays behind
``MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME`` because it changes shared
host firewall state. This backend does not.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.analyzers.egress import (
    FilteredEgressProbe,
    FilteredEgressSetupError,
    allowlist_hosts,
    host_is_allowlisted,
    resolve_allowlist_host_ips,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_RELAY_OK = b"OK\n"
_RELAY_NO = b"NO\n"


def _can_unshare_user_net() -> bool:
    if shutil.which("unshare") is None:
        return False
    try:
        completed = subprocess.run(
            ["unshare", "--user", "--map-root-user", "--net", "true"],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def probe_userspace_egress() -> FilteredEgressProbe:
    """Probe user-namespace net + iptables without touching host FORWARD."""
    net = _can_unshare_user_net()
    iptables = shutil.which("iptables") is not None
    if net and iptables:
        return FilteredEgressProbe(
            network_namespace=True,
            veth=False,
            ip_netns=False,
            iptables=True,
            available=True,
            reason="",
            backend="userspace",
            user_namespace=True,
        )
    missing: list[str] = []
    if not net:
        missing.append("unshare --user --map-root-user --net")
    if not iptables:
        missing.append("iptables")
    return FilteredEgressProbe(
        network_namespace=net,
        veth=False,
        ip_netns=False,
        iptables=iptables,
        available=False,
        reason="userspace filtered egress unavailable: " + ", ".join(missing),
        backend="none",
        user_namespace=net,
    )


def userspace_egress_available() -> bool:
    """True when the Action-image backend can enforce an allowlist."""
    return probe_userspace_egress().available


def wrap_argv_for_userspace_relay(
    argv: list[str],
    *,
    socket_path: str,
    allowed_hosts: Iterable[str],
    allowed_ips: Iterable[str],
    host_ips: Mapping[str, Iterable[str]] | None = None,
) -> list[str]:
    """Prefix argv with the userspace bridge (parent stays on the container net)."""
    hosts = ",".join(sorted(allowlist_hosts(allowed_hosts)))
    ips = ",".join(sorted(allowed_ips))
    mapping = host_ips or {}
    encoded = json.dumps(
        {host: sorted(set(values)) for host, values in mapping.items()},
        separators=(",", ":"),
    )
    return [
        sys.executable,
        "-m",
        "mergecraft.analyzers.egress_bridge",
        "--socket",
        socket_path,
        "--hosts",
        hosts,
        "--ips",
        ips,
        "--map",
        encoded,
        "--",
        *argv,
    ]


@dataclass(slots=True)
class UserspaceEgressSession:
    """Parent-side TCP relay plus child user+net namespace (#538)."""

    allowed_hosts: list[str]
    socket_path: str = ""
    _socket_dir: str = field(default="", init=False)
    _allowed_ips: frozenset[str] = field(default_factory=frozenset, init=False)
    _host_ips: dict[str, frozenset[str]] = field(default_factory=dict, init=False)
    _server: socket.socket | None = field(default=None, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _started: bool = field(default=False, init=False)

    def start(self) -> None:
        """Bind the Unix relay; fail closed when the userspace probe is false."""
        probe = probe_userspace_egress()
        if not probe.available:
            raise FilteredEgressSetupError(probe.reason)
        host_ips = resolve_allowlist_host_ips(self.allowed_hosts)
        ips = frozenset(ip for values in host_ips.values() for ip in values)
        if not ips:
            raise FilteredEgressSetupError("allowlist resolved to no addresses")
        self._host_ips = host_ips
        self._allowed_ips = ips
        socket_dir = Path(tempfile.mkdtemp(prefix=f"mc-eg-us-{os.getpid()}-"))
        os.chmod(socket_dir, 0o700)
        self._socket_dir = str(socket_dir)
        self.socket_path = str(socket_dir / "relay.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self.socket_path)
        server.listen(16)
        server.settimeout(0.5)
        self._server = server
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, name="mc-egress-relay", daemon=True)
        self._thread.start()
        self._started = True

    def close(self) -> None:
        """Stop the relay and remove the socket."""
        self._stop.set()
        server = self._server
        self._server = None
        if server is not None:
            with contextlib.closing(server):
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._socket_dir:
            shutil.rmtree(self._socket_dir, ignore_errors=True)
            self._socket_dir = ""
        self.socket_path = ""
        self._started = False

    def __enter__(self) -> UserspaceEgressSession:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def wrap_argv(self, argv: list[str]) -> list[str]:
        """Wrap analyzer argv so it can only leave via this session's relay."""
        if not self._started or not self.socket_path:
            raise FilteredEgressSetupError("userspace egress session is not started")
        return wrap_argv_for_userspace_relay(
            argv,
            socket_path=self.socket_path,
            allowed_hosts=self.allowed_hosts,
            allowed_ips=self._allowed_ips,
            host_ips=self._host_ips,
        )

    def destination_allowed(self, host: str, ip: str) -> bool:
        """Return True only when *ip* is an allowlisted literal bound to *host*.

        The child supplies both fields and the parent dials ``ip`` verbatim, so a
        hostname must never authorize an address on its own: an analyzer could
        otherwise send ``{"host": "<allowlisted>", "ip": "<anything>"}`` and have
        the parent open it. The relay listens on ``AF_UNIX`` in the shared
        filesystem, which the child netns can always reach — a TCP ``OUTPUT``
        DROP does not apply to it — so this check is the only enforcement point
        that matters (#538).
        """
        return relay_request_allowed(
            host=host,
            ip=ip,
            allowed_hosts=self.allowed_hosts,
            allowed_ips=self._allowed_ips,
            host_ips=self._host_ips,
        )

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stop.is_set():
            try:
                client, _unused = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            thread = threading.Thread(
                target=self._handle_client,
                args=(client,),
                name="mc-egress-relay-client",
                daemon=True,
            )
            thread.start()

    def _handle_client(self, client: socket.socket) -> None:
        remote: socket.socket | None = None
        try:
            client.settimeout(10)
            raw = _read_line(client)
            request = json.loads(raw)
            if not isinstance(request, dict):
                client.sendall(_RELAY_NO)
                return
            host = str(request.get("host") or "")
            ip = str(request.get("ip") or "")
            port = int(request.get("port") or 0)
            if port <= 0 or port > 65535 or not self.destination_allowed(host, ip):
                client.sendall(_RELAY_NO)
                return
            remote = socket.create_connection((ip, port), timeout=10)
            client.sendall(_RELAY_OK)
            _splice(client, remote)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.info("userspace egress relay rejected a stream: {}", exc)
            with contextlib.suppress(OSError):
                client.sendall(_RELAY_NO)
        finally:
            with contextlib.closing(client):
                pass
            if remote is not None:
                with contextlib.closing(remote):
                    pass


def _read_line(sock: socket.socket) -> str:
    chunks: list[bytes] = []
    while True:
        piece = sock.recv(1)
        if not piece:
            break
        if piece == b"\n":
            break
        chunks.append(piece)
        if sum(len(item) for item in chunks) > 4096:
            raise ValueError("relay request too long")
    return b"".join(chunks).decode("utf-8")


def _splice(left: socket.socket, right: socket.socket) -> None:
    done = threading.Event()

    def _copy(source: socket.socket, dest: socket.socket) -> None:
        try:
            while not done.is_set():
                data = source.recv(65536)
                if not data:
                    break
                dest.sendall(data)
        except OSError:
            pass
        finally:
            done.set()
            with contextlib.suppress(OSError):
                dest.shutdown(socket.SHUT_WR)

    first = threading.Thread(target=_copy, args=(left, right), daemon=True)
    second = threading.Thread(target=_copy, args=(right, left), daemon=True)
    first.start()
    second.start()
    first.join()
    second.join()


def relay_request_allowed(
    *,
    host: str,
    ip: str,
    allowed_hosts: Iterable[str],
    allowed_ips: Iterable[str],
    host_ips: Mapping[str, frozenset[str]] | None = None,
) -> bool:
    """Pure allowlist check used by the child bridge, the relay, and tests.

    IP-only by construction. ``host`` narrows the decision, it never widens it:
    an allowlisted hostname paired with a foreign address is rejected, because
    the caller dials the address and not the name.
    """
    try:
        parsed = ipaddress.ip_address(ip.strip())
    except ValueError:
        # Not a literal address — a name here would be resolved by the dialler,
        # after this check, which is precisely the gap being closed.
        return False

    def _same(candidate: str) -> bool:
        try:
            return ipaddress.ip_address(candidate.strip()) == parsed
        except ValueError:
            return False

    if not any(_same(entry) for entry in allowed_ips):
        return False
    if not host:
        return True
    # A host was named: it must be allowlisted *and* actually resolve to this
    # address, so one allowlisted name cannot vouch for another name's IP.
    if not host_is_allowlisted(host, allowlist_hosts(allowed_hosts)):
        return False
    if host_ips is None:
        # No map supplied: the address already had to be on the allowlist above,
        # so this stays IP-gated. Callers that have a map must pass it.
        return True
    bound = host_ips.get(host) or next(
        (ips for name, ips in host_ips.items() if name.lower() == host.lower()),
        None,
    )
    if bound is None:
        # A map was supplied and does not know this name — reject rather than
        # fall back, or an unmapped-but-allowlisted name would widen the check.
        return False
    return any(_same(entry) for entry in bound)


__all__ = [
    "UserspaceEgressSession",
    "probe_userspace_egress",
    "relay_request_allowed",
    "userspace_egress_available",
    "wrap_argv_for_userspace_relay",
]
