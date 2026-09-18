"""Plan 26 H2 — Darwin skip, fail-closed ``--shell enabled``, honest context, sandbox-exec.

Contracts: plan decisions 1-4. H2 xfails removed after the impl landed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mergecraft.analyzers import sandbox as sandbox_mod
from mergecraft.mcp import shell as shell_mod
from mergecraft.mcp.tool_state import AnalyzerRunState
from mergecraft.review.offline_stages import run_offline_analyze
from mergecraft.utils.offline_diff import DiffMaterialization

_OVERRIDE = "MERGECRAFT_ALLOW_UNSANDBOXED_SHELL"
_PATCH = "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ a/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"


def _empty_caps() -> sandbox_mod.SandboxCapabilities:
    return sandbox_mod.SandboxCapabilities(
        pid_namespace=False,
        network_namespace=False,
        read_only_bind=False,
        tmpfs=False,
        cgroup_memory=False,
        rlimit_nproc=True,
        pid_namespace_method="none",
    )


def _force_no_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox_mod, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", _empty_caps)
    # Stand-in is not lru_cache; do not require a real cache_clear.
    monkeypatch.setattr(sandbox_mod.probe_capabilities, "cache_clear", lambda: None, raising=False)
    monkeypatch.setattr(shell_mod, "_detected_sandbox", None)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "none")
    monkeypatch.delenv(_OVERRIDE, raising=False)


def _materialization(tmp_path: Path) -> DiffMaterialization:
    diff_path = tmp_path / "change.diff"
    diff_path.write_text(_PATCH, encoding="utf-8")
    return DiffMaterialization(
        path=diff_path,
        base_ref="HEAD",
        line_count=_PATCH.count("\n"),
        empty=False,
    )


@pytest.fixture(autouse=True)
def _clear_probe_cache() -> None:
    sandbox_mod.probe_capabilities.cache_clear()
    shell_mod.reset_detection_cache()


def test_darwin_does_not_run_linux_isolation_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 1 — Darwin is detected up front; the Linux unshare/mount probe never runs."""
    monkeypatch.setattr(sandbox_mod, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.delenv("MERGECRAFT_PROBE_TEST_DOUBLE", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    def _fail_run(*_a: object, **_k: object) -> None:
        pytest.fail("Linux isolation probe launched on Darwin")

    monkeypatch.setattr(sandbox_mod.subprocess, "run", _fail_run)
    caps = sandbox_mod.probe_capabilities()
    joined = "; ".join(caps.unavailable_reasons)
    assert not caps.pid_namespace
    assert "local CLI" in joined
    assert "Action container" not in joined
    assert "unshare failed" not in joined
    assert "unshare --net failed" not in joined


def test_enabled_shell_refuses_without_backend_and_names_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 2 — fail closed; the refusal names the override; override is not the default."""
    _force_no_backend(monkeypatch)
    with pytest.raises((RuntimeError, PermissionError)) as excinfo:
        sandbox_mod.require_sandbox_for_enabled_shell(shell="enabled")
    message = str(excinfo.value)
    assert _OVERRIDE in message
    assert "1" in message


@pytest.mark.parametrize("value", ["", "0", "false", "yes", "true"])
def test_enabled_shell_override_is_only_the_literal_one(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Guard deletion — any value other than the literal ``1`` must still refuse."""
    _force_no_backend(monkeypatch)
    monkeypatch.setenv(_OVERRIDE, value)
    with pytest.raises((RuntimeError, PermissionError), match=_OVERRIDE):
        sandbox_mod.require_sandbox_for_enabled_shell(shell="enabled")


def test_enabled_shell_override_allows_proceed(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_no_backend(monkeypatch)
    monkeypatch.setenv(_OVERRIDE, "1")
    sandbox_mod.require_sandbox_for_enabled_shell(shell="enabled")


@pytest.mark.parametrize("shell", ["disabled", "restricted"])
def test_non_enabled_shell_does_not_require_a_backend(
    monkeypatch: pytest.MonkeyPatch, shell: str
) -> None:
    _force_no_backend(monkeypatch)
    sandbox_mod.require_sandbox_for_enabled_shell(shell=shell)


def test_enabled_shell_proceeds_when_sandbox_exec_backend_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_OVERRIDE, raising=False)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "sandbox-exec")
    monkeypatch.setattr(shell_mod, "_detected_sandbox", "sandbox-exec")
    sandbox_mod.require_sandbox_for_enabled_shell(shell="enabled")


def test_trusted_darwin_analyzer_argv_is_not_wrapped_by_sandbox_exec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """sandbox-exec satisfies the gate and wraps MCP shell; trusted analyzers stay bare.

    Wrapping would apply ``(deny network*)`` to tools that declare egress.
    Untrusted analyzers still skip via ``plan_sandbox``.
    """
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "sandbox-exec")
    context = sandbox_mod.build_sandbox_context(
        repo_root=tmp_path,
        scratch_dir=tmp_path / "scratch",
        limits=sandbox_mod.SandboxLimits(timeout_s=60, memory_mb=512, max_processes=16),
        network_allowlist=[],
        read_only_source=False,
    )
    argv = sandbox_mod.build_analyzer_sandbox_argv(("ruff", "check", "."), context=context)
    assert argv == ["ruff", "check", "."]
    assert argv[0] != "sandbox-exec"


