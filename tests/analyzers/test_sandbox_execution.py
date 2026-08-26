"""Lane A — analyzer sandbox execution must enforce probed capabilities (D6)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from mergecraft.analyzers import sandbox as sandbox_mod
from mergecraft.analyzers.run import _sandboxed_argv
from mergecraft.analyzers.sandbox import SandboxContext, SandboxLimits, build_sandbox_context
from mergecraft.mcp import shell as shell_mod


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    shell_mod.reset_detection_cache()
    sandbox_mod.reset_detection_cache()


def _full_caps() -> sandbox_mod.SandboxCapabilities:
    return sandbox_mod.SandboxCapabilities(
        pid_namespace=True,
        network_namespace=True,
        read_only_bind=True,
        tmpfs=True,
        cgroup_memory=False,
        rlimit_nproc=True,
        pid_namespace_method="unshare",
    )


def _sandbox_context(tmp_path: Path) -> SandboxContext:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return build_sandbox_context(
        repo_root=tmp_path,
        scratch_dir=scratch,
        limits=SandboxLimits(timeout_s=30, memory_mb=256, max_processes=8),
        network_allowlist=[],
        read_only_source=True,
        caps=_full_caps(),
    )


def test_sandboxed_argv_wires_net_ro_bind_and_tmpfs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", lambda: _full_caps())
    shell_mod._reset_shell_detection_globals()

    from mergecraft.analyzers.resolve import AnalyzerPlan

    plan = AnalyzerPlan(
        manifest_id="actionlint",
        argv=("echo", "probe"),
        cwd=tmp_path,
        mode="native",
    )
    argv, _preexec = _sandboxed_argv(plan, _sandbox_context(tmp_path))
    joined = " ".join(argv)
    assert argv[:4] == ["unshare", "--pid", "--fork", "--mount-proc"]
    assert "--net" in argv
    assert "remount,bind,ro" in joined
    assert "tmpfs" in joined
    assert str(tmp_path) in joined
    assert "bash" in argv
    assert "exec echo probe" in joined


def test_sandboxed_argv_uses_sudo_unshare_when_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "sudo-unshare")
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", lambda: _full_caps())
    shell_mod._reset_shell_detection_globals()

    from mergecraft.analyzers.resolve import AnalyzerPlan

    plan = AnalyzerPlan(
        manifest_id="actionlint",
        argv=("true",),
        cwd=tmp_path,
        mode="native",
    )
    argv, _preexec = _sandboxed_argv(plan, _sandbox_context(tmp_path))
    assert argv[0] == "sudo"
    assert "--net" in argv


@pytest.mark.skipif(sys.platform != "linux", reason="namespace mounts require Linux")
def test_sandboxed_execution_blocks_repo_write_and_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caps = _full_caps()
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", lambda: caps)
    shell_mod._reset_shell_detection_globals()
    method = shell_mod.detect_sandbox_method()
    if method == "none":
        pytest.skip("PID namespace isolation unavailable on this host")

    context = _sandbox_context(tmp_path)
    marker = tmp_path / "sandbox-write-probe"
    probe_script = (
        f"touch {marker} 2>/dev/null && echo WRITE_OK || echo WRITE_BLOCKED; "
        "curl -fsS --max-time 2 https://example.com >/dev/null 2>&1 "
        "&& echo NET_OK || echo NET_BLOCKED"
    )
    from mergecraft.analyzers.resolve import AnalyzerPlan

    plan = AnalyzerPlan(
        manifest_id="probe",
        argv=("bash", "-c", probe_script),
        cwd=tmp_path,
        mode="native",
    )
    argv, preexec = _sandboxed_argv(plan, context)
    completed = subprocess.run(
        argv,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        preexec_fn=preexec,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    assert "WRITE_BLOCKED" in output, output
    assert "NET_BLOCKED" in output, output
    assert not marker.exists()
