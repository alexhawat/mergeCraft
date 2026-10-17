"""Trusted-tier catalog analyzers drop to the agent UID and own their scratch (#878).

The non-root tests pin that the drop is *requested* and that scratch ownership is
handed to the drop target before the payload starts. The root-gated test proves it
end to end on the privileged Linux backend.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers import sandbox as sandbox_mod
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.analyzers.run import run_plan

_DROP_UID = 4242
_DROP_GID = 4343
_DROP_PREFIX = ["setpriv", "--no-new-privs", f"--reuid={_DROP_UID}", f"--regid={_DROP_GID}"]


def _trusted_context(tmp_path: Path) -> sandbox_mod.SandboxContext:
    scratch = tmp_path / ".mergecraft" / "analyzer-scratch" / "jscpd"
    scratch.mkdir(parents=True)
    (scratch / "home").mkdir()
    (scratch / "home" / "cache.db").write_text("x", encoding="utf-8")
    return sandbox_mod.SandboxContext(
        repo_root=tmp_path,
        scratch_dir=scratch,
        timeout_s=30,
        memory_mb=256,
        max_processes=8,
        read_only_source=False,
        source_mount_read_only=False,
        network_allowlist=[],
        network_default="deny",
    )


def _plan(tmp_path: Path, scratch: Path) -> AnalyzerPlan:
    return AnalyzerPlan(
        manifest_id="jscpd",
        argv=(sys.executable, "-c", "pass"),
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "HOME": "/github/home"},
        mode="repo-native",
    )


@pytest.fixture
def pretend_root(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {"chowned": [], "argv": None, "env": None}
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(sandbox_mod, "build_privilege_drop_argv", lambda **_kw: list(_DROP_PREFIX))
    monkeypatch.setattr(sandbox_mod, "resolve_drop_target_uid", lambda: _DROP_UID)
    monkeypatch.setattr(sandbox_mod, "resolve_drop_target_gid", lambda: _DROP_GID)

    def _record_chown(path: Any, uid: int, gid: int, *_a: Any, **_kw: Any) -> None:
        seen["chowned"].append((str(path), uid, gid))

    monkeypatch.setattr(os, "chown", _record_chown)
    monkeypatch.setattr(os, "lchown", _record_chown, raising=False)

    def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["argv"] = list(argv)
        seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _run)
    return seen


def test_trusted_catalog_analyzer_is_launched_behind_the_identity_drop(
    tmp_path: Path, pretend_root: dict[str, Any]
) -> None:
    context = _trusted_context(tmp_path)

    run_plan(_plan(tmp_path, context.scratch_dir), sandbox_context=context)

    argv = pretend_root["argv"]
    assert argv is not None
    assert argv[: len(_DROP_PREFIX)] == _DROP_PREFIX
    assert argv[len(_DROP_PREFIX) :] == [sys.executable, "-c", "pass"]


def test_scratch_tree_is_handed_to_the_drop_target_before_the_payload_runs(
    tmp_path: Path, pretend_root: dict[str, Any]
) -> None:
    context = _trusted_context(tmp_path)

    run_plan(_plan(tmp_path, context.scratch_dir), sandbox_context=context)

    owned = {
        path for path, uid, gid in pretend_root["chowned"] if (uid, gid) == (_DROP_UID, _DROP_GID)
    }
    assert str(context.scratch_dir) in owned
    assert str(context.scratch_dir / "home") in owned
    assert str(context.scratch_dir / "home" / "cache.db") in owned
    # The checkout itself is never re-owned by the analyzer runner.
    assert str(tmp_path) not in owned


def test_dropped_payload_gets_a_writable_home(tmp_path: Path, pretend_root: dict[str, Any]) -> None:
    context = _trusted_context(tmp_path)

    run_plan(_plan(tmp_path, context.scratch_dir), sandbox_context=context)

    env = pretend_root["env"]
    assert env is not None
    assert Path(env["HOME"]).is_relative_to(context.scratch_dir)


def test_symlinked_scratch_entries_are_never_followed_by_the_chown(
    tmp_path: Path, pretend_root: dict[str, Any]
) -> None:
    """A PR-planted symlink inside scratch must not re-own a path outside the checkout."""
    context = _trusted_context(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (context.scratch_dir / "escape").symlink_to(outside, target_is_directory=True)

    run_plan(_plan(tmp_path, context.scratch_dir), sandbox_context=context)

    touched = [path for path, _uid, _gid in pretend_root["chowned"]]
    assert not any(path.startswith(str(outside)) for path in touched)


def test_no_drop_is_requested_off_the_root_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _trusted_context(tmp_path)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    def _run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _run)

    run_plan(_plan(tmp_path, context.scratch_dir), sandbox_context=context)

    assert captured["argv"] == [sys.executable, "-c", "pass"]


def test_unlandable_drop_is_a_named_unavailable_not_a_root_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed: when the drop cannot land the analyzer does not run as root."""
    from mergecraft.main import _ConfigurationError

    context = _trusted_context(tmp_path)
    launched: list[list[str]] = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    def _cannot_drop(**_kw: Any) -> list[str]:
        msg = "setpriv is not on PATH"
        raise _ConfigurationError(msg)

    monkeypatch.setattr(sandbox_mod, "build_privilege_drop_argv", _cannot_drop)

    def _run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        launched.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _run)

    outcome = run_plan(_plan(tmp_path, context.scratch_dir), sandbox_context=context)

    assert launched == []
    assert outcome.status == "unavailable"
    assert "setpriv" in outcome.output


