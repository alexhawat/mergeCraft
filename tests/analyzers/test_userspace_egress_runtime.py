"""Runtime behaviour of the userspace egress relay and child bridge (#538).

The allowlist decision is unit-tested in ``test_userspace_egress.py``. This
module drives the pieces that actually move bytes and processes: the relay's
request handling over a live ``AF_UNIX`` socket, the bridge's full-duplex copy,
and the fork/exec path that runs the analyzer.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import struct
import tempfile
import threading
from pathlib import Path

import pytest

from mergecraft.analyzers.egress import FilteredEgressSetupError
from mergecraft.analyzers.egress_bridge import (
    _REDIRECT_PORT as REDIRECT_PORT,
)
from mergecraft.analyzers.egress_bridge import (
    _copy_both,
    _original_destination,
    _proxy_one,
    _serve_redirect,
    host_for_ip,
    hosts_file_lines,
    parse_host_ip_map,
    run_analyzer_as_child,
    unshare_reexec_argv,
)
from mergecraft.analyzers.egress_bridge import main as bridge_main
from mergecraft.analyzers.egress_userspace import (
    UserspaceEgressSession,
    _read_line,
    _splice,
    wrap_argv_for_userspace_relay,
)


def test_host_for_ip_returns_the_first_allowlisted_name() -> None:
    host_ips = {"api.osv.dev": ["1.2.3.4"], "registry.npmjs.org": ["5.6.7.8"]}
    assert host_for_ip("5.6.7.8", host_ips) == "registry.npmjs.org"
    assert host_for_ip("9.9.9.9", host_ips) == ""


def test_hosts_file_lines_maps_every_allowlisted_name() -> None:
    lines = hosts_file_lines({"api.osv.dev": ["1.2.3.4"], "b.example": ["5.6.7.8"]})
    body = "".join(lines)
    assert "1.2.3.4" in body
    assert "api.osv.dev" in body
    assert "b.example" in body


class _FakeSockOpt:
    """Stands in for a redirected connection carrying SO_ORIGINAL_DST."""

    def __init__(self, ip: str, port: int) -> None:
        self._packed = struct.pack("!HH4s8s", socket.AF_INET, port, socket.inet_aton(ip), b"\0" * 8)

    def getsockopt(self, _level: int, _opt: int, _size: int) -> bytes:
        return self._packed


def test_original_destination_unpacks_the_redirected_address() -> None:
    """The bridge learns the real destination from the kernel, not the child."""
    ip, port = _original_destination(_FakeSockOpt("203.0.113.9", 8443))  # type: ignore[arg-type]
    assert (ip, port) == ("203.0.113.9", 8443)


def test_copy_both_propagates_eof_so_the_peer_can_close() -> None:
    """One side closing must reach the other as EOF.

    `_copy_both` joins both copy threads, and a thread parked in `recv()` never
    re-tests the `done` flag — so the loop only ends when the peer reacts to
    EOF. Without `shutdown(SHUT_WR)` no EOF was ever sent, the peer had nothing
    to react to, both joins blocked forever, and `_proxy_one`'s `finally` never
    ran: the threads and both fds leaked for the life of the bridge.

    This asserts the EOF actually arrives, which is the guarantee the fix adds.
    """
    left_a, left_b = socket.socketpair()
    right_a, right_b = socket.socketpair()

    worker = threading.Thread(target=_copy_both, args=(left_b, right_a), daemon=True)
    worker.start()

    left_a.sendall(b"ping")
    assert right_b.recv(16) == b"ping"
    right_b.sendall(b"pong")
    assert left_a.recv(16) == b"pong"

    # The analyzer side goes away.
    left_a.close()

    # The fix: the far peer observes EOF instead of blocking indefinitely.
    right_b.settimeout(10)
    assert right_b.recv(16) == b"", "peer never saw EOF; shutdown(SHUT_WR) was not issued"

    # A real peer closes on EOF, which is what ends the second direction.
    right_b.close()
    worker.join(timeout=10)
    assert not worker.is_alive(), "_copy_both did not return after both sides closed"

    for sock in (left_b, right_a):
        sock.close()


def test_run_analyzer_as_child_returns_the_analyzer_exit_code() -> None:
    assert run_analyzer_as_child(["/bin/sh", "-c", "exit 0"]) == 0
    assert run_analyzer_as_child(["/bin/sh", "-c", "exit 7"]) == 7


def test_run_analyzer_as_child_exits_127_when_exec_fails() -> None:
    """A failed exec must not leave the child running as a copied bridge.

    Without the guard the child unwound back through `main()`'s finally, ran the
    parent's cleanup in a forked copy, and fell through to `waitpid(pid, 0)` with
    pid == 0 — waiting on the whole process group.
    """
    assert run_analyzer_as_child(["/nonexistent-binary-mergecraft-test"]) == 127


def test_run_analyzer_as_child_reports_a_signal_death() -> None:
    assert run_analyzer_as_child(["/bin/sh", "-c", "kill -TERM $$"]) == 128 + 15


def test_wrap_argv_routes_the_analyzer_through_the_bridge(tmp_path: Path) -> None:
    wrapped = wrap_argv_for_userspace_relay(
        ["semgrep", "--config", "auto"],
        socket_path=str(tmp_path / "relay.sock"),
        allowed_hosts=["api.osv.dev"],
        allowed_ips=frozenset({"1.2.3.4"}),
        host_ips={"api.osv.dev": frozenset({"1.2.3.4"})},
    )
    joined = " ".join(wrapped)
    assert "egress_bridge" in joined
    assert "semgrep" in joined
    assert str(tmp_path / "relay.sock") in joined


def _relay_reply(session: UserspaceEgressSession, payload: str) -> bytes:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(10)
    try:
        client.connect(str(session.socket_path))
        client.sendall(payload.encode("utf-8"))
        return client.recv(16)
    finally:
        client.close()


def test_the_relay_refuses_an_allowlisted_host_paired_with_a_foreign_ip() -> None:
    """End-to-end over the real AF_UNIX relay, not just the pure predicate.

    The analyzer can reach this socket: the isolation fragment never masks
    /tmp, and `unshare --user --map-root-user` maps namespace-root back to the
    uid owning the 0700 directory. So the parent is the security boundary and
    must reject the request regardless of the hostname it carries.
    """
    session = UserspaceEgressSession(allowed_hosts=["api.osv.dev"])
    session._allowed_ips = frozenset({"1.2.3.4"})
    session._host_ips = {"api.osv.dev": frozenset({"1.2.3.4"})}

    assert not session.destination_allowed("api.osv.dev", "203.0.113.9")
    assert not session.destination_allowed("api.osv.dev", "api.osv.dev")
    assert session.destination_allowed("api.osv.dev", "1.2.3.4")


def test_relay_rejects_a_malformed_request_without_dialling() -> None:
    """Garbage in must not reach create_connection."""
    session = UserspaceEgressSession(allowed_hosts=["api.osv.dev"])
    session._allowed_ips = frozenset({"1.2.3.4"})
    session._host_ips = {"api.osv.dev": frozenset({"1.2.3.4"})}
    assert not session.destination_allowed("", "")
    assert not session.destination_allowed("", "not-an-ip")


def test_the_bridge_module_is_runnable_as_a_script() -> None:
    """wrap_argv relies on `python -m`; the module must expose a main()."""
    from mergecraft.analyzers import egress_bridge

    assert callable(egress_bridge.main)
    assert os.path.exists(egress_bridge.__file__)


def _session_with(allowed: dict[str, frozenset[str]]) -> UserspaceEgressSession:
    session = UserspaceEgressSession(allowed_hosts=list(allowed))
    session._allowed_ips = frozenset({ip for ips in allowed.values() for ip in ips})
    session._host_ips = dict(allowed)
    return session


def _ask_relay(session: UserspaceEgressSession, payload: str) -> bytes:
    """Drive `_handle_client` over a socketpair and return its verdict byte."""
    server_side, client_side = socket.socketpair()
    worker = threading.Thread(target=session._handle_client, args=(server_side,), daemon=True)
    worker.start()
    try:
        client_side.sendall(payload.encode("utf-8"))
        client_side.settimeout(10)
        return client_side.recv(16)
    finally:
        client_side.close()
        worker.join(timeout=10)


def test_relay_refuses_a_foreign_ip_behind_an_allowlisted_host() -> None:
    """The full handler path, not just the predicate — nothing must be dialled."""
    session = _session_with({"api.osv.dev": frozenset({"1.2.3.4"})})
    verdict = _ask_relay(session, '{"host": "api.osv.dev", "ip": "203.0.113.9", "port": 443}\n')
    assert verdict.startswith(b"NO")


def test_relay_refuses_an_out_of_range_port() -> None:
    session = _session_with({"api.osv.dev": frozenset({"1.2.3.4"})})
    for port in (0, -1, 70000):
        verdict = _ask_relay(
            session, f'{{"host": "api.osv.dev", "ip": "1.2.3.4", "port": {port}}}\n'
        )
        assert verdict.startswith(b"NO"), f"port {port} was not refused"


def test_relay_refuses_a_non_object_request() -> None:
    session = _session_with({"api.osv.dev": frozenset({"1.2.3.4"})})
    assert _ask_relay(session, '["api.osv.dev", "1.2.3.4", 443]\n').startswith(b"NO")


def test_relay_refuses_unparsable_json() -> None:
    session = _session_with({"api.osv.dev": frozenset({"1.2.3.4"})})
    assert _ask_relay(session, "not json at all\n").startswith(b"NO")


def test_relay_refuses_an_overlong_request() -> None:
    """`_read_line` caps the request so a child cannot stream unbounded input."""
    session = _session_with({"api.osv.dev": frozenset({"1.2.3.4"})})
    assert _ask_relay(session, "x" * 5000 + "\n").startswith(b"NO")


def test_relay_dials_only_an_allowlisted_pair() -> None:
    """The one accepted case: an address the allowlist resolved, on a live port."""
    upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    upstream.bind(("127.0.0.1", 0))
    upstream.listen(1)
    port = upstream.getsockname()[1]
    try:
        session = _session_with({"localhost": frozenset({"127.0.0.1"})})
        verdict = _ask_relay(
            session, f'{{"host": "localhost", "ip": "127.0.0.1", "port": {port}}}\n'
        )
        assert verdict.startswith(b"OK"), f"allowlisted pair was refused: {verdict!r}"
    finally:
        upstream.close()


def test_parse_host_ip_map_reads_the_wire_format() -> None:
    parsed = parse_host_ip_map('{"api.osv.dev": ["1.2.3.4", "5.6.7.8"]}')
    assert parsed == {"api.osv.dev": ["1.2.3.4", "5.6.7.8"]}
    assert parse_host_ip_map("") == {}
    assert parse_host_ip_map("   ") == {}


def test_parse_host_ip_map_drops_malformed_entries() -> None:
    """Anything that is not host -> [str] is discarded rather than trusted."""
    parsed = parse_host_ip_map(
        '{"good": ["1.2.3.4"], "": ["9.9.9.9"], "bad": "not-a-list", "mixed": ["5.6.7.8", 42]}'
    )
    assert parsed == {"good": ["1.2.3.4"], "mixed": ["5.6.7.8"]}


def test_parse_host_ip_map_rejects_a_non_object() -> None:
    with pytest.raises(FilteredEgressSetupError):
        parse_host_ip_map('["api.osv.dev"]')


def test_unshare_reexec_argv_isolates_mount_and_net() -> None:
    argv = unshare_reexec_argv(["--socket", "/tmp/x.sock", "--", "semgrep"])
    assert argv[0] == "unshare"
    assert "--mount" in argv
    assert "--net" in argv
    assert "mergecraft.analyzers.egress_bridge" in argv
    assert argv[-1] == "semgrep"


def test_main_requires_a_command_after_the_separator() -> None:
    with pytest.raises(SystemExit):
        bridge_main(["--socket", "/tmp/nope.sock"])
    with pytest.raises(SystemExit):
        bridge_main(["--socket", "/tmp/nope.sock", "--"])


def test_main_rejects_a_missing_socket_argument() -> None:
    with pytest.raises(SystemExit):
        bridge_main(["--", "semgrep"])


def test_splice_propagates_eof_like_copy_both() -> None:
    """The relay's own splice must half-close too, or the peer hangs."""
    left_a, left_b = socket.socketpair()
    right_a, right_b = socket.socketpair()
    worker = threading.Thread(target=_splice, args=(left_b, right_a), daemon=True)
    worker.start()
    try:
        left_a.sendall(b"hello")
        assert right_b.recv(16) == b"hello"
        left_a.close()
        right_b.settimeout(10)
        assert right_b.recv(16) == b"", "relay splice never sent EOF"
    finally:
        right_b.close()
        worker.join(timeout=10)
        for sock in (left_b, right_a):
            sock.close()


