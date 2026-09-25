"""Tests for the run_static_checks tool: availability reporting and shell gating."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers import sandbox as sandbox_mod
from mergecraft.mcp import shell as shell_mod
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import build_common_tools
from mergecraft.mcp.static_checks import run_static_checks_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.utils.github import GitHubClient


def _ctx(
    tmp_path: Path,
    *,
    shell: str = "restricted",
    static_checks: list[StaticCheckConfig] | None = None,
    enabled: bool = True,
) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell=shell,  # type: ignore[arg-type]
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        static_checks=static_checks or [],
        static_checks_enabled=enabled,
    )


async def _run(ctx: ToolContext, **params: Any) -> dict[str, Any]:
    result = await run_static_checks_tool(ctx).execute(params)
    return json.loads(result.content[0]["text"])


@pytest.mark.asyncio
async def test_reports_not_run_when_repo_declares_no_gate(tmp_path: Path) -> None:
    payload = await _run(_ctx(tmp_path))
    assert payload["ran"] is False
    assert "declares no mechanical gate" in payload["reason"]
    assert payload["checks"] == []


@pytest.mark.asyncio
async def test_reports_not_run_when_every_gate_is_unavailable(tmp_path: Path) -> None:
    """A repo can declare a gate this environment cannot run; that is not a finding."""
    ctx = _ctx(
        tmp_path,
        static_checks=[StaticCheckConfig(name="lint", command="mergecraft-no-such-binary")],
    )
    payload = await _run(ctx)
    assert payload["ran"] is False
    assert "unavailable" in payload["reason"]
    assert payload["checks"][0]["status"] == "unavailable"
    assert payload["checks"][0]["exitCode"] is None


@pytest.mark.asyncio
async def test_failing_gate_is_reported_as_ran_and_not_passed(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'raise SystemExit(1)'")],
    )
    payload = await _run(ctx)
    assert payload["ran"] is True
    assert payload["allPassed"] is False
    assert payload["checks"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_unavailable_gate_does_not_sink_a_passing_one(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        static_checks=[
            StaticCheckConfig(name="missing", command="mergecraft-no-such-binary"),
            StaticCheckConfig(name="ok", command="python -c 'pass'"),
        ],
    )
    payload = await _run(ctx)
    assert payload["ran"] is True
    assert payload["allPassed"] is True
    assert [c["status"] for c in payload["checks"]] == ["unavailable", "passed"]


def test_tool_is_withheld_when_static_checks_disabled(tmp_path: Path) -> None:
    """`shell: disabled` must not leave a path to running repo-declared commands."""
    names = {t.name for t in build_common_tools(_ctx(tmp_path, shell="disabled", enabled=False))}
    assert "run_static_checks" not in names
    names = {t.name for t in build_common_tools(_ctx(tmp_path, enabled=True))}
    assert "run_static_checks" in names


@pytest.mark.asyncio
async def test_static_checks_declared_but_cannot_run_when_shell_disabled(
    tmp_path: Path,
) -> None:
    """Configured staticChecks with shell disabled must report explicitly, not omit silently."""
    ctx = _ctx(
        tmp_path,
        shell="disabled",
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'pass'")],
        enabled=True,
    )
    ctx.trust_tier = "untrusted"
    payload = await _run(ctx)
    assert payload["ran"] is False
    reason = str(payload.get("reason", "")).lower()
    checks = payload.get("checks") or []
    status_values = {str(check.get("status", "")).lower() for check in checks}
    assert "declared but cannot run" in reason or "declared-but-cannot-run" in status_values
    assert checks, "configured gates must appear as explicit unavailable rows"


@pytest.mark.asyncio
async def test_static_checks_run_when_shell_disabled_but_trusted_offline(
    tmp_path: Path,
) -> None:
    """Offline diff-review keeps shell disabled for security but still runs declared gates."""
    ctx = _ctx(
        tmp_path,
        shell="disabled",
        static_checks=[StaticCheckConfig(name="lint", command="python -c 'pass'")],
        enabled=True,
    )
    ctx.trust_tier = "trusted"
    payload = await _run(ctx)
    assert payload["ran"] is True
    assert payload["allPassed"] is True
    assert payload["checks"][0]["status"] == "passed"


def _write_makefile(tmp_path: Path) -> None:
    """Give the repo a discoverable `lint` gate that succeeds when it runs."""
    (tmp_path / "Makefile").write_text("lint:\n\t@true\n", encoding="utf-8")


requires_make = pytest.mark.skipif(
    shutil.which("make") is None, reason="Makefile gate discovery requires `make` on PATH"
)


@requires_make
@pytest.mark.asyncio
async def test_discovered_makefile_gates_are_not_run_bare_when_shell_disabled(
    tmp_path: Path,
) -> None:
    """Undeclared repos fall back to Makefile gates; untrusted they never run bare.

    Under the untrusted-sandbox decision the shell-disabled withhold is replaced
    by a sandbox plan: a host with no isolation reports the gate as
    declared-but-cannot-run rather than executing PR-authored Makefile code.
    """
    _write_makefile(tmp_path)
    ctx = _ctx(tmp_path, shell="disabled", static_checks=[], enabled=True)
    ctx.trust_tier = "untrusted"
    payload = await _run(ctx)
    assert payload["ran"] is False
    checks = payload.get("checks") or []
    assert [check["status"] for check in checks] == ["declared-but-cannot-run"]
    assert checks[0]["name"] == "lint"


@requires_make
@pytest.mark.asyncio
async def test_discovered_makefile_gates_run_when_shell_disabled_but_trusted(
    tmp_path: Path,
) -> None:
    """The trusted carve-out is unchanged: offline review still runs discovered gates."""
    _write_makefile(tmp_path)
    ctx = _ctx(tmp_path, shell="disabled", static_checks=[], enabled=True)
    ctx.trust_tier = "trusted"
    payload = await _run(ctx)
    assert payload["ran"] is True
    assert payload["allPassed"] is True
    assert payload["checks"][0]["status"] == "passed"


@requires_make
@pytest.mark.asyncio
async def test_discovered_makefile_gates_run_under_permissive_shell(tmp_path: Path) -> None:
    """An untrusted event with shell available keeps running discovered gates."""
    _write_makefile(tmp_path)
    ctx = _ctx(tmp_path, shell="restricted", static_checks=[], enabled=True)
    ctx.trust_tier = "untrusted"
    payload = await _run(ctx)
    assert payload["ran"] is True
    assert payload["allPassed"] is True
    assert payload["checks"][0]["status"] == "passed"


@pytest.mark.asyncio
async def test_no_gate_at_all_keeps_early_return_when_shell_disabled(tmp_path: Path) -> None:
    """No declared and no discoverable gate: the untouched 'no mechanical gate' return."""
    ctx = _ctx(tmp_path, shell="disabled", static_checks=[], enabled=True)
    ctx.trust_tier = "untrusted"
    payload = await _run(ctx)
    assert payload["ran"] is False
    assert "declares no mechanical gate" in payload["reason"]
    assert payload["checks"] == []
    assert ctx.tool_state.static_checks_ran is True


# ---------------------------------------------------------------------------
# Untrusted gates run inside the untrusted sandbox (default-deny env, scratch
# home, isolated network), and sandbox-caused failures are classified rather
# than reported as findings about the diff.
# ---------------------------------------------------------------------------


def _full_caps() -> sandbox_mod.SandboxCapabilities:
    return sandbox_mod.SandboxCapabilities(
        pid_namespace=True,
        network_namespace=True,
        read_only_bind=True,
        tmpfs=True,
        cgroup_memory=False,
        rlimit_nproc=True,
        pid_namespace_method="unshare",
        user_namespace=True,
    )


def _force_untrusted_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", _full_caps)
    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "unshare")
    shell_mod._reset_shell_detection_globals()


def _capture_child(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, Any]:
    """Patch the child boundary and record what the gate would have received."""
    captured: dict[str, Any] = {"argv": [], "env": None, "payload_env": None}

    def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["argv"] = list(argv)
        captured["env"] = kwargs.get("env")
        descriptors = kwargs.get("pass_fds") or ()
        if descriptors:
            raw = os.read(descriptors[0], 65536).decode("utf-8", errors="replace")
            parsed: dict[str, str] = {}
            for entry in raw.split("\0"):
                if "=" in entry:
                    key, value = entry.split("=", 1)
                    parsed[key] = value
            captured["payload_env"] = parsed
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", _run)
    return captured


@pytest.mark.parametrize("shell", ["restricted", "disabled"])
@pytest.mark.asyncio
async def test_untrusted_gates_run_sandboxed_with_scratch_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: str
) -> None:
    _force_untrusted_sandbox(monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN", "static-checks-scm-canary")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "static-checks-provider-canary")
    captured = _capture_child(monkeypatch)

    ctx = _ctx(
        tmp_path,
        shell=shell,
        static_checks=[StaticCheckConfig(name="lint", command="gate")],
        enabled=True,
    )
    ctx.trust_tier = "untrusted"
    await _run(ctx)

    argv = captured["argv"]
    assert "unshare" in argv, argv
    assert "--net" in argv, argv
    payload_env = captured["payload_env"]
    assert isinstance(payload_env, dict), "the sandboxed gate must receive a payload env"
    assert "static-checks-scm-canary" not in payload_env
    assert "static-checks-provider-canary" not in payload_env
    for key in ("HOME", "XDG_CACHE_HOME", "TMPDIR"):
        value = payload_env.get(key)
        assert value, f"{key} must be pointed at scratch, got {value!r}"
        assert str(tmp_path) in value, f"{key}={value!r} is outside the run tmpdir"


@pytest.mark.parametrize(
    ("stderr", "reason"),
    [
        ("Could not resolve host: registry.npmjs.org", "sandboxed: network is disabled"),
        (
            "Temporary failure in name resolution",
            "sandboxed: network is disabled",
        ),
        ("EROFS: read-only file system", "sandboxed: path not writable"),
    ],
)
@pytest.mark.asyncio
async def test_sandbox_caused_gate_failure_is_declared_not_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stderr: str, reason: str
) -> None:
    _force_untrusted_sandbox(monkeypatch)
    _capture_child(monkeypatch, returncode=1, stderr=stderr)

    ctx = _ctx(
        tmp_path,
        static_checks=[StaticCheckConfig(name="lint", command="gate")],
        enabled=True,
    )
    ctx.trust_tier = "untrusted"
    payload = await _run(ctx)

    checks = payload["checks"]
    assert checks, payload
    assert checks[0]["status"] == "declared-but-cannot-run", payload
    assert checks[0]["status"] != "failed"
    assert reason in json.dumps(payload), payload


@pytest.mark.asyncio
async def test_real_gate_failure_is_still_the_gates_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_untrusted_sandbox(monkeypatch)
    _capture_child(
        monkeypatch,
        returncode=1,
        stderr="src/app.py:3:1: error: the network helper is unused (F401)",
    )

    ctx = _ctx(
        tmp_path,
        static_checks=[StaticCheckConfig(name="lint", command="gate")],
        enabled=True,
    )
    ctx.trust_tier = "untrusted"
    payload = await _run(ctx)

    checks = payload["checks"]
    assert checks[0]["status"] == "failed", payload
    assert checks[0]["exitCode"] == 1


@pytest.mark.asyncio
async def test_sandboxed_gate_write_never_reaches_the_real_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_untrusted_sandbox(monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    sandboxed_upper = tmp_path / "sandboxed-upper"
    sandboxed_upper.mkdir()

    def _fake_subprocess_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        # The write lands where the process actually is: a namespace-wrapped gate
        # writes the disposable upper layer, a bare gate corrupts the checkout.
        target = sandboxed_upper if "unshare" in argv else repo
        (target / "build-output.txt").write_text("built\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)
    ctx = _ctx(
        repo,
        static_checks=[StaticCheckConfig(name="lint", command="gate")],
        enabled=True,
    )
    ctx.trust_tier = "untrusted"
    payload = await _run(ctx)

    assert payload["checks"][0]["status"] == "passed", payload
    assert not (repo / "build-output.txt").exists(), "the real checkout was written"
    assert (sandboxed_upper / "build-output.txt").exists()


@pytest.mark.asyncio
async def test_trusted_tier_gate_still_runs_without_a_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_child(monkeypatch, returncode=0, stdout="ok")
    ctx = _ctx(
        tmp_path,
        static_checks=[StaticCheckConfig(name="lint", command="gate")],
        enabled=True,
    )
    ctx.trust_tier = "trusted"
    payload = await _run(ctx)

    assert "unshare" not in captured["argv"], captured["argv"]
    assert payload["checks"][0]["status"] == "passed", payload