def test_static_check_runs_are_not_dropped_twice(
    tmp_path: Path, pretend_root: dict[str, Any]
) -> None:
    """Static gates build their own drop prefix and pass no sandbox context."""
    plan = AnalyzerPlan(
        manifest_id="lint",
        argv=(*_DROP_PREFIX, sys.executable, "-c", "pass"),
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        mode="repo-native",
    )

    run_plan(plan, sandbox_context=None)

    argv = pretend_root["argv"]
    assert argv.count("setpriv") == 1


_ROOT_REASON = "requires euid 0, Linux and setpriv — runs in the action image"
_ROOT_READY = (
    sys.platform == "linux" and os.geteuid() == 0 and shutil.which("setpriv") is not None
    if hasattr(os, "geteuid")
    else False
)


@pytest.mark.skipif(not _ROOT_READY, reason=_ROOT_REASON)
def test_root_backend_trusted_analyzer_payload_runs_unprivileged_and_writes_scratch(
    tmp_path: Path,
) -> None:
    """Root-gated: the payload is UID != 0 and can still write its (re-owned) scratch."""
    os.chmod(tmp_path, 0o755)
    context = _trusted_context(tmp_path)
    scratch = context.scratch_dir
    script = f'id -u > "{scratch}/uid.txt" && touch "{scratch}/home/probe" && echo WROTE'
    plan = AnalyzerPlan(
        manifest_id="jscpd",
        argv=("/bin/sh", "-c", script),
        cwd=tmp_path,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
        mode="repo-native",
    )

    outcome = run_plan(plan, sandbox_context=context)

    assert outcome.status == "passed", outcome.output
    assert "WROTE" in outcome.output
    assert (scratch / "uid.txt").read_text(encoding="utf-8").strip() != "0"


def test_base_worktree_is_handed_to_the_drop_target_on_the_root_backend(
    tmp_path: Path, pretend_root: dict[str, Any]
) -> None:
    """Baseline suppression runs analyzers on a root-owned ``mkdtemp`` checkout."""
    from mergecraft.analyzers.baseline_suppression import _hand_worktree_to_drop_target

    worktree = tmp_path / "base"
    (worktree / "src").mkdir(parents=True)
    (worktree / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

    _hand_worktree_to_drop_target(worktree)

    owned = {
        path for path, uid, gid in pretend_root["chowned"] if (uid, gid) == (_DROP_UID, _DROP_GID)
    }
    assert {str(worktree), str(worktree / "src"), str(worktree / "src" / "a.py")} <= owned


def test_base_worktree_is_untouched_off_the_root_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.analyzers.baseline_suppression import _hand_worktree_to_drop_target

    calls: list[str] = []
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr(os, "lchown", lambda path, *_a: calls.append(str(path)), raising=False)

    _hand_worktree_to_drop_target(tmp_path)

    assert calls == []
