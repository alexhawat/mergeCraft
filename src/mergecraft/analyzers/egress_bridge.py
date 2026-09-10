"""Child-side userspace egress bridge — isolated netns + parent Unix relay (#538).

Invoked as ``python -m mergecraft.analyzers.egress_bridge``. The parent process
stays on the container network and makes allowlisted TCP connections. This
process enters a user+net namespace, redirects outbound TCP to a local
accept loop, and forwards original destinations over the Unix socket.

The analyzer is forked as a child so the redirect listener stays alive.
``os.execvp`` of the analyzer would destroy the listener threads and close
the non-inheritable listen socket (PEP 446).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from mergecraft.analyzers.egress import FilteredEgressSetupError
from mergecraft.analyzers.egress_userspace import relay_request_allowed

_SO_ORIGINAL_DST = 80
_REDIRECT_PORT = 17999


def unshare_reexec_argv(extra_args: list[str]) -> list[str]:
    """Argv that re-enters this module with ``-m`` after ``unshare``."""
    return [
        "unshare",
        "--user",
        "--map-root-user",
        "--mount",
        "--net",
        sys.executable,
        "-m",
        "mergecraft.analyzers.egress_bridge",
        *extra_args,
    ]


def _unshare_into_netns() -> None:
    if os.environ.get("MERGECRAFT_EGRESS_BRIDGE_IN_NS") == "1":
        return
    env = dict(os.environ)
    env["MERGECRAFT_EGRESS_BRIDGE_IN_NS"] = "1"
    os.execvpe("unshare", unshare_reexec_argv(sys.argv[1:]), env)


def _setup_loopback_and_filter() -> None:
    commands = [
        ["ip", "link", "set", "lo", "up"],
        ["iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "-d", "127.0.0.1", "-j", "RETURN"],
        [
            "iptables",
            "-t",
            "nat",
            "-A",
            "OUTPUT",
            "-p",
            "tcp",
            "-j",
            "REDIRECT",
            "--to-ports",
            str(_REDIRECT_PORT),
        ],
        ["iptables", "-A", "OUTPUT", "-p", "tcp", "-d", "127.0.0.1", "-j", "ACCEPT"],
        ["iptables", "-A", "OUTPUT", "-j", "DROP"],
    ]
    for argv in commands:
        completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=10)
        if completed.returncode != 0:
            err = (completed.stderr or completed.stdout or "").strip()
            raise FilteredEgressSetupError(f"{' '.join(argv)}: {err}")
    for scope in ("all", "default", "lo"):
        subprocess.run(
            ["sysctl", "-w", f"net.ipv6.conf.{scope}.disable_ipv6=1"],
            check=False,
            capture_output=True,
            timeout=5,
        )


def parse_host_ip_map(raw: str) -> dict[str, list[str]]:
    """Parse ``--map`` JSON ``{host: [ip, ...]}``."""
    if not raw.strip():
        return {}
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise FilteredEgressSetupError("egress --map must be a JSON object")
    mapping: dict[str, list[str]] = {}
    for host, ips in loaded.items():
        if not isinstance(host, str) or not host:
            continue
        if not isinstance(ips, list):
            continue
        mapping[host] = [str(ip) for ip in ips if isinstance(ip, str) and ip]
    return mapping


def hosts_file_lines(host_ips: dict[str, list[str]]) -> list[str]:
    """``/etc/hosts`` lines: each hostname maps only to its own resolved IPs."""
    lines = ["127.0.0.1 localhost\n"]
    for host, ips in sorted(host_ips.items()):
        if not host:
            continue
        for ip in ips:
            if ip:
                lines.append(f"{ip} {host}\n")
    return lines


def host_for_ip(ip: str, host_ips: dict[str, list[str]]) -> str:
    """Return the first allowlisted hostname that resolved to *ip*."""
    for host, ips in host_ips.items():
        if ip in ips:
            return host
    return ""


def _write_hosts(host_ips: dict[str, list[str]]) -> None:
    hosts_path = Path(tempfile.mkdtemp(prefix="mc-eg-hosts-")) / "hosts"
    hosts_path.write_text("".join(hosts_file_lines(host_ips)), encoding="utf-8")
    subprocess.run(
        ["mount", "--bind", str(hosts_path), "/etc/hosts"], check=False, capture_output=True
    )


def _original_destination(conn: socket.socket) -> tuple[str, int]:
    packed = conn.getsockopt(socket.SOL_IP, _SO_ORIGINAL_DST, 16)
    port = int.from_bytes(packed[2:4], "big")
    ip = socket.inet_ntoa(packed[4:8])
    return ip, port


def _proxy_one(
    conn: socket.socket,
    *,
    socket_path: str,
    host_ips: dict[str, list[str]],
) -> None:
    remote: socket.socket | None = None
    allowed_hosts = list(host_ips)
    allowed_ips = [ip for ips in host_ips.values() for ip in ips]
    try:
        ip, port = _original_destination(conn)
        host = host_for_ip(ip, host_ips)
        if not relay_request_allowed(
            host=host,
            ip=ip,
            allowed_hosts=allowed_hosts,
            allowed_ips=allowed_ips,
            host_ips={name: frozenset(ips) for name, ips in host_ips.items()},
        ):
            return
        remote = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        remote.settimeout(10)
        remote.connect(socket_path)
        payload = json.dumps({"host": host, "ip": ip, "port": port}) + "\n"
        remote.sendall(payload.encode("utf-8"))
        status = remote.recv(16)
        if not status.startswith(b"OK"):
            return
        _copy_both(conn, remote)
    except OSError:
        return
    finally:
        with contextlib.suppress(OSError):
            conn.close()
        if remote is not None:
            with contextlib.suppress(OSError):
                remote.close()


def _copy_both(left: socket.socket, right: socket.socket) -> None:
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
            # Half-close so the peer sees EOF. Without it the opposite thread
            # stays parked in recv() — it never re-tests `done` — so both joins
            # below block forever and `_proxy_one`'s finally never runs, leaking
            # the thread and both fds for the life of the bridge. An analyzer
            # opening many keep-alive connections would exhaust fds.
            with contextlib.suppress(OSError):
                dest.shutdown(socket.SHUT_WR)

    first = threading.Thread(target=_copy, args=(left, right), daemon=True)
    second = threading.Thread(target=_copy, args=(right, left), daemon=True)
    first.start()
    second.start()
    first.join()
    second.join()


def _serve_redirect(*, socket_path: str, host_ips: dict[str, list[str]]) -> socket.socket:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", _REDIRECT_PORT))
    server.listen(32)
    server.settimeout(0.5)

    def _accept_loop() -> None:
        while True:
            try:
                conn, _unused = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            thread = threading.Thread(
                target=_proxy_one,
                kwargs={"conn": conn, "socket_path": socket_path, "host_ips": host_ips},
                daemon=True,
            )
            thread.start()

    threading.Thread(target=_accept_loop, name="mc-egress-redirect", daemon=True).start()
    return server


def _die_with_parent() -> None:
    """Ask the kernel to SIGKILL this process when the bridge goes away.

    The bridge holds the netns and the relay threads; if a harness ``timeout=``
    SIGKILLs it, the analyzer would otherwise keep running with its egress path
    gone. ``PR_SET_PDEATHSIG`` is Linux-only and best-effort — every other
    platform, and any failure to load libc, simply keeps the old behaviour.
    """
    if sys.platform != "linux":
        return
    with contextlib.suppress(Exception):
        import ctypes

        _PR_SET_PDEATHSIG = 1
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)


def run_analyzer_as_child(command: list[str]) -> int:
    """Fork the analyzer; keep this process so redirect threads stay alive."""
    parent = os.getpid()
    pid = os.fork()
    if pid == 0:
        # 127 mirrors the shell's "command not found". Bare `os.execvp` left the
        # child running Python past the fork on failure, where it fell through to
        # the `waitpid(pid, 0)` below with pid == 0 — waiting on the whole process
        # group instead of exiting.
        try:
            _die_with_parent()
            # PDEATHSIG is delivered on parent death, so a parent that died
            # between fork and prctl would never trigger it. Re-check before exec.
            if os.getppid() != parent:
                os._exit(127)
            os.execvp(command[0], command)
        except BaseException:  # a forked child must never unwind past exec
            os._exit(127)
        os._exit(127)  # unreachable: a successful execvp replaces this image
    _waited, status = os.waitpid(pid, 0)
    if os.WIFEXITED(status):
        return int(os.WEXITSTATUS(status))
    if os.WIFSIGNALED(status):
        return 128 + int(os.WTERMSIG(status))
    return 1


def main(argv: list[str] | None = None) -> int:
    """Enter the isolated netns, start the redirector, run the analyzer as a child."""
    parser = argparse.ArgumentParser(prog="mergecraft-egress-bridge")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--hosts", default="")
    parser.add_argument("--ips", default="")
    parser.add_argument("--map", dest="host_map", default="")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("egress bridge requires a command after --")
    _unshare_into_netns()
    host_ips = parse_host_ip_map(args.host_map)
    if not host_ips:
        hosts = [item for item in args.hosts.split(",") if item]
        ips = [item for item in args.ips.split(",") if item]
        host_ips = {host: list(ips) for host in hosts} if hosts and ips else {}
    _setup_loopback_and_filter()
    _write_hosts(host_ips)
    listener = _serve_redirect(socket_path=args.socket, host_ips=host_ips)
    try:
        return run_analyzer_as_child(command)
    finally:
        with contextlib.suppress(OSError):
            listener.close()


if __name__ == "__main__":
    raise SystemExit(main())