async def test_offline_analyze_enabled_shell_does_not_start_pipeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--shell enabled`` with no backend must not reach the analyzer pipeline."""
    _force_no_backend(monkeypatch)
    called: list[dict[str, Any]] = []

    def _pipeline(**kwargs: object) -> AnalyzerRunState:
        called.append(dict(kwargs))
        return AnalyzerRunState(ran=True, reason=None)

    monkeypatch.setattr(
        "mergecraft.review.offline_stages.run_analyzer_pipeline",
        _pipeline,
    )
    raised: BaseException | None = None
    state: AnalyzerRunState | None = None
    try:
        state = await run_offline_analyze(
            cwd=tmp_path,
            materialization=_materialization(tmp_path),
            trust_tier="trusted",
            shell="enabled",
            analyzers_enabled=True,
        )
    except (RuntimeError, PermissionError) as exc:
        raised = exc
    assert called == [], "fail-closed gate must run before the analyzer pipeline"
    if raised is not None:
        assert _OVERRIDE in str(raised)
        return
    assert state is not None
    assert state.ran is False
    assert state.reason is not None
    assert _OVERRIDE in state.reason


def test_sandbox_execution_context_names_local_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 3 — a local CLI run names itself, not an Action container."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(sandbox_mod, "_probe_cgroup_memory", lambda: (False, "unused"))
    assert sandbox_mod.sandbox_execution_context() == "local CLI"


def test_sandbox_execution_context_names_action_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(sandbox_mod, "_probe_cgroup_memory", lambda: (True, None))
    assert sandbox_mod.sandbox_execution_context() == "Action container"


def test_sandbox_execution_context_names_container_without_cgroups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(sandbox_mod, "_probe_cgroup_memory", lambda: (False, "no cgroup"))
    assert sandbox_mod.sandbox_execution_context() == "container-without-cgroups"


def test_probe_reasons_include_the_named_execution_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox_mod, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("MERGECRAFT_PROBE_TEST_DOUBLE", raising=False)
    monkeypatch.setattr(
        sandbox_mod.subprocess, "run", lambda *_a, **_k: pytest.fail("Linux probe launched")
    )
    caps = sandbox_mod.probe_capabilities()
    joined = "; ".join(caps.unavailable_reasons)
    assert "local CLI" in joined
    assert "Action container" not in joined
    assert "container-without-cgroups" not in joined


def test_detect_sandbox_method_returns_sandbox_exec_on_darwin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 4 — Darwin with ``sandbox-exec`` on PATH is a real backend."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sandbox_mod, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(shell_mod, "sys", SimpleNamespace(platform="darwin"), raising=False)
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", _empty_caps)
    monkeypatch.setattr(shell_mod, "_detected_sandbox", None)
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name, *a, **k: "/usr/bin/sandbox-exec" if name == "sandbox-exec" else None,
    )
    assert shell_mod.detect_sandbox_method() == "sandbox-exec"


def test_detect_sandbox_method_is_none_when_sandbox_exec_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sandbox_mod, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(shell_mod, "sys", SimpleNamespace(platform="darwin"), raising=False)
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", _empty_caps)
    monkeypatch.setattr(shell_mod, "_detected_sandbox", None)
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    assert shell_mod.detect_sandbox_method() == "none"


def test_sandbox_exec_policy_denies_network_and_writes_outside_workspace(
    tmp_path: Path,
) -> None:
    """Decision 4 — policy: read-only outside the workspace; network denied."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    policy = sandbox_mod.sandbox_exec_policy(workspace=workspace)
    lowered = policy.casefold()
    assert "network" in lowered
    assert "deny" in lowered
    assert str(workspace) in policy
    assert "file-write" in lowered or "file-write*" in lowered
    git_dir = str(workspace / ".git")
    assert git_dir in policy
    assert "(deny file-write*" in policy
    assert "(deny process-exec*" in policy
    assert "git$" in policy or "/git" in policy


