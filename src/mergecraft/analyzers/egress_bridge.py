"""Child-side userspace egress bridge — isolated netns + parent Unix relay (#538).

Invoked as ``python -m mergecraft.analyzers.egress_bridge``. The parent process
stays on the container network and makes allowlisted TCP connections. This
process enters a user+net namespace, redirects outbound TCP to a local
accept loop, and forwards original destinations over the Unix socket.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
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


def _unshare_into_netns() -> None:
    if os.environ.get("MERGECRAFT_EGRESS_BRIDGE_IN_NS") == "1":
        return
    env = dict(os.environ)
    env["MERGECRAFT_EGRESS_BRIDGE_IN_NS"] = "1"
    os.execvpe(
        "unshare",
        ["unshare", "--user", "--map-root-user", "--mount", "--net", sys.executable, *sys.argv],
        env,
    )


def _setup_loopback_and_filter(*, allowed_ips: list[str]) -> None:
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
    _ = allowed_ips
    for scope in ("all", "default", "lo"):
        subprocess.run(
            ["sysctl", "-w", f"net.ipv6.conf.{scope}.disable_ipv6=1"],
            check=False,
            capture_output=True,
            timeout=5,
        )


def _write_hosts(allowed_hosts: list[str], allowed_ips: list[str]) -> None:
    lines = ["127.0.0.1 localhost\n"]
    if allowed_hosts and allowed_ips:
        first_ip = allowed_ips[0]
        for host in allowed_hosts:
            if host:
                lines.append(f"{first_ip} {host}\n")
        for ip in allowed_ips:
            # Each resolved IP must also be reachable by the original hostname
            # set; extra IPs are listed so getaddrinfo can still hit them via
            # the relay even when libc picked a different A record.
            if ip != first_ip:
                suffix = " ".join(allowed_hosts)
                if suffix:
                    lines.append(f"{ip} {suffix}\n")
    hosts_path = Path(tempfile.mkdtemp(prefix="mc-eg-hosts-")) / "hosts"
    hosts_path.write_text("".join(lines), encoding="utf-8")
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
    allowed_hosts: list[str],
    allowed_ips: list[str],
) -> None:
    remote: socket.socket | None = None
    try:
        ip, port = _original_destination(conn)
        if not relay_request_allowed(
            host="",
            ip=ip,
            allowed_hosts=allowed_hosts,
            allowed_ips=allowed_ips,
        ):
            return
        remote = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        remote.settimeout(10)
        remote.connect(socket_path)
        payload = json.dumps({"host": "", "ip": ip, "port": port}) + "\n"
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

    first = threading.Thread(target=_copy, args=(left, right), daemon=True)
    second = threading.Thread(target=_copy, args=(right, left), daemon=True)
    first.start()
    second.start()
    first.join()
    second.join()


def _serve_redirect(
    *,
    socket_path: str,
    allowed_hosts: list[str],
    allowed_ips: list[str],
) -> None:
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
                kwargs={
                    "conn": conn,
                    "socket_path": socket_path,
                    "allowed_hosts": allowed_hosts,
                    "allowed_ips": allowed_ips,
                },
                daemon=True,
            )
            thread.start()

    threading.Thread(target=_accept_loop, name="mc-egress-redirect", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    """Enter the isolated netns (if needed), start the redirector, exec the analyzer."""
    parser = argparse.ArgumentParser(prog="mergecraft-egress-bridge")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--hosts", default="")
    parser.add_argument("--ips", default="")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("egress bridge requires a command after --")
    _unshare_into_netns()
    hosts = [item for item in args.hosts.split(",") if item]
    ips = [item for item in args.ips.split(",") if item]
    _setup_loopback_and_filter(allowed_ips=ips)
    _write_hosts(hosts, ips)
    _serve_redirect(socket_path=args.socket, allowed_hosts=hosts, allowed_ips=ips)
    os.execvp(command[0], command)


if __name__ == "__main__":
    raise SystemExit(main())
