"""Sandbox capability probe and isolation (D7).

Also pins the identity the analyzer sandbox installs: on a root orchestrator it
omits the ``--user --map-root-user`` mapping and drops the payload to the agent
user; off the root backend the argv is unchanged.
"""

from __future__ import annotations

import os
import pwd
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from tests.analyzers.support import import_module

if TYPE_CHECKING:
    import pytest


class _FakePwEntry:
    """Minimal ``pwd.struct_passwd`` stand-in for the drop target."""

    def __init__(self, name: str = "mergecraft", uid: int = 10001, gid: int = 10001) -> None:
        self.pw_name = name
        self.pw_uid = uid
        self.pw_gid = gid


def _full_caps_with_user_namespace() -> object:
    sandbox = import_module("mergecraft.analyzers.sandbox")
    return sandbox.SandboxCapabilities(
        pid_namespace=True,
        network_namespace=True,
        read_only_bind=True,
        tmpfs=True,
        cgroup_memory=False,
        rlimit_nproc=True,
        pid_namespace_method="unshare",
        user_namespace=True,
    )


def _fake_drop_tools(monkeypatch: pytest.MonkeyPatch, *, uid: int) -> None:
    monkeypatch.setattr(os, "getuid", lambda: uid)
    monkeypatch.setattr(os, "geteuid", lambda: uid)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(pwd, "getpwnam", lambda name: _FakePwEntry(name))
    from mergecraft.utils import privilege

    monkeypatch.setattr(privilege, "_in_action_image", lambda: True)
    monkeypatch.setattr(privilege, "_setpriv_supports_bounding_set", lambda: True)


def _analyzer_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sandbox = import_module("mergecraft.analyzers.sandbox")
    shell_mod = import_module("mergecraft.mcp.shell")
    monkeypatch.setattr(sandbox, "probe_capabilities", _full_caps_with_user_namespace)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
    context = sandbox.build_sandbox_context(
        repo_root=tmp_path,
        scratch_dir=tmp_path / "scratch",
        limits=sandbox.SandboxLimits(timeout_s=30, memory_mb=256, max_processes=8),
        network_allowlist=[],
        read_only_source=True,
        caps=_full_caps_with_user_namespace(),
    )
    return sandbox.build_analyzer_sandbox_argv(
        ("echo", "probe"), context=context, isolate_network=False
    )


def test_root_analyzer_argv_omits_map_root_user_and_drops_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UID 0 maps 0→0, so the sandbox must not use it and must drop instead."""
    _fake_drop_tools(monkeypatch, uid=0)
    argv = _analyzer_argv(tmp_path, monkeypatch)
    joined = " ".join(argv)
    assert "--user" not in argv, argv
    assert "--map-root-user" not in argv, argv
    assert "--reuid=mergecraft" in joined, argv
    assert "--regid=mergecraft" in joined, argv
    assert "--no-new-privs" in joined, argv
    assert "--inh-caps=-all" in joined, argv


def test_non_root_analyzer_argv_keeps_map_root_user_and_no_reuid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off the root backend the analyzer argv is unchanged."""
    _fake_drop_tools(monkeypatch, uid=4242)
    argv = _analyzer_argv(tmp_path, monkeypatch)
    joined = " ".join(argv)
    assert "--user" in argv, argv
    assert "--map-root-user" in argv, argv
    assert "--reuid" not in joined, argv
    assert "--regid" not in joined, argv


def test_capability_probe_records_unavailable_primitives_by_name() -> None:
    sandbox = import_module("mergecraft.analyzers.sandbox")
    caps = sandbox.probe_capabilities()
    assert hasattr(caps, "network_namespace")
    assert hasattr(caps, "pid_namespace")
    if caps.unavailable_reasons:
        assert all(isinstance(r, str) and r for r in caps.unavailable_reasons)
    if not caps.network_namespace:
        assert any("net" in r.lower() or "unshare" in r.lower() for r in caps.unavailable_reasons)


def test_untrusted_analyzer_skipped_when_required_capability_missing(tmp_path: Path) -> None:
    sandbox = import_module("mergecraft.analyzers.sandbox")
    manifest = import_module("mergecraft.analyzers.manifest")
    m = manifest.load_manifest_file(
        Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml")
    )
    decision = sandbox.plan_sandbox(
        manifest=m,
        tier="untrusted",
        repo_root=tmp_path,
        scratch_dir=tmp_path / "scratch",
    )
    if not decision.can_run:
        assert decision.skip_reason
        assert (
            "network" in decision.skip_reason.lower() or "sandbox" in decision.skip_reason.lower()
        )


def test_sandbox_applies_time_memory_and_process_caps(tmp_path: Path) -> None:
    sandbox = import_module("mergecraft.analyzers.sandbox")
    limits = sandbox.SandboxLimits(timeout_s=30, memory_mb=512, max_processes=16)
    ctx = sandbox.build_sandbox_context(
        repo_root=tmp_path,
        scratch_dir=tmp_path / "scratch",
        limits=limits,
        network_allowlist=[],
        read_only_source=True,
    )
    assert ctx.timeout_s == 30
    assert ctx.memory_mb == 512
    assert ctx.max_processes == 16
    assert ctx.read_only_source is True


def test_tmpfs_scratch_and_read_only_source_paths(tmp_path: Path) -> None:
    sandbox = import_module("mergecraft.analyzers.sandbox")
    scratch = tmp_path / "scratch"
    ctx = sandbox.build_sandbox_context(
        repo_root=tmp_path,
        scratch_dir=scratch,
        limits=sandbox.SandboxLimits(timeout_s=60, memory_mb=256, max_processes=8),
        network_allowlist=[],
        read_only_source=True,
    )
    assert ctx.scratch_dir == scratch
    assert ctx.source_mount_read_only is True


def test_network_denied_except_manifest_allowlist(tmp_path: Path) -> None:
    sandbox = import_module("mergecraft.analyzers.sandbox")
    allowlist = ["https://github.com"]
    ctx = sandbox.build_sandbox_context(
        repo_root=tmp_path,
        scratch_dir=tmp_path / "scratch",
        limits=sandbox.SandboxLimits(timeout_s=60, memory_mb=256, max_processes=8),
        network_allowlist=allowlist,
        read_only_source=True,
    )
    assert ctx.network_allowlist == allowlist
    assert ctx.network_default == "deny"
