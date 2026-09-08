"""W3 Step 3 — allowlisted CONNECT proxy and filtered netns wrap (not HTTP_PROXY)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import suppress
from typing import TYPE_CHECKING

import pytest

from mergecraft.analyzers.egress import (
    FilteredEgressSetupError,
    FilteredNetnsSession,
    _parse_resolv_conf,
    _pid_alive,
    allowlist_hosts,
    default_dns_resolvers,
    filtered_egress_available,
    host_is_allowlisted,
    probe_filtered_egress,
    reset_filtered_egress_cache,
    resolve_allowlist_ips,
    sweep_orphaned_filtered_egress,
    wrap_argv_for_filtered_netns,
)
from tests.analyzers.support_allowlist_proxy import AllowlistConnectProxy

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


# setup-uv may install Python under runner-owned mode-0700 directories. The
# capability-free child deliberately cannot bypass those DAC permissions.
_PROBE_PYTHON = "/usr/bin/python3" if sys.platform == "linux" else sys.executable


def _echo_backend() -> tuple[socket.socket, int]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])

    def _accept() -> None:
        conn, _addr = listener.accept()
        try:
            data = conn.recv(1024)
            conn.sendall(data)
        finally:
            conn.close()
            listener.close()

    threading.Thread(target=_accept, daemon=True).start()
    return listener, port


def test_allowlist_hosts_strips_scheme_and_port() -> None:
    hosts = allowlist_hosts(["https://api.osv.dev", "deps.dev:443"])
    assert "api.osv.dev" in hosts
    assert "deps.dev" in hosts


def test_host_is_allowlisted_matches_parent_suffix() -> None:
    allowed = allowlist_hosts(["osv.dev"])
    assert host_is_allowlisted("api.osv.dev", allowed)
    assert not host_is_allowlisted("evil.example", allowed)


def test_resolve_allowlist_ips_includes_loopback() -> None:
    ips = resolve_allowlist_ips(["127.0.0.1"])
    assert "127.0.0.1" in ips


def test_wrap_argv_for_filtered_netns_drops_net() -> None:
    wrapped = wrap_argv_for_filtered_netns(["unshare", "--net", "true"], "mc-eg-test")
    assert wrapped == ["ip", "netns", "exec", "mc-eg-test", "unshare", "true"]


def test_parse_resolv_conf_reads_nameservers_and_skips_ipv6(tmp_path: Path) -> None:
    """(#606 finding 3/4) — IPv6 entries are dropped; they cannot feed ``iptables -d``."""
    conf = tmp_path / "resolv.conf"
    conf.write_text(
        "# comment\n"
        "nameserver 10.0.0.1\n"
        "nameserver 10.0.0.1\n"  # duplicate — must not repeat
        "nameserver 2001:db8::1\n"  # IPv6 — must be skipped
        "search example.com\n"
        "nameserver 10.0.0.2\n",
        encoding="utf-8",
    )
    assert _parse_resolv_conf(conf) == ("10.0.0.1", "10.0.0.2")


def test_parse_resolv_conf_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _parse_resolv_conf(tmp_path / "does-not-exist") == ()


def test_default_dns_resolvers_env_override(monkeypatch: MonkeyPatch) -> None:
    """(#606 finding 4) — configurable via ``MERGECRAFT_EGRESS_DNS_RESOLVERS``."""
    monkeypatch.setenv("MERGECRAFT_EGRESS_DNS_RESOLVERS", "10.1.2.3, 10.4.5.6")
    assert default_dns_resolvers() == ("10.1.2.3", "10.4.5.6")


def test_default_dns_resolvers_falls_back_to_host_resolv_conf(
    monkeypatch: MonkeyPatch,
) -> None:
    """No hardcoded ``1.1.1.1`` when the host's own resolvers are readable."""
    monkeypatch.delenv("MERGECRAFT_EGRESS_DNS_RESOLVERS", raising=False)
    monkeypatch.setattr("mergecraft.analyzers.egress._parse_resolv_conf", lambda: ("192.168.1.1",))
    assert default_dns_resolvers() == ("192.168.1.1",)


def test_default_dns_resolvers_falls_back_to_public_resolver_when_host_has_none(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("MERGECRAFT_EGRESS_DNS_RESOLVERS", raising=False)
    monkeypatch.setattr("mergecraft.analyzers.egress._parse_resolv_conf", lambda: ())
    assert default_dns_resolvers() == ("1.1.1.1",)


def test_session_dns_resolvers_default_matches_default_dns_resolvers() -> None:
    session = FilteredNetnsSession(["127.0.0.1"])
    assert session.dns_resolvers == default_dns_resolvers()


def test_session_dns_resolvers_can_be_overridden() -> None:
    session = FilteredNetnsSession(["127.0.0.1"], dns_resolvers=("10.9.9.9",))
    assert session.dns_resolvers == ("10.9.9.9",)


def test_allowlisted_connect_reaches_backend() -> None:
    _listener, port = _echo_backend()
    with AllowlistConnectProxy(["127.0.0.1"]) as proxy:
        client = socket.create_connection((proxy.host, proxy.port), timeout=5)
        client.sendall(f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\n\r\n".encode())
        status = client.recv(1024)
        assert status.startswith(b"HTTP/1.1 200"), status
        client.sendall(b"ping")
        echoed = client.recv(1024)
        assert echoed == b"ping"
        client.close()


def test_non_allowlisted_connect_is_forbidden() -> None:
    with AllowlistConnectProxy(["api.osv.dev"]) as proxy:
        client = socket.create_connection((proxy.host, proxy.port), timeout=5)
        client.sendall(b"CONNECT evil.example:443 HTTP/1.1\r\n\r\n")
        status = client.recv(1024)
        assert status.startswith(b"HTTP/1.1 403"), status
        client.close()


def test_probe_does_not_fake_availability_on_this_host() -> None:
    """macOS / unprivileged containers report unavailable rather than lying."""
    reset_filtered_egress_cache()
    probe = probe_filtered_egress()
    if not probe.available:
        assert probe.reason
        assert "unavailable" in probe.reason
    else:
        assert probe.network_namespace
        assert probe.veth
        assert probe.ip_netns
        assert probe.iptables


def test_session_start_fails_closed_when_unavailable() -> None:
    reset_filtered_egress_cache()
    if filtered_egress_available():
        pytest.skip("filtered egress is available on this host")
    with pytest.raises(FilteredEgressSetupError):
        FilteredNetnsSession(["127.0.0.1"]).start()


# ---------------------------------------------------------------------------
# (#606 finding 2) — the production FilteredNetnsSession path (netns, veth,
# and the iptables FORWARD allowlist) never ran in any test: every test host
# reports filtered_egress_available() == False, so start() raises on its
# first line and not one line of the netns/veth/iptables code executed
# anywhere. The tests above only exercise AllowlistConnectProxy, which the
# module docstring says production never uses. This self-skips exactly like
# every other test in this module — it is not weakened or faked to run here.
# ---------------------------------------------------------------------------

_ECHO_SERVER_SCRIPT = (
    "import socket\n"
    "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
    "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('0.0.0.0', {port}))\n"
    "s.listen(8)\n"
    "while True:\n"
    "    conn, _ = s.accept()\n"
    "    data = conn.recv(1024)\n"
    "    conn.sendall(data)\n"
    "    conn.close()\n"
)

_CLIENT_CONNECT_SCRIPT = (
    "import socket, sys\n"
    "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
    "s.settimeout(4)\n"
    "try:\n"
    "    s.connect((sys.argv[1], int(sys.argv[2])))\n"
    "except OSError as exc:\n"
    "    print('blocked:', exc)\n"
    "else:\n"
    "    s.sendall(b'ping')\n"
    "    print('connected:', s.recv(1024).decode(errors='replace'))\n"
)


class _FakeWanTarget:
    """A second netns + veth pair standing in for a real, routed destination.

    ``FilteredNetnsSession``'s allowlist is enforced by the host FORWARD
    chain, which never engages for traffic to the host's own veth address
    (that is delivered locally via INPUT, not forwarded). To exercise
    FORWARD for real — rather than merely proving a socket can be opened —
    the destination has to be genuinely routed through the host, so this
    stands up an independent namespace with its own veth pair and a real
    TCP listener, playing the role of "the internet" without depending on
    live network access in CI.
    """

    def __init__(self) -> None:
        pid = os.getpid()
        self.ns = f"mc-eg-test-wan-{pid}"
        self.host_veth = f"mcwh{pid % 10_000}"
        self.peer_veth = f"mcwp{pid % 10_000}"
        self.host_ip = "10.253.0.1"
        self.peer_ip = "10.253.0.2"
        self._server: subprocess.Popen[bytes] | None = None

    def start(self, port: int) -> None:
        for argv in (
            ["ip", "netns", "add", self.ns],
            [
                "ip",
                "link",
                "add",
                self.host_veth,
                "type",
                "veth",
                "peer",
                "name",
                self.peer_veth,
            ],
            ["ip", "link", "set", self.peer_veth, "netns", self.ns],
            ["ip", "addr", "add", f"{self.host_ip}/30", "dev", self.host_veth],
            ["ip", "link", "set", self.host_veth, "up"],
            [
                "ip",
                "netns",
                "exec",
                self.ns,
                "ip",
                "addr",
                "add",
                f"{self.peer_ip}/30",
                "dev",
                self.peer_veth,
            ],
            ["ip", "netns", "exec", self.ns, "ip", "link", "set", self.peer_veth, "up"],
            ["ip", "netns", "exec", self.ns, "ip", "link", "set", "lo", "up"],
        ):
            subprocess.run(argv, check=True, capture_output=True, timeout=5)
        script = _ECHO_SERVER_SCRIPT.format(port=port)
        self._server = subprocess.Popen(
            ["ip", "netns", "exec", self.ns, _PROBE_PYTHON, "-c", script]
        )
        time.sleep(0.3)

    def close(self) -> None:
        if self._server is not None:
            self._server.terminate()
            with suppress(Exception):
                self._server.wait(timeout=2)
            self._server = None
        subprocess.run(
            ["ip", "link", "delete", self.host_veth], check=False, capture_output=True, timeout=5
        )
        subprocess.run(
            ["ip", "netns", "delete", self.ns], check=False, capture_output=True, timeout=5
        )


def _connect_from_netns(ns_name: str, dest_ip: str, port: int) -> str:
    result = subprocess.run(
        [
            "ip",
            "netns",
            "exec",
            ns_name,
            "setpriv",
            "--bounding-set=-all",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            "--no-new-privs",
            "--",
            _PROBE_PYTHON,
            "-c",
            _CLIENT_CONNECT_SCRIPT,
            dest_ip,
            str(port),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result.stdout.strip() or result.stderr.strip()


@pytest.mark.integration
def test_filtered_netns_session_allows_allowlisted_and_drops_the_rest() -> None:
    """The real ``FilteredNetnsSession`` path — not ``AllowlistConnectProxy`` — must
    connect to an allowlisted destination and drop the identical, reachable
    destination when it is not allowlisted (#606 findings 1 and 2)."""
    if os.environ.get("MERGECRAFT_DISPOSABLE_LINUX") != "1":
        pytest.skip("requires make test-filtered-egress in disposable Linux")
    reset_filtered_egress_cache()
    assert filtered_egress_available(), probe_filtered_egress().reason

    port = 39217
    target = _FakeWanTarget()
    target.start(port)
    try:
        allowed = FilteredNetnsSession([target.peer_ip])
        allowed.start()
        try:
            out = _connect_from_netns(allowed.ns_name, target.peer_ip, port)
            assert out.startswith("connected:"), out
            assert "ping" in out
        finally:
            allowed.close()

        # Same reachable destination, a session whose allowlist excludes it:
        # the dedicated FORWARD chain must drop it, not merely fail to route.
        blocked = FilteredNetnsSession(["192.0.2.1"])
        blocked.start()
        try:
            out = _connect_from_netns(blocked.ns_name, target.peer_ip, port)
            assert out.startswith("blocked:"), out
        finally:
            blocked.close()
    finally:
        target.close()


@pytest.mark.integration
def test_filtered_boundary_host_ipv6_concurrency_and_cleanup(monkeypatch: MonkeyPatch) -> None:
    """Exercise kernel INPUT/FORWARD policy and independent session ownership."""
    if os.environ.get("MERGECRAFT_DISPOSABLE_LINUX") != "1":
        pytest.skip("requires make test-filtered-egress in disposable Linux")
    assert filtered_egress_available(), probe_filtered_egress().reason
    target = _FakeWanTarget()
    port = 39218
    sessions: list[FilteredNetnsSession] = []
    subprocess.run(["iptables", "-S"], check=True, capture_output=True)
    subprocess.run(["iptables", "-t", "nat", "-S"], check=True, capture_output=True)
    before = subprocess.run(["iptables-save"], capture_output=True, text=True, check=True).stdout
    target.start(port)
    try:
        # These rules would bypass an appended filter. Session rules must win.
        for chain in ("INPUT", "FORWARD"):
            subprocess.run(["iptables", "-I", chain, "1", "-j", "ACCEPT"], check=True)
        allowed = FilteredNetnsSession([target.peer_ip], dns_resolvers=())
        denied = FilteredNetnsSession(["192.0.2.1"], dns_resolvers=())
        sessions.extend([allowed, denied])
        allowed.start()
        denied.start()
        assert allowed.ns_name != denied.ns_name
        assert allowed._cidr != denied._cidr
        assert _connect_from_netns(allowed.ns_name, target.peer_ip, port).startswith("connected:")
        assert _connect_from_netns(denied.ns_name, target.peer_ip, port).startswith("blocked:")
        host = subprocess.Popen([_PROBE_PYTHON, "-c", _ECHO_SERVER_SCRIPT.format(port=port)])
        try:
            time.sleep(0.3)
            assert _connect_from_netns(allowed.ns_name, allowed._host_ip, port).startswith(
                "blocked:"
            )
            assert _connect_from_netns(allowed.ns_name, "127.0.0.1", port).startswith("blocked:")
            v6 = subprocess.run(
                allowed.wrap_argv(
                    [
                        _PROBE_PYTHON,
                        "-c",
                        "import socket; s=socket.socket(socket.AF_INET6); s.settimeout(1); s.connect(('::1', 39218))",
                    ]
                ),
                capture_output=True,
                timeout=5,
            )
            assert v6.returncode != 0
        finally:
            host.terminate()
            host.wait(timeout=5)
        # Timing out an analyzer and closing its session must not harm its peer.
        with pytest.raises(subprocess.TimeoutExpired):
            subprocess.run(denied.wrap_argv(["sleep", "5"]), timeout=0.1, check=True)
        denied.close()
        assert _connect_from_netns(allowed.ns_name, target.peer_ip, port).startswith("connected:")
        snapshot = subprocess.run(
            ["iptables-save"], capture_output=True, text=True, check=True
        ).stdout
        failed = FilteredNetnsSession([target.peer_ip], dns_resolvers=())
        original = FilteredNetnsSession._apply_filter

        def partial_failure(self: FilteredNetnsSession, ips: frozenset[str]) -> None:
            original(self, ips)
            raise FilteredEgressSetupError("injected setup failure after firewall installation")

        monkeypatch.setattr(FilteredNetnsSession, "_apply_filter", partial_failure)
        with pytest.raises(FilteredEgressSetupError, match="injected setup failure"):
            failed.start()
        after_failure = subprocess.run(
            ["iptables-save"], capture_output=True, text=True, check=True
        ).stdout
        assert _firewall_rules(after_failure) == _firewall_rules(snapshot)
        assert _connect_from_netns(allowed.ns_name, target.peer_ip, port).startswith("connected:")
    finally:
        for session in sessions:
            session.close()
        for chain in ("INPUT", "FORWARD"):
            subprocess.run(["iptables", "-D", chain, "-j", "ACCEPT"], check=False)
        target.close()
    after = subprocess.run(["iptables-save"], capture_output=True, text=True, check=True).stdout
    assert _firewall_rules(after) == _firewall_rules(before)


def _firewall_rules(raw: str) -> list[str]:
    """Ignore counters and generated timestamps when comparing firewall ownership."""
    rows = []
    table = ""
    builtins = {"INPUT", "OUTPUT", "FORWARD", "PREROUTING", "POSTROUTING"}
    for line in raw.splitlines():
        if line.startswith("*"):
            table = line
        elif line.startswith("-A "):
            rows.append(f"{table} {line}")
        elif line.startswith(":"):
            name, policy = line.split()[:2]
            if name[1:] not in builtins or policy != "ACCEPT":
                rows.append(f"{table} {name} {policy}")
    return rows


def test_wrapper_preserves_analyzer_net_argument() -> None:
    assert wrap_argv_for_filtered_netns(
        ["unshare", "--pid", "--net", "bash", "--net"], "example"
    ) == ["ip", "netns", "exec", "example", "unshare", "--pid", "bash", "--net"]
    assert wrap_argv_for_filtered_netns(["analyzer", "--net"], "example")[-2:] == [
        "analyzer",
        "--net",
    ]


def test_sessions_have_independent_names_in_one_process() -> None:
    first = FilteredNetnsSession(["192.0.2.1"])
    second = FilteredNetnsSession(["192.0.2.1"])
    assert first.ns_name != second.ns_name
    assert first._host_veth != second._host_veth


def test_route_inspection_failure_refuses_allocation(monkeypatch: MonkeyPatch) -> None:
    def fail(*a: object, **k: object) -> object:
        raise subprocess.CalledProcessError(1, "ip")

    monkeypatch.setattr("mergecraft.analyzers.egress.subprocess.run", fail)
    with pytest.raises(FilteredEgressSetupError, match="cannot safely inspect"):
        FilteredNetnsSession(["192.0.2.1"])._select_subnet()


def test_route_overlap_excludes_entire_existing_network(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mergecraft.analyzers.egress.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess([], 0, '[{"dst": "10.255.0.0/16"}]', ""),
    )
    with pytest.raises(FilteredEgressSetupError, match="no free"):
        FilteredNetnsSession(["192.0.2.1"])._select_subnet()


def test_cleanup_never_touches_uncreated_objects(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mergecraft.analyzers.egress.subprocess.run",
        lambda *a, **k: pytest.fail("unowned resource deletion"),
    )
    FilteredNetnsSession(["192.0.2.1"]).close()


def test_cleanup_retains_failed_command_for_retry(monkeypatch: MonkeyPatch) -> None:
    session = FilteredNetnsSession(["192.0.2.1"])
    command = ["iptables", "-X", session._chain]
    session._cleanup_commands = [command]
    monkeypatch.setattr(
        "mergecraft.analyzers.egress.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess([], 1, "", "busy"),
    )
    session.close()
    assert session._cleanup_commands == [command]
    monkeypatch.setattr(
        "mergecraft.analyzers.egress.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
    )
    session.close()
    assert session._cleanup_commands == []


@pytest.mark.integration
def test_actual_analyzer_wrapper_prevents_namespace_and_ipv6_escape(tmp_path: Path) -> None:
    """Mount setup must finish before dropping privilege for untrusted argv."""
    if os.environ.get("MERGECRAFT_DISPOSABLE_LINUX") != "1":
        pytest.skip("requires make test-filtered-egress in disposable Linux")
    from mergecraft.analyzers.resolve import AnalyzerPlan
    from mergecraft.analyzers.run import run_plan
    from mergecraft.analyzers.sandbox import SandboxLimits, build_sandbox_context

    target = _FakeWanTarget()
    target.start(39219)
    try:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        marker = tmp_path / "must-not-write"
        bootstrap_marker = tmp_path.parent / "bootstrap-must-not-run"
        malicious_bin = tmp_path / "bin"
        malicious_bin.mkdir()
        startup = tmp_path / "bash-startup"
        startup.write_text(f"/bin/cat /proc/self/status >> {bootstrap_marker}\n")
        for helper in ("ip", "unshare", "mount", "umount", "setpriv"):
            fake = malicious_bin / helper
            fake.write_text(
                f"#!/bin/sh\n/bin/cat /proc/self/status >> {bootstrap_marker}\nexit 77\n"
            )
            fake.chmod(0o755)
        payload_env = {
            **os.environ,
            "PATH": f"{malicious_bin}:/usr/sbin:/usr/bin:/sbin:/bin",
            "BASH_ENV": str(startup),
            "ENV": str(startup),
            "LD_PRELOAD": "/nonexistent/mergecraft-test-loader.so",
        }
        script = (
            "import pathlib, subprocess, sys\n"
            "status = pathlib.Path('/proc/self/status').read_text()\n"
            "for name in ('CapEff', 'CapPrm', 'CapBnd', 'CapAmb'):\n"
            "    value = next(line.split()[1] for line in status.splitlines() if line.startswith(name+':'))\n"
            "    assert int(value, 16) == 0, (name, value)\n"
            "assert subprocess.call(['/usr/sbin/ip', 'netns', 'exec', sys.argv[1], 'true']) != 0\n"
            "assert pathlib.Path('/proc/sys/net/ipv6/conf/all/disable_ipv6').read_text().strip() == '1'\n"
            "try:\n"
            "    pathlib.Path('/proc/sys/net/ipv6/conf/all/disable_ipv6').write_text('0')\n"
            "except OSError:\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('IPv6 sysctl became writable')\n"
            "assert pathlib.Path('/proc/sys/net/ipv6/conf/all/disable_ipv6').read_text().strip() == '1'\n"
            "try:\n"
            "    pathlib.Path(sys.argv[2]).write_text('escaped')\n"
            "except OSError:\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('repository became writable')\n"
            "print('escape attempts blocked')\n"
        )
        plan = AnalyzerPlan(
            manifest_id="probe",
            argv=(_PROBE_PYTHON, "-c", script, target.ns, str(marker)),
            env=payload_env,
            cwd=tmp_path,
            mode="native",
        )
        context = build_sandbox_context(
            repo_root=tmp_path,
            scratch_dir=scratch,
            limits=SandboxLimits(timeout_s=15, memory_mb=512, max_processes=16),
            network_allowlist=[target.peer_ip],
            read_only_source=True,
        )
        result = run_plan(
            plan,
            sandbox_context=context,
            event_name="pull_request_target",
            event={"pull_request": {}},
        )
        assert result.exit_code == 0, result.output
        assert "escape attempts blocked" in result.output
        assert not marker.exists()
        assert not bootstrap_marker.exists()
    finally:
        target.close()


def test_capable_host_still_requires_operator_isolated_runtime_opt_in(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME", raising=False)
    monkeypatch.setattr(
        "mergecraft.analyzers.egress._can_unshare_net",
        lambda: pytest.fail("probe ran without opt-in"),
    )
    reset_filtered_egress_cache()
    probe = probe_filtered_egress()
    assert not probe.available
    assert "operator-owned isolated runtime" in probe.reason


def test_operator_opt_in_does_not_replace_required_capabilities(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME", "1")
    monkeypatch.setattr("mergecraft.analyzers.egress._can_unshare_net", lambda: False)
    reset_filtered_egress_cache()
    probe = probe_filtered_egress()
    assert not probe.available
    assert "unshare" in probe.reason


@pytest.mark.integration
def test_actual_analyzer_timeout_reaps_namespace_child(tmp_path: Path) -> None:
    """A timed-out unshare parent must not leave its analyzer running."""
    if os.environ.get("MERGECRAFT_DISPOSABLE_LINUX") != "1":
        pytest.skip("requires make test-filtered-egress in disposable Linux")
    from mergecraft.analyzers.resolve import AnalyzerPlan
    from mergecraft.analyzers.run import run_plan
    from mergecraft.analyzers.sandbox import SandboxLimits, build_sandbox_context

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    marker = tmp_path.parent / f"{tmp_path.name}-orphan"
    context = build_sandbox_context(
        repo_root=tmp_path,
        scratch_dir=scratch,
        limits=SandboxLimits(timeout_s=10, memory_mb=512, max_processes=16),
        network_allowlist=[],
        read_only_source=True,
    )
    control = AnalyzerPlan(
        manifest_id="probe",
        argv=(
            _PROBE_PYTHON,
            "-c",
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('control')",
            str(marker),
        ),
        cwd=tmp_path,
        mode="native",
        timeout_s=5,
    )
    completed = run_plan(
        control, sandbox_context=context, event_name="pull_request_target", event={}
    )
    assert completed.status == "passed", completed.output
    assert marker.read_text() == "control"
    marker.unlink()
    delayed = AnalyzerPlan(
        manifest_id="probe",
        argv=(
            _PROBE_PYTHON,
            "-c",
            "import pathlib,sys,time; time.sleep(2); pathlib.Path(sys.argv[1]).write_text('orphan')",
            str(marker),
        ),
        cwd=tmp_path,
        mode="native",
        timeout_s=1,
    )
    result = run_plan(delayed, sandbox_context=context, event_name="pull_request_target", event={})
    assert result.status == "timed_out", result.output
    time.sleep(3)
    assert not marker.exists(), "analyzer survived its timed-out unshare parent"


def test_pid_alive_true_for_current_process() -> None:
    assert _pid_alive(os.getpid()) is True


def test_pid_alive_false_for_a_pid_that_does_not_exist() -> None:
    # Linux pid_max tops out well below 2**30; this pid cannot be real.
    assert _pid_alive(2**30) is False


def test_sweep_orphaned_filtered_egress_is_a_noop_without_iptables(
    monkeypatch: MonkeyPatch,
) -> None:
    """(#606 finding 6) — must never raise, even when iptables is unavailable."""
    monkeypatch.setattr("mergecraft.analyzers.egress.shutil.which", lambda _name: None)
    sweep_orphaned_filtered_egress()  # must not raise


def test_a_live_session_id_carries_a_sweepable_pid() -> None:
    """The sweeper keys on the pid in the tag; main's random-only id had none.

    Regression guard for the #606/main merge: if the identity ever loses its
    pid component again, _stale_session_ids stops matching and the sweeper
    silently becomes a no-op while still reporting success.
    """
    from mergecraft.analyzers.egress import _SESSION_ID_RE

    session = FilteredNetnsSession(allowed_hosts=["example.com"])
    match = _SESSION_ID_RE.fullmatch(session.ns_name)
    assert match is not None, f"{session.ns_name!r} is not sweepable"
    assert int(match.group(1)) == os.getpid()
