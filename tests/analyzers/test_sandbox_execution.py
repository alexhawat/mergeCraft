"""Lane A — analyzer sandbox execution must enforce probed capabilities (D6)."""

from __future__ import annotations

import shutil
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
    assert "--kill-child=KILL" in argv
    assert "remount,bind,ro" in joined
    assert "tmpfs" in joined
    assert str(tmp_path) in joined
    assert "bash" in argv
    assert (
        "exec setpriv --bounding-set=-all --inh-caps=-all --ambient-caps=-all --no-new-privs -- /bin/bash --noprofile --norc"
        in joined
    )
    assert "echo probe" in joined


def test_untrusted_sudo_backend_refuses_private_fd_loss(
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
    from mergecraft.analyzers.egress import FilteredEgressSetupError

    with pytest.raises(FilteredEgressSetupError, match="sudo closes private environment"):
        _sandboxed_argv(plan, _sandbox_context(tmp_path))


@pytest.mark.skipif(sys.platform != "linux", reason="namespace mounts require Linux")
def test_sandboxed_execution_blocks_repo_write_and_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caps = sandbox_mod.probe_capabilities()
    if not caps.pid_namespace or caps.pid_namespace_method != "unshare":
        pytest.skip("direct unshare unavailable; sudo cannot carry the private payload environment")

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    context = build_sandbox_context(
        repo_root=tmp_path,
        scratch_dir=scratch,
        limits=SandboxLimits(timeout_s=30, memory_mb=256, max_processes=8),
        network_allowlist=[],
        read_only_source=True,
        caps=caps,
    )
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
    from mergecraft.analyzers.run import _run_subprocess

    completed = _run_subprocess(
        argv,
        plan=plan,
        cwd=tmp_path,
        timeout_s=15,
        preexec_fn=preexec,
        command="probe",
        sandboxed=True,
    )
    assert isinstance(completed, subprocess.CompletedProcess)
    output = (completed.stdout or "") + (completed.stderr or "")
    assert "WRITE_BLOCKED" in output, output
    assert "NET_BLOCKED" in output, output
    assert not marker.exists()


def test_untrusted_backend_disagreement_never_launches_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.analyzers.resolve import AnalyzerPlan
    from mergecraft.analyzers.run import run_plan

    monkeypatch.setattr(sandbox_mod, "probe_capabilities", _full_caps)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "none")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("bare untrusted command launched")
    )
    plan = AnalyzerPlan(manifest_id="probe", argv=("touch", "escaped"), cwd=tmp_path, mode="native")
    result = run_plan(
        plan, sandbox_context=_sandbox_context(tmp_path), event_name="pull_request_target", event={}
    )
    assert result.status == "unavailable"
    assert "namespace backend" in result.output


def test_privileged_bootstrap_never_inherits_payload_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.analyzers.resolve import AnalyzerPlan
    from mergecraft.analyzers.run import _run_subprocess

    plan = AnalyzerPlan(
        manifest_id="probe",
        argv=("true",),
        cwd=tmp_path,
        mode="native",
        env={
            "PATH": "/repo/bin",
            "BASH_ENV": "/repo/startup",
            "LD_PRELOAD": "/repo/loader.so",
            "ENV": "/repo/env",
        },
    )
    captured: dict[str, object] = {}

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    _run_subprocess(
        ["unshare", "true"],
        plan=plan,
        cwd=tmp_path,
        timeout_s=1,
        preexec_fn=None,
        command="true",
        sandboxed=True,
    )
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert "MERGECRAFT_PAYLOAD_ENV_FD" in environment
    environment.pop("MERGECRAFT_PAYLOAD_ENV_FD")
    assert environment == {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"}


def test_payload_environment_values_use_private_fd_not_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from mergecraft.analyzers.resolve import AnalyzerPlan
    from mergecraft.analyzers.run import _run_subprocess

    secret = "fake-secret-with-spaces $() = value"
    plan = AnalyzerPlan(
        manifest_id="probe", argv=("true",), cwd=tmp_path, mode="native", env={"OPAQUE": secret}
    )
    observed: list[int] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert secret not in repr(argv)
        assert secret not in repr(kwargs["env"])
        descriptors = kwargs["pass_fds"]
        assert isinstance(descriptors, tuple)
        descriptor = descriptors[0]
        observed.append(descriptor)
        assert os.read(descriptor, 8192) == f"OPAQUE={secret}\0".encode()
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    _run_subprocess(
        ["true"],
        plan=plan,
        cwd=tmp_path,
        timeout_s=1,
        preexec_fn=None,
        command="true",
        sandboxed=True,
    )
    with pytest.raises(OSError, match=r"[Bb]ad file descriptor"):
        os.fstat(observed[0])


def test_payload_environment_restore_is_literal_and_private(tmp_path: Path) -> None:
    import hashlib

    from mergecraft.analyzers.resolve import AnalyzerPlan
    from mergecraft.analyzers.run import _RESTORE_PAYLOAD_ENV, _run_subprocess

    secret = f"literal\n$(touch {tmp_path / 'must-not-run'})=value"
    digest = hashlib.sha256(secret.encode()).hexdigest()
    script = "import hashlib,os,sys; assert hashlib.sha256(os.environ['OPAQUE'].encode()).hexdigest() == sys.argv[1]; assert 'MERGECRAFT_PAYLOAD_ENV_FD' not in os.environ"
    argv = [
        shutil.which("bash") or "/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
        _RESTORE_PAYLOAD_ENV,
        "probe",
        sys.executable,
        "-c",
        script,
        digest,
    ]
    assert secret not in repr(argv)
    plan = AnalyzerPlan(
        manifest_id="probe", argv=("true",), cwd=tmp_path, mode="native", env={"OPAQUE": secret}
    )
    result = _run_subprocess(
        argv,
        plan=plan,
        cwd=tmp_path,
        timeout_s=10,
        preexec_fn=None,
        command="probe",
        sandboxed=True,
    )
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "must-not-run").exists()
