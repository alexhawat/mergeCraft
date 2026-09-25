"""An empty ``plan.env`` must resolve to a default-deny environment, not inheritance.

No analyzer execution path may hand a subprocess ``os.environ``: the bare
branch (``environment = plan.env or None``) and the sandboxed payload branch
(``payload_env = plan.env or dict(os.environ)``) both silently inherited the
orchestrator's full environment when a caller passed an empty mapping. Both are
pinned here by planting a canary in ``os.environ`` and observing what the child
would receive.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.analyzers import sandbox as sandbox_mod
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.analyzers.run import run_plan
from mergecraft.mcp import shell as shell_mod

if TYPE_CHECKING:
    import pytest

_CANARY_NAME = "MERGECRAFT_RUN_ENV_CANARY"
_CANARY_VALUE = "run-env-inherited-canary"


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


def _sandbox_context(tmp_path: Path) -> sandbox_mod.SandboxContext:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return sandbox_mod.build_sandbox_context(
        repo_root=tmp_path,
        scratch_dir=scratch,
        limits=sandbox_mod.SandboxLimits(timeout_s=30, memory_mb=256, max_processes=8),
        network_allowlist=[],
        read_only_source=True,
        caps=_full_caps(),
    )


def test_bare_run_plan_with_empty_env_does_not_inherit_os_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_CANARY_NAME, _CANARY_VALUE)
    captured: dict[str, object] = {}

    def _run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _run)
    plan = AnalyzerPlan(
        manifest_id="probe",
        argv=(sys.executable, "-c", "pass"),
        cwd=tmp_path,
        mode="repo-native",
    )

    run_plan(plan)

    environment = captured.get("env")
    assert environment is not None, (
        "an empty plan.env fell back to env=None, which inherits os.environ"
    )
    assert isinstance(environment, dict)
    assert _CANARY_NAME not in environment, (
        "an empty plan.env inherited os.environ into the bare gate"
    )


def test_sandboxed_run_plan_with_empty_env_does_not_inherit_os_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_CANARY_NAME, _CANARY_VALUE)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", _full_caps)
    shell_mod._reset_shell_detection_globals()

    captured: dict[str, object] = {}

    def _run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        descriptors = kwargs.get("pass_fds") or ()
        if descriptors:
            captured["payload"] = os.read(descriptors[0], 65536).decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _run)
    plan = AnalyzerPlan(manifest_id="probe", argv=("true",), cwd=tmp_path, mode="native")

    run_plan(plan, sandbox_context=_sandbox_context(tmp_path))

    descriptors = captured.get("pass_fds")
    assert isinstance(descriptors, tuple), (
        "the sandboxed payload environment must ride the private descriptor"
    )
    assert descriptors, "the sandboxed payload environment must ride the private descriptor"
    payload = captured.get("payload")
    assert isinstance(payload, str), payload
    assert _CANARY_NAME not in payload, (
        "an empty plan.env inherited os.environ into the sandboxed payload"
    )
