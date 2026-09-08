"""#538 — userspace filtered egress for the Action image (no host CAP_NET_ADMIN)."""

from __future__ import annotations

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
