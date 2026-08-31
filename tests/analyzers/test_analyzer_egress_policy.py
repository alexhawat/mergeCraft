"""W1.2 — analyzer egress fail-closed (wave plan 15, green after W3)."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mergecraft.analyzers.sandbox import (
    SandboxCapabilities,
    SandboxLimits,
    build_analyzer_sandbox_argv,
    build_sandbox_context,
)
from tests.analyzers.support import FORK_PULL_REQUEST_EVENT, SAME_REPO_PULL_REQUEST_EVENT
from tests.trust_credentials.support import import_analyzer_egress_symbol

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_OSV_ALLOWLIST = ["https://api.osv.dev", "https://deps.dev"]


def _sandbox_context(tmp_path: Path, allowlist: list[str]) -> object:
    return build_sandbox_context(
        repo_root=tmp_path,
        scratch_dir=tmp_path / "scratch",
        limits=SandboxLimits(timeout_s=60, memory_mb=512, max_processes=64),
        network_allowlist=allowlist,
        read_only_source=True,
    )


@pytest.fixture(autouse=True)
def _force_unshare_sandbox(monkeypatch: MonkeyPatch) -> None:
    """Pin host capabilities so argv assertions are meaningful (D5b scope)."""
    caps = SandboxCapabilities(
        pid_namespace=True,
        network_namespace=True,
        read_only_bind=True,
        tmpfs=True,
        cgroup_memory=True,
        rlimit_nproc=True,
        pid_namespace_method="unshare",
        unavailable_reasons=[],
    )
    monkeypatch.setattr("mergecraft.analyzers.sandbox.probe_capabilities", lambda: caps)
    monkeypatch.setattr("mergecraft.mcp.shell.detect_sandbox_method", lambda: "unshare")


def _egress_argv(
    tmp_path: Path,
    *,
    allowlist: list[str],
    event_name: str,
    event: dict[str, object],
    self_review: str = "off",
) -> list[str]:
    build = import_analyzer_egress_symbol("build_analyzer_sandbox_argv_for_run")
    return build(
        ("osv-scanner", "--format", "json", "."),
        context=_sandbox_context(tmp_path, allowlist),
        event_name=event_name,
        event=event,
        self_review_level=self_review,
        analyzer_id="osv-scanner",
    )


def test_push_event_allows_host_networking_for_allowlist_declaring_analyzer(
    tmp_path: Path,
) -> None:
    """Push CI sets ``GITHUB_EVENT_NAME=push`` — same-repo writers are trusted for egress."""
    evaluate = import_analyzer_egress_symbol("evaluate_analyzer_egress_policy")
    outcome = evaluate(
        analyzer_id="osv-scanner",
        network_allowlist=_OSV_ALLOWLIST,
        event_name="push",
        event={"ref": "refs/heads/main", "repository": {"full_name": "acme/demo"}},
        self_review_level="off",
    )
    assert outcome.status == "allowed"


def test_untrusted_non_empty_allowlist_does_not_get_host_networking(tmp_path: Path) -> None:
    """D5 — untrusted tier + declared allowlist must not drop --net isolation."""
    argv = _egress_argv(
        tmp_path,
        allowlist=_OSV_ALLOWLIST,
        event_name="pull_request_target",
        event=FORK_PULL_REQUEST_EVENT,
    )
    assert "--net" in argv, f"expected network isolation, got {argv!r}"


def test_trusted_tier_keeps_egress_for_allowlist_declaring_analyzer(tmp_path: Path) -> None:
    """D7 regression — trusted runs keep today's host-networking behaviour for osv-scanner."""
    argv = build_analyzer_sandbox_argv(
        ("osv-scanner", "--format", "json", "."),
        context=_sandbox_context(tmp_path, _OSV_ALLOWLIST),
    )
    assert "--net" not in argv


def test_empty_allowlist_still_isolates_network(tmp_path: Path) -> None:
    """Regression — empty allowlist keeps full network isolation."""
    argv = build_analyzer_sandbox_argv(
        ("ruff", "check", "."),
        context=_sandbox_context(tmp_path, []),
    )
    assert "--net" in argv


def test_lane_d_self_review_analyzers_prt_still_isolates_network(tmp_path: Path) -> None:
    """D5a — selfReview analyzers + same-repo pull_request_target + allowlist → no host networking."""
    argv = _egress_argv(
        tmp_path,
        allowlist=_OSV_ALLOWLIST,
        event_name="pull_request_target",
        event=SAME_REPO_PULL_REQUEST_EVENT,
        self_review="analyzers",
    )
    assert "--net" in argv, f"lane-D coupling must not grant host networking: {argv!r}"


def test_untrusted_allowlist_skip_is_distinct_from_unavailable(tmp_path: Path) -> None:
    """D6 — egress-policy skip is a first-class outcome, not unavailable or clean."""
    evaluate = import_analyzer_egress_symbol("evaluate_analyzer_egress_policy")
    outcome = evaluate(
        analyzer_id="osv-scanner",
        network_allowlist=_OSV_ALLOWLIST,
        event_name="pull_request_target",
        event=FORK_PULL_REQUEST_EVENT,
        self_review_level="off",
    )
    assert outcome.status == "skipped"
    assert outcome.status != "unavailable"
    assert "egress" in outcome.reason.lower()


def test_egress_skip_reason_names_analyzer_and_hosts(tmp_path: Path) -> None:
    """Skip reason names the analyzer and declared hosts."""
    evaluate = import_analyzer_egress_symbol("evaluate_analyzer_egress_policy")
    outcome = evaluate(
        analyzer_id="osv-scanner",
        network_allowlist=_OSV_ALLOWLIST,
        event_name="pull_request_target",
        event=FORK_PULL_REQUEST_EVENT,
        self_review_level="off",
    )
    reason = outcome.reason.lower()
    assert "osv-scanner" in reason
    assert "api.osv.dev" in reason or "osv.dev" in reason


def test_build_analyzer_env_no_longer_discards_network_allowlist() -> None:
    """trust.py must not silently discard network_allowlist (the #538 root cause)."""
    from mergecraft.analyzers import trust as trust_mod

    source = inspect.getsource(trust_mod.build_analyzer_env)
    assert "_ = event, network_allowlist" not in source
    assert "network_allowlist" in source