def test_build_sandbox_exec_argv_invokes_sandbox_exec(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    argv = sandbox_mod.build_sandbox_exec_argv(("echo", "ok"), workspace=workspace)
    assert argv[0] == "sandbox-exec"
    assert "echo" in argv
    assert "ok" in argv


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is a Darwin backend")
@pytest.mark.skipif(shutil.which("sandbox-exec") is None, reason="sandbox-exec not on PATH")
def test_sandbox_exec_blocks_write_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside-write.txt"
    argv = sandbox_mod.build_sandbox_exec_argv(
        ("/bin/bash", "-c", f"echo leaked > {outside}"),
        workspace=workspace,
    )
    completed = subprocess.run(argv, cwd=workspace, capture_output=True, check=False, timeout=10)
    assert completed.returncode != 0
    assert not outside.exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is a Darwin backend")
@pytest.mark.skipif(shutil.which("sandbox-exec") is None, reason="sandbox-exec not on PATH")
def test_sandbox_exec_blocks_network(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    argv = sandbox_mod.build_sandbox_exec_argv(
        (
            "/usr/bin/python3",
            "-c",
            "import socket; socket.create_connection(('1.1.1.1', 80), 1)",
        ),
        workspace=workspace,
    )
    completed = subprocess.run(argv, cwd=workspace, capture_output=True, check=False, timeout=10)
    assert completed.returncode != 0


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is a Darwin backend")
@pytest.mark.skipif(shutil.which("sandbox-exec") is None, reason="sandbox-exec not on PATH")
def test_sandbox_exec_allows_write_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    inside = workspace / "ok.txt"
    argv = sandbox_mod.build_sandbox_exec_argv(
        ("/bin/bash", "-c", f"echo ok > {inside}"),
        workspace=workspace,
    )
    completed = subprocess.run(argv, cwd=workspace, capture_output=True, check=False, timeout=10)
    assert completed.returncode == 0
    assert inside.read_text(encoding="utf-8") == "ok\n"


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is a Darwin backend")
@pytest.mark.skipif(shutil.which("sandbox-exec") is None, reason="sandbox-exec not on PATH")
def test_sandbox_exec_blocks_write_inside_git_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    git_dir = workspace / ".git"
    git_dir.mkdir(parents=True)
    target = git_dir / "evil"
    argv = sandbox_mod.build_sandbox_exec_argv(
        ("/bin/bash", "-c", f"echo leaked > {target}"),
        workspace=workspace,
    )
    completed = subprocess.run(argv, cwd=workspace, capture_output=True, check=False, timeout=10)
    assert completed.returncode != 0
    assert not target.exists()


def test_spawn_shell_sandbox_exec_passes_git_deny_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "sandbox-exec")
    captured: list[str] = []

    def _popen(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        captured.extend(argv)
        return SimpleNamespace(pid=1)

    monkeypatch.setattr(shell_mod.subprocess, "Popen", _popen)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    shell_mod._spawn_shell(
        "echo ok",
        env={},
        cwd=str(workspace),
        stdout=None,
        stderr=None,
    )
    assert captured[0] == "sandbox-exec"
    policy = captured[captured.index("-p") + 1]
    assert str(workspace / ".git") in policy
    assert "(deny file-write*" in policy
