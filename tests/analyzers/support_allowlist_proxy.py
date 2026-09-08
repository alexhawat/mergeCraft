"""Test-only CONNECT proxy that encodes the egress hostname allowlist (#606).

``AllowlistConnectProxy`` never ran in production — the module docstring on
``mergecraft.analyzers.egress`` always said so — but it shipped in ``src/``
where it was reachable by anything that imported the package. Production
isolation is ``FilteredNetnsSession`` (kernel FORWARD filter, IP-based);
this loopback CONNECT proxy exists only so ``allowlist_hosts`` /
``host_is_allowlisted`` have an executable hostname-policy check in tests
without needing ``CAP_NET_ADMIN`` / ``CAP_SYS_ADMIN``.
"""

from __future__ import annotations

import contextlib
import socket
import threading
from typing import TYPE_CHECKING

from mergecraft.analyzers.egress import allowlist_hosts, host_is_allowlisted

if TYPE_CHECKING:
    from collections.abc import Iterable


class AllowlistConnectProxy:
    """Loopback CONNECT proxy that permits only allowlisted destinations.

    Enforcement is the proxy's CONNECT policy, not ``HTTP_PROXY`` in the
    analyzer environment. Production isolation uses ``FilteredNetnsSession``
    in ``mergecraft.analyzers.egress``; this class only exists so tests can
    exercise the hostname allowlist without root/CAP_NET_ADMIN.
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


__all__ = ["AllowlistConnectProxy"]
