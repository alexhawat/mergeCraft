"""Sandbox capability probing and untrusted execution context (D7)."""

from __future__ import annotations

import os
import resource
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger

from mergecraft.mcp.shell import detect_sandbox_method

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import AnalyzerManifest, TrustTier

NetworkDefault = Literal["deny", "allow"]


@dataclass(frozen=True, slots=True)
class SandboxCapabilities:
    pid_namespace: bool
    network_namespace: bool
    read_only_bind: bool
    tmpfs: bool
    cgroup_memory: bool
    rlimit_nproc: bool
    unavailable_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    timeout_s: int
    memory_mb: int
    max_processes: int


@dataclass(frozen=True, slots=True)
class SandboxContext:
    repo_root: Path
    scratch_dir: Path
    timeout_s: int
    memory_mb: int
    max_processes: int
    read_only_source: bool
    source_mount_read_only: bool
    network_allowlist: list[str]
    network_default: NetworkDefault
    unavailable_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SandboxPlan:
    can_run: bool
    skip_reason: str | None = None
    context: SandboxContext | None = None


def _probe_pid_namespace() -> tuple[bool, str | None]:
    method = detect_sandbox_method()
    if method in {"unshare", "sudo-unshare"}:
        return True, None
    return False, "pid namespace unavailable (unshare failed)"


def _probe_network_namespace() -> tuple[bool, str | None]:
    if os.environ.get("CI") != "true":
        return False, "network namespace unavailable outside CI"
    try:
        result = subprocess.run(
            ["unshare", "--net", "true"],
            timeout=5,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return True, None
    except OSError:
        pass
    return False, "network namespace unavailable (unshare --net failed)"


def _probe_read_only_bind() -> tuple[bool, str | None]:
    if os.environ.get("CI") != "true":
        return False, "read-only bind mount unavailable outside CI"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "ro-target"
            target.mkdir()
            (target / "file").write_text("x", encoding="utf-8")
            mountpoint = root / "mnt"
            mountpoint.mkdir()
            bind = subprocess.run(
                ["mount", "--bind", str(target), str(mountpoint)],
                capture_output=True,
                check=False,
            )
            if bind.returncode != 0:
                return False, "read-only bind mount unavailable (bind failed)"
            remount = subprocess.run(
                ["mount", "-o", "remount,bind,ro", str(mountpoint)],
                capture_output=True,
                check=False,
            )
            subprocess.run(["umount", str(mountpoint)], capture_output=True, check=False)
            if remount.returncode == 0:
                return True, None
    except OSError:
        pass
    return False, "read-only bind mount unavailable (remount ro failed)"


def _probe_tmpfs() -> tuple[bool, str | None]:
    if os.environ.get("CI") != "true":
        return False, "tmpfs scratch unavailable outside CI"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            mountpoint = Path(tmp) / "scratch"
            mountpoint.mkdir()
            result = subprocess.run(
                ["mount", "-t", "tmpfs", "tmpfs", str(mountpoint)],
                capture_output=True,
                check=False,
            )
            subprocess.run(["umount", str(mountpoint)], capture_output=True, check=False)
            if result.returncode == 0:
                return True, None
    except OSError:
        pass
    return False, "tmpfs scratch unavailable (mount tmpfs failed)"


def _probe_cgroup_memory() -> tuple[bool, str | None]:
    return False, "cgroup memory limits unavailable in Action container (W0.4 probe)"


def _probe_rlimit_nproc() -> tuple[bool, str | None]:
    try:
        resource.getrlimit(resource.RLIMIT_NPROC)
        return True, None
    except OSError:
        return False, "RLIMIT_NPROC unavailable"


def probe_capabilities() -> SandboxCapabilities:
    """Probe isolation primitives; record every unavailable capability by name."""
    reasons: list[str] = []
    pid_ok, pid_reason = _probe_pid_namespace()
    if pid_reason:
        reasons.append(pid_reason)
    net_ok, net_reason = _probe_network_namespace()
    if net_reason:
        reasons.append(net_reason)
    ro_ok, ro_reason = _probe_read_only_bind()
    if ro_reason:
        reasons.append(ro_reason)
    tmpfs_ok, tmpfs_reason = _probe_tmpfs()
    if tmpfs_reason:
        reasons.append(tmpfs_reason)
    cgroup_ok, cgroup_reason = _probe_cgroup_memory()
    if cgroup_reason:
        reasons.append(cgroup_reason)
    nproc_ok, nproc_reason = _probe_rlimit_nproc()
    if nproc_reason:
        reasons.append(nproc_reason)

    caps = SandboxCapabilities(
        pid_namespace=pid_ok,
        network_namespace=net_ok,
        read_only_bind=ro_ok,
        tmpfs=tmpfs_ok,
        cgroup_memory=cgroup_ok,
        rlimit_nproc=nproc_ok,
        unavailable_reasons=reasons,
    )
    if reasons:
        logger.info("sandbox capabilities unavailable: {}", "; ".join(reasons))
    return caps


def _required_for_untrusted(caps: SandboxCapabilities) -> list[str]:
    missing: list[str] = []
    if not caps.network_namespace:
        missing.append("network namespace")
    if not caps.read_only_bind:
        missing.append("read-only source mount")
    if not caps.tmpfs:
        missing.append("tmpfs scratch")
    return missing


def build_sandbox_context(
    *,
    repo_root: Path,
    scratch_dir: Path,
    limits: SandboxLimits,
    network_allowlist: list[str],
    read_only_source: bool,
    caps: SandboxCapabilities | None = None,
) -> SandboxContext:
    probed = caps if caps is not None else probe_capabilities()
    _ = probed
    return SandboxContext(
        repo_root=repo_root,
        scratch_dir=scratch_dir,
        timeout_s=limits.timeout_s,
        memory_mb=limits.memory_mb,
        max_processes=limits.max_processes,
        read_only_source=read_only_source,
        source_mount_read_only=read_only_source,
        network_allowlist=list(network_allowlist),
        network_default="deny",
        unavailable_capabilities=tuple(probed.unavailable_reasons),
    )


def plan_sandbox(
    *,
    manifest: AnalyzerManifest,
    tier: TrustTier,
    repo_root: Path,
    scratch_dir: Path,
) -> SandboxPlan:
    """Plan sandbox execution; skip untrusted analyzers when isolation is missing (D7)."""
    limits = SandboxLimits(
        timeout_s=manifest.timeout_s,
        memory_mb=512,
        max_processes=16,
    )
    caps = probe_capabilities()
    if tier == "untrusted":
        missing = _required_for_untrusted(caps)
        if missing:
            reason = f"skipped {manifest.id}: sandbox isolation unavailable — " + ", ".join(missing)
            logger.info("{}", reason)
            return SandboxPlan(can_run=False, skip_reason=reason)

    context = build_sandbox_context(
        repo_root=repo_root,
        scratch_dir=scratch_dir,
        limits=limits,
        network_allowlist=manifest.network_allowlist,
        read_only_source=tier == "untrusted",
        caps=caps,
    )
    return SandboxPlan(can_run=True, context=context)


__all__ = [
    "NetworkDefault",
    "SandboxCapabilities",
    "SandboxContext",
    "SandboxLimits",
    "SandboxPlan",
    "build_sandbox_context",
    "plan_sandbox",
    "probe_capabilities",
]
