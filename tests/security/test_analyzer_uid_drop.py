"""In-image proof that the analyzer sandbox drops root identity (S11).

Runs only on the privileged Linux backend the action image provides: the
untrusted analyzer payload must be a non-root process that can write its scratch
and ``HOME``, cannot write a root-owned file outside the read-only checkout, and
never reaches UID 0 on the userspace-egress path (or fails closed with a named
reason). On any host without euid 0, Linux, ``unshare`` and ``setpriv`` the whole
module skips with the precondition reason.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

_ROOT_PRECONDITION_REASON = "requires euid 0, Linux, unshare and setpriv — runs in the action image"


def _preconditions_met() -> bool:
    if sys.platform != "linux" or os.geteuid() != 0:
        return False
    return shutil.which("unshare") is not None and shutil.which("setpriv") is not None


pytestmark = pytest.mark.skipif(not _preconditions_met(), reason=_ROOT_PRECONDITION_REASON)


def _make_traversable_for_dropped_uid(path: Path) -> None:
    """Add ``o+x`` to ``path`` and its ancestors so the dropped uid can traverse in.

    pytest's ``tmp_path`` lives under a root-owned ``0700`` base
    (``/tmp/pytest-of-<user>/pytest-<n>``), while the production analyzer
    workspace is traversable by the agent (``utils/privilege.prepare_workspace_for_agent``
    chowns it before the run). The sandbox correctly drops the payload to the
    agent uid; the fixture must then present a traversable parent chain or the
    payload cannot reach the ``1777`` tmpfs mounted at the scratch leaf. Grant
    traversal only — the leaf tmpfs stays world-writable and the real checkout
    stays unreadable. Stop at ``tempfile.gettempdir()`` and any ancestor that is
    already traversable by others.
    """
    stop = Path(tempfile.gettempdir()).resolve()
    current = path.resolve()
    while True:
        mode = current.stat().st_mode
        if mode & 0o001:
            break
        os.chmod(current, mode | 0o001)
        parent = current.parent
        if current == stop or parent == current:
            break
        current = parent


def _untrusted_context(tmp_path: Path) -> Any:
    from mergecraft.analyzers import sandbox as sandbox_mod

    scratch = tmp_path / "analyzer-scratch"
    _make_traversable_for_dropped_uid(tmp_path)
    plan = sandbox_mod.plan_sandbox(
        repo_root=tmp_path,
        scratch_dir=scratch,
        tier="untrusted",
    )
    assert plan.can_run, f"the untrusted sandbox must be available in the image: {plan.skip_reason}"
    assert plan.context is not None
    return plan.context


def _run_payload(tmp_path: Path, script: str, *, env: dict[str, str] | None = None) -> str:
    from mergecraft.analyzers.resolve import AnalyzerPlan
    from mergecraft.analyzers.run import _run_subprocess, _sandboxed_argv

    context = _untrusted_context(tmp_path)
    plan = AnalyzerPlan(
        manifest_id="uid-probe",
        argv=("bash", "-c", script),
        cwd=tmp_path,
        env=env if env is not None else {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
        mode="native",
    )
    argv, preexec = _sandboxed_argv(plan, context)
    result = _run_subprocess(
        argv,
        plan=plan,
        cwd=tmp_path,
        timeout_s=60,
        preexec_fn=preexec,
        command="uid-probe",
        sandboxed=True,
    )
    assert isinstance(result, subprocess.CompletedProcess), result
    return (result.stdout or "") + (result.stderr or "")


def test_analyzer_payload_runs_without_root_identity(tmp_path: Path) -> None:
    output = _run_payload(tmp_path, "id -u")
    uid_lines = [line.strip() for line in output.splitlines() if line.strip().isdigit()]
    assert uid_lines, output
    assert uid_lines[-1] != "0", output


def test_analyzer_payload_can_write_scratch_and_home(tmp_path: Path) -> None:
    context = _untrusted_context(tmp_path)
    scratch = context.scratch_dir
    output = _run_payload(
        tmp_path,
        f'touch "{scratch}/scratch-probe" && echo SCRATCH_OK || echo SCRATCH_DENIED; '
        'echo "HOME=$HOME"; '
        'touch "$HOME/.mergecraft-home-probe" && echo HOME_OK || echo HOME_DENIED',
    )
    assert "SCRATCH_OK" in output, output
    assert "HOME_OK" in output, output
    assert f"HOME={scratch}" in output or f"HOME={scratch.resolve()}" in output, output


def test_analyzer_payload_cannot_write_outside_scratch(tmp_path: Path) -> None:
    outside_dir = Path(tempfile.mkdtemp(dir="/tmp"))
    os.chmod(outside_dir, 0o755)
    try:
        outside = outside_dir / "root-owned.txt"
        outside.write_text("root-owned\n", encoding="utf-8")
        os.chmod(outside, 0o644)
        output = _run_payload(
            tmp_path,
            f'touch "{outside}" 2>/dev/null && echo OUTSIDE_WRITE_OK || echo OUTSIDE_WRITE_DENIED',
        )
        assert "OUTSIDE_WRITE_OK" not in output, output
        assert "OUTSIDE_WRITE_DENIED" in output, output
        assert outside.read_text(encoding="utf-8") == "root-owned\n"
    finally:
        shutil.rmtree(outside_dir, ignore_errors=True)


def test_userspace_egress_analysis_never_reaches_uid_zero(tmp_path: Path) -> None:
    """The bridge path either keeps a non-root payload or fails closed by name."""
    from mergecraft.analyzers.egress import FilteredEgressSetupError
    from mergecraft.analyzers.resolve import AnalyzerPlan
    from mergecraft.analyzers.run import _run_subprocess, _sandboxed_argv

    context = _untrusted_context(tmp_path)

    class _StubEgressSession:
        def wrap_argv(self, argv: list[str]) -> list[str]:
            return list(argv)

    plan = AnalyzerPlan(
        manifest_id="uid-probe",
        argv=("id", "-u"),
        cwd=tmp_path,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
        mode="native",
    )
    try:
        argv, preexec = _sandboxed_argv(
            plan,
            context,
            event_name="pull_request_target",
            event={"_uid_probe": True},
            egress_session=_StubEgressSession(),
        )
    except FilteredEgressSetupError as exc:
        if not str(exc).strip():
            pytest.fail("the F4 failure must carry a named reason")
        return

    result = _run_subprocess(
        argv,
        plan=plan,
        cwd=tmp_path,
        timeout_s=60,
        preexec_fn=preexec,
        command="id -u",
        sandboxed=True,
    )
    assert isinstance(result, subprocess.CompletedProcess), result
    output = (result.stdout or "") + (result.stderr or "")
    uid_lines = [line.strip() for line in output.splitlines() if line.strip().isdigit()]
    assert uid_lines, output
    assert uid_lines[-1] != "0", output