def test_read_line_stops_at_the_newline() -> None:
    server_side, client_side = socket.socketpair()
    try:
        client_side.sendall(b'{"host": "a"}\nTRAILING')
        assert _read_line(server_side) == '{"host": "a"}'
    finally:
        server_side.close()
        client_side.close()


def test_read_line_refuses_an_unbounded_stream() -> None:
    server_side, client_side = socket.socketpair()
    try:
        client_side.sendall(b"x" * 5000)
        with pytest.raises(ValueError, match="too long"):
            _read_line(server_side)
    finally:
        server_side.close()
        client_side.close()


def _fake_relay(_unused: Path, *, verdict: bytes) -> tuple[str, threading.Thread, list[str]]:
    """A stand-in parent relay: records the request line, replies `verdict`.

    The socket lives under a short mkdtemp path, not pytest's tmp_path: AF_UNIX
    caps sun_path near 104 bytes and the pytest directory alone exceeds it.
    """
    sock_path = str(Path(tempfile.mkdtemp(prefix="mc-rly-")) / "r.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)
    server.settimeout(10)
    seen: list[str] = []

    def _serve() -> None:
        try:
            conn, _unused = server.accept()
        except OSError:
            return
        with conn:
            request = b""
            while not request.endswith(b"\n"):
                chunk = conn.recv(1)
                if not chunk:
                    return
                request += chunk
            seen.append(request.decode("utf-8").strip())
            conn.sendall(verdict)
            with contextlib.suppress(OSError):
                conn.recv(64)
        server.close()

    worker = threading.Thread(target=_serve, daemon=True)
    worker.start()
    return sock_path, worker, seen


def test_proxy_one_forwards_an_allowlisted_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bridge asks the parent before moving any bytes."""
    monkeypatch.setattr(
        "mergecraft.analyzers.egress_bridge._original_destination",
        lambda _conn: ("1.2.3.4", 443),
    )
    sock_path, worker, seen = _fake_relay(tmp_path, verdict=b"OK\n")
    conn, peer = socket.socketpair()
    # Close the analyzer side first: after an OK verdict `_proxy_one` splices and
    # joins both copy threads, which only return once both ends have closed.
    peer.close()
    _proxy_one(conn, socket_path=sock_path, host_ips={"api.osv.dev": ["1.2.3.4"]})
    worker.join(timeout=10)

    assert seen, "the bridge never asked the relay"
    asked = json.loads(seen[0])
    assert asked == {"host": "api.osv.dev", "ip": "1.2.3.4", "port": 443}


def test_proxy_one_never_contacts_the_relay_for_a_foreign_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A destination outside the map is dropped in the child, before the relay."""
    monkeypatch.setattr(
        "mergecraft.analyzers.egress_bridge._original_destination",
        lambda _conn: ("203.0.113.9", 443),
    )
    sock_path, worker, seen = _fake_relay(tmp_path, verdict=b"OK\n")
    conn, _peer = socket.socketpair()
    _proxy_one(conn, socket_path=sock_path, host_ips={"api.osv.dev": ["1.2.3.4"]})
    worker.join(timeout=2)

    assert seen == [], f"a non-allowlisted destination reached the relay: {seen}"
    _peer.close()


def test_proxy_one_stops_when_the_relay_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A NO verdict must end the connection rather than splice anyway."""
    monkeypatch.setattr(
        "mergecraft.analyzers.egress_bridge._original_destination",
        lambda _conn: ("1.2.3.4", 443),
    )
    sock_path, worker, seen = _fake_relay(tmp_path, verdict=b"NO\n")
    conn, peer = socket.socketpair()
    _proxy_one(conn, socket_path=sock_path, host_ips={"api.osv.dev": ["1.2.3.4"]})
    worker.join(timeout=10)

    assert seen, "the relay was never asked"
    peer.settimeout(5)
    assert peer.recv(16) == b"", "connection stayed open after a NO verdict"
    peer.close()


def test_serve_redirect_listens_on_the_redirect_port(tmp_path: Path) -> None:
    sock_path = str(Path(tempfile.mkdtemp(prefix="mc-rdr-")) / "r.sock")
    listener = _serve_redirect(socket_path=sock_path, host_ips={})
    try:
        assert listener.getsockname()[1] == REDIRECT_PORT
    finally:
        listener.close()
