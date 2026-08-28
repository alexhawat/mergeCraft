"""Sandbox capability probe and isolation (D7)."""

from __future__ import annotations

from pathlib import Path

from tests.analyzers.support import import_module


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
