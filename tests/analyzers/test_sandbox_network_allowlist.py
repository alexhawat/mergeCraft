"""An analyzer declaring ``network_allowlist`` must keep egress (#533 review).

``build_analyzer_sandbox_argv`` hardcoded ``isolate_network=True``, so every
sandboxed analyzer got ``unshare --net`` -- a namespace with no external
connectivity. ``osv-scanner`` and ``trivy`` are ``trust: untrusted`` with
non-empty allowlists and cannot work without egress, so both broke on any host
where ``unshare --net`` succeeds. The failure is silent: an erroring analyzer is
reported unavailable, not as a finding.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mergecraft.analyzers import sandbox as sandbox_mod
from mergecraft.analyzers.sandbox import (
    SandboxCapabilities,
    SandboxLimits,
    build_analyzer_sandbox_argv,
    build_sandbox_context,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def _context(tmp_path: Path, allowlist: list[str]) -> object:
    return build_sandbox_context(
        repo_root=tmp_path,
        scratch_dir=tmp_path / "scratch",
        limits=SandboxLimits(timeout_s=60, memory_mb=512, max_processes=64),
        network_allowlist=allowlist,
        read_only_source=True,
    )


@pytest.fixture(autouse=True)
def _force_full_isolation(monkeypatch: MonkeyPatch) -> None:
    """Pin the host-dependent halves so the argv is a pure function of the manifest.

    Without this the test passes vacuously on macOS and on GitHub's runners
    alike, where ``unshare --net`` is unavailable and ``--net`` is never
    appended for any input -- which is precisely the environment blind spot
    that let the regression through.
    """
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
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", lambda: caps)
    monkeypatch.setattr(sandbox_mod, "detect_sandbox_method", lambda: "unshare", raising=False)
    monkeypatch.setattr("mergecraft.mcp.shell.detect_sandbox_method", lambda: "unshare")


def test_declared_network_allowlist_keeps_egress(tmp_path: Path) -> None:
    argv = build_analyzer_sandbox_argv(
        ("osv-scanner", "--format", "json", "."),
        context=_context(tmp_path, ["https://api.osv.dev", "https://deps.dev"]),
    )
    assert "--net" not in argv, (
        f"an analyzer declaring network_allowlist must not be network-isolated; got {argv!r}"
    )


def test_empty_allowlist_still_isolates_the_network(tmp_path: Path) -> None:
    argv = build_analyzer_sandbox_argv(
        ("ruff", "check", "."),
        context=_context(tmp_path, []),
    )
    assert "--net" in argv, (
        f"an analyzer declaring no network needs must stay isolated; got {argv!r}"
    )


def test_pid_isolation_is_unconditional(tmp_path: Path) -> None:
    """Relaxing the network must not relax process isolation."""
    for allowlist in ([], ["https://api.osv.dev"]):
        argv = build_analyzer_sandbox_argv(("tool",), context=_context(tmp_path, allowlist))
        assert "--pid" in argv, f"pid isolation lost for allowlist={allowlist!r}: {argv!r}"
        assert "--mount-proc" in argv, f"proc isolation lost for allowlist={allowlist!r}: {argv!r}"
