"""#538 — userspace filtered egress for the Action image (no host CAP_NET_ADMIN)."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from mergecraft.analyzers.egress import (
    FilteredEgressSetupError,
    probe_filtered_egress,
    reset_filtered_egress_cache,
)
from mergecraft.analyzers.egress_userspace import (
    UserspaceEgressSession,
    relay_request_allowed,
    wrap_argv_for_userspace_relay,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def test_relay_request_allows_only_declared_ips() -> None:
    assert relay_request_allowed(
        host="api.osv.dev",
        ip="1.2.3.4",
        allowed_hosts=["api.osv.dev"],
        allowed_ips=["1.2.3.4"],
    )
    assert not relay_request_allowed(
        host="evil.example",
        ip="9.9.9.9",
        allowed_hosts=["api.osv.dev"],
        allowed_ips=["1.2.3.4"],
    )


def test_wrap_argv_prefixes_bridge_module() -> None:
    wrapped = wrap_argv_for_userspace_relay(
        ["osv-scanner", "--lockfile=uv.lock"],
        socket_path="/tmp/mc-eg.sock",
        allowed_hosts=["api.osv.dev"],
        allowed_ips=["1.2.3.4"],
    )
    assert wrapped[1:3] == ["-m", "mergecraft.analyzers.egress_bridge"]
    assert "--socket" in wrapped
    assert "/tmp/mc-eg.sock" in wrapped
    assert wrapped[-2:] == ["osv-scanner", "--lockfile=uv.lock"]
    assert "--map" in wrapped


def test_hosts_file_maps_each_host_to_its_own_ips() -> None:
    from mergecraft.analyzers.egress_bridge import host_for_ip, hosts_file_lines

    mapping = {"api.osv.dev": ["1.2.3.4"], "deps.dev": ["5.6.7.8"]}
    text = "".join(hosts_file_lines(mapping))
    assert "1.2.3.4 api.osv.dev" in text
    assert "5.6.7.8 deps.dev" in text
    assert "1.2.3.4 deps.dev" not in text
    assert host_for_ip("5.6.7.8", mapping) == "deps.dev"


def test_unshare_reexec_uses_module_path() -> None:
    from mergecraft.analyzers.egress_bridge import unshare_reexec_argv

    argv = unshare_reexec_argv(["--socket", "/tmp/x", "--", "true"])
    assert argv[:5] == ["unshare", "--user", "--map-root-user", "--mount", "--net"]
    assert "-m" in argv
    assert "mergecraft.analyzers.egress_bridge" in argv


def test_run_analyzer_as_child_propagates_exit_status() -> None:
    from mergecraft.analyzers.egress_bridge import run_analyzer_as_child

    code = run_analyzer_as_child([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert code == 3


def test_userspace_backend_does_not_need_isolated_runtime_opt_in(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME", raising=False)
    monkeypatch.setattr(
        "mergecraft.analyzers.egress._can_unshare_net",
        lambda: pytest.fail("kernel probe ran without opt-in"),
    )
    monkeypatch.setattr(
        "mergecraft.analyzers.egress_userspace.probe_userspace_egress",
        lambda: __import__(
            "mergecraft.analyzers.egress", fromlist=["FilteredEgressProbe"]
        ).FilteredEgressProbe(
            network_namespace=True,
            veth=False,
            ip_netns=False,
            iptables=True,
            available=True,
            reason="",
            backend="userspace",
            user_namespace=True,
        ),
    )
    reset_filtered_egress_cache()
    probe = probe_filtered_egress()
    assert probe.available
    assert probe.backend == "userspace"


def test_kernel_backend_still_requires_operator_isolated_runtime_opt_in(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME", raising=False)
    monkeypatch.setattr(
        "mergecraft.analyzers.egress._can_unshare_net",
        lambda: pytest.fail("kernel probe ran without opt-in"),
    )
    monkeypatch.setattr(
        "mergecraft.analyzers.egress_userspace.probe_userspace_egress",
        lambda: __import__(
            "mergecraft.analyzers.egress", fromlist=["FilteredEgressProbe"]
        ).FilteredEgressProbe(
            network_namespace=False,
            veth=False,
            ip_netns=False,
            iptables=False,
            available=False,
            reason="userspace filtered egress unavailable: unshare --user --map-root-user --net",
            backend="none",
        ),
    )
    reset_filtered_egress_cache()
    probe = probe_filtered_egress()
    assert not probe.available
    assert "isolated runtime" in probe.reason


def test_userspace_session_start_fails_closed_when_unavailable(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mergecraft.analyzers.egress_userspace.probe_userspace_egress",
        lambda: __import__(
            "mergecraft.analyzers.egress", fromlist=["FilteredEgressProbe"]
        ).FilteredEgressProbe(
            network_namespace=False,
            veth=False,
            ip_netns=False,
            iptables=False,
            available=False,
            reason="userspace filtered egress unavailable: iptables",
            backend="none",
        ),
    )
    with pytest.raises(FilteredEgressSetupError, match="unavailable"):
        UserspaceEgressSession(["api.osv.dev"]).start()


def test_session_socket_dir_is_private(monkeypatch: MonkeyPatch) -> None:
    import stat
    from pathlib import Path

    monkeypatch.setattr(
        "mergecraft.analyzers.egress_userspace.probe_userspace_egress",
        lambda: __import__(
            "mergecraft.analyzers.egress", fromlist=["FilteredEgressProbe"]
        ).FilteredEgressProbe(
            network_namespace=True,
            veth=False,
            ip_netns=False,
            iptables=True,
            available=True,
            reason="",
            backend="userspace",
            user_namespace=True,
        ),
    )
    monkeypatch.setattr(
        "mergecraft.analyzers.egress_userspace.resolve_allowlist_host_ips",
        lambda _hosts: {"api.osv.dev": frozenset(["1.2.3.4"])},
    )
    session = UserspaceEgressSession(["api.osv.dev"])
    session.start()
    try:
        mode = Path(session._socket_dir).stat().st_mode
        assert stat.S_IMODE(mode) == 0o700
    finally:
        session.close()
