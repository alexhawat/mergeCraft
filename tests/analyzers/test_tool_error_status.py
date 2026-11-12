"""A run that exits non-zero without one parsed diagnostic is a ``tool-error``.

Outcomes are built through the real ``run._outcome_from_completed`` seam, so the
stdout-or-stderr parse surface and the persisted output are the production ones;
only the subprocess itself is replaced by a ``CompletedProcess``.
"""

from __future__ import annotations

import shlex
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers import adapters as adapters_mod
from mergecraft.analyzers import contracts as contracts_mod
from mergecraft.analyzers import execution as execution_mod
from mergecraft.analyzers.adapters import run_adapter
from mergecraft.analyzers.registry import get_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.analyzers.run import AnalyzerOutcome, _outcome_from_completed
from tests.analyzers.support import C4_CONTRACT_TOOLS

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_VERSION_NOTE = "ran mergeCraft's pinned tool; your repo pins none"

_MYPY_CRASH = (
    "Traceback (most recent call last):\n"
    '  File "mypy/main.py", line 12, in main\n'
    "mypy: error: INTERNAL ERROR -- Please try using mypy master on GitHub\n"
)
_MYPY_UNREADABLE = "mypy: can't read file 'src/x.py': No such file or directory"
_VULTURE_CRASH = "Traceback (most recent call last):\nSyntaxError: invalid syntax"
_BUF_BUILD_ERROR = 'proto/user/v1/user.proto:3:8:import "b.proto": file does not exist'


def _outcome(plan: AnalyzerPlan, *, returncode: int, stdout: str = "", stderr: str = "") -> Any:
    completed = subprocess.CompletedProcess(
        args=list(plan.argv), returncode=returncode, stdout=stdout, stderr=stderr
    )
    return _outcome_from_completed(completed, plan=plan, command=" ".join(plan.argv))


def _stub_adapter_chain(
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan: AnalyzerPlan,
    outcome: AnalyzerOutcome,
) -> None:
    """Stub everything between manifest resolution and ``run_plan`` in ``run_adapter``."""
    monkeypatch.setattr(adapters_mod, "resolve_analyzer", lambda **_kwargs: plan)
    monkeypatch.setattr(adapters_mod, "provision_managed_argv", lambda _plan, **_kwargs: plan)
    monkeypatch.setattr(
        adapters_mod,
        "plan_sandbox",
        lambda **_kwargs: SimpleNamespace(can_run=True, skip_reason=None, context=None),
    )
    monkeypatch.setattr(adapters_mod, "finalize_plan", lambda _plan, **_kwargs: plan)
    monkeypatch.setattr(adapters_mod, "run_plan", lambda _plan, **_kwargs: outcome)


def _plan(tool_id: str, tmp_path: Path) -> AnalyzerPlan:
    return AnalyzerPlan(
        manifest_id=tool_id,
        mode="repo-native",
        argv=(tool_id, "src/app.py"),
        cwd=tmp_path,
        version_note=_VERSION_NOTE,
    )


@pytest.mark.parametrize(
    ("tool_id", "returncode", "stdout", "stderr"),
    [
        ("mypy", 2, "", _MYPY_CRASH),
        ("mypy", 2, _MYPY_UNREADABLE, ""),
        ("vulture", 1, "", _VULTURE_CRASH),
        ("mypy", 2, "", ""),
    ],
    ids=["mypy-traceback", "mypy-unreadable-file", "vulture-traceback", "mypy-silent-exit-2"],
)
def test_crash_output_is_a_tool_error_not_a_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_id: str,
    returncode: int,
    stdout: str,
    stderr: str,
) -> None:
    plan = _plan(tool_id, tmp_path)
    _stub_adapter_chain(
        monkeypatch,
        plan=plan,
        outcome=_outcome(plan, returncode=returncode, stdout=stdout, stderr=stderr),
    )

    result = run_adapter(
        tool_id=tool_id, repo_root=tmp_path, changed_files=["src/app.py"], tier="trusted"
    )

    assert result.tool_error is True
    assert result.skipped is True
    assert result.findings == []
    reason = result.skip_reason or ""
    assert reason.startswith(f"tool-error {tool_id}: analyzer exited {returncode}")
    # The reason never carries the tool's own bytes.
    assert "Traceback" not in reason
    assert "src/x.py" not in reason


def test_nonzero_exit_with_diagnostics_is_still_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan("mypy", tmp_path)
    row = (
        '{"file": "src/app.py", "line": 3, "column": 1, "message": "bad", '
        '"code": "arg-type", "severity": "error"}'
    )
    _stub_adapter_chain(monkeypatch, plan=plan, outcome=_outcome(plan, returncode=1, stdout=row))

    result = run_adapter(
        tool_id="mypy", repo_root=tmp_path, changed_files=["src/app.py"], tier="trusted"
    )

    assert result.tool_error is False
    assert result.skipped is False
    assert [finding.rule_id for finding in result.findings] == ["arg-type"]


def test_clean_exit_zero_is_still_a_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan("vulture", tmp_path)
    _stub_adapter_chain(monkeypatch, plan=plan, outcome=_outcome(plan, returncode=0))

    result = run_adapter(
        tool_id="vulture", repo_root=tmp_path, changed_files=["src/app.py"], tier="trusted"
    )

    assert result.skipped is False
    assert result.tool_error is False
    assert result.findings == []


def test_pipeline_reports_tool_error_status_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.analyzers import pipeline

    plan = _plan("mypy", tmp_path)
    _stub_adapter_chain(
        monkeypatch, plan=plan, outcome=_outcome(plan, returncode=2, stderr=_MYPY_CRASH)
    )
    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_: [get_manifest("mypy")])

    state = pipeline.run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=["src/app.py"],
        tier="trusted",
        shell="restricted",
    )

    rows = {row.id: row for row in state.analyzers}
    assert rows["mypy"].status == "tool-error"
    assert "exited 2" in (rows["mypy"].reason or "")
    assert state.ran is False
    assert "tool-error" in (state.reason or "")
    assert "skipped in this environment" not in (state.reason or "")
    assert "1 tool errors (mypy: tool-error mypy" in (state.pre_merge_summary or "")


# --------------------------------------------------------------------------- contracts


def _stub_contract_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    tool_id: str,
    outcomes: list[Callable[[AnalyzerPlan], AnalyzerOutcome]],
) -> None:
    """Stub provisioning/sandboxing; ``execution.run_argv_result`` itself runs for real."""
    plan = AnalyzerPlan(
        manifest_id=tool_id,
        mode="managed",
        argv=(tool_id,),
        cwd=tmp_path,
        version_note=_VERSION_NOTE,
    )
    pending = list(outcomes)
    monkeypatch.setattr(contracts_mod, "resolve_analyzer", lambda **_kwargs: plan)
    monkeypatch.setattr(contracts_mod, "provision_resolved_plan", lambda p, **_kwargs: p)
    monkeypatch.setattr(execution_mod, "resolve_analyzer", lambda **_kwargs: plan)
    monkeypatch.setattr(execution_mod, "provision_resolved_plan", lambda p, **_kwargs: p)
    monkeypatch.setattr(execution_mod, "finalize_plan", lambda p, **_kwargs: p)
    monkeypatch.setattr(
        execution_mod,
        "plan_sandbox",
        lambda **_kwargs: SimpleNamespace(can_run=True, skip_reason=None, context=None),
    )
    monkeypatch.setattr(
        execution_mod, "run_plan", lambda p, **_kwargs: pending.pop(0)(p) if pending else None
    )


def _contract(tool_id: str, repo_root: Path) -> Any:
    return contracts_mod.run_differential_adapter(
        tool_id=tool_id,
        repo_root=repo_root,
        changed_files=[C4_CONTRACT_TOOLS[tool_id]],
        base_ref="fixture-base",
        tier="trusted",
    )


def test_clean_contract_run_never_parses_the_version_note(
    adapter_fixture_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 0 with both streams empty: oasdiff found nothing, which is a pass."""
    _stub_contract_chain(
        monkeypatch,
        adapter_fixture_repo,
        tool_id="oasdiff",
        outcomes=[lambda plan: _outcome(plan, returncode=0)],
    )

    result = _contract("oasdiff", adapter_fixture_repo)

    assert result.skipped is False, result.skip_reason
    assert result.findings == []


@pytest.mark.parametrize(
    ("tool_id", "stdout", "stderr"),
    [
        ("oasdiff", "", "Error: failed to load base spec"),
        ("squawk", "", "error: could not parse migration"),
        ("buf", "", _BUF_BUILD_ERROR),
    ],
    ids=["oasdiff-load-error", "squawk-parse-error", "buf-build-error"],
)
def test_contract_tool_failure_is_a_tool_error(
    adapter_fixture_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_id: str,
    stdout: str,
    stderr: str,
) -> None:
    _stub_contract_chain(
        monkeypatch,
        adapter_fixture_repo,
        tool_id=tool_id,
        outcomes=[lambda plan: _outcome(plan, returncode=100, stdout=stdout, stderr=stderr)],
    )

    result = _contract(tool_id, adapter_fixture_repo)

    assert result.tool_error is True, result.skip_reason
    assert result.skipped is True
    assert (result.skip_reason or "").startswith(f"tool-error {tool_id}: analyzer exited 100")


def test_buf_breaking_rows_with_nonzero_exit_are_findings(
    adapter_fixture_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """buf exits 100 when it reports annotations; JSON rows mean the comparison ran."""
    row = (
        '{"path": "proto/user/v1/user.proto", "start_line": 5, "type": "FIELD_NO_DELETE", '
        '"message": "Previously present field \\"2\\" with name \\"email\\" was deleted."}'
    )
    _stub_contract_chain(
        monkeypatch,
        adapter_fixture_repo,
        tool_id="buf",
        outcomes=[
            lambda plan: _outcome(plan, returncode=100, stdout=row),
            lambda plan: _outcome(plan, returncode=0),
        ],
    )

    result = _contract("buf", adapter_fixture_repo)

    assert result.skipped is False, result.skip_reason
    assert [finding.rule_id for finding in result.findings] == ["FIELD_NO_DELETE"]


def test_run_argv_result_returns_empty_raw_and_exit_code_for_a_silent_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_contract_chain(
        monkeypatch,
        tmp_path,
        tool_id="oasdiff",
        outcomes=[lambda plan: _outcome(plan, returncode=0)],
    )

    run = execution_mod.run_argv_result(
        manifest=get_manifest("oasdiff"),
        repo_root=tmp_path,
        argv=("oasdiff", "breaking"),
        changed_files=[],
        tier="trusted",
    )

    assert run.raw == ""
    assert run.exit_code == 0
    assert run.reason is None


# --------------------------------------------------------------------------- benign exits


def _fake_binary(tmp_path: Path, *, exit_code: int, stderr: str) -> str:
    """A real executable that writes ``stderr`` and exits ``exit_code``."""
    script = tmp_path / f"fake-tool-{exit_code}"
    script.write_text(
        f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(stderr)} >&2\nexit {exit_code}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return str(script)


def _stub_to_real_run_plan(monkeypatch: pytest.MonkeyPatch, plan: AnalyzerPlan) -> None:
    """Stub resolution/sandboxing only; the real ``run_plan`` spawns ``plan.argv``."""
    monkeypatch.setattr(adapters_mod, "resolve_analyzer", lambda **_kwargs: plan)
    monkeypatch.setattr(adapters_mod, "provision_managed_argv", lambda _plan, **_kwargs: plan)
    monkeypatch.setattr(
        adapters_mod,
        "plan_sandbox",
        lambda **_kwargs: SimpleNamespace(can_run=True, skip_reason=None, context=None),
    )
    monkeypatch.setattr(adapters_mod, "finalize_plan", lambda _plan, **_kwargs: plan)


_CHANGED = {"mypy": ["src/app.py"], "zizmor": [".github/workflows/ci.yml"]}


def _run_fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, tool_id: str, binary: str) -> Any:
    plan = AnalyzerPlan(manifest_id=tool_id, mode="repo-native", argv=(binary,), cwd=tmp_path)
    _stub_to_real_run_plan(monkeypatch, plan)
    return run_adapter(
        tool_id=tool_id, repo_root=tmp_path, changed_files=_CHANGED[tool_id], tier="trusted"
    )


@pytest.mark.parametrize(
    ("tool_id", "exit_code", "message"),
    [
        ("mypy", 2, "There are no .py[i] files in directory '.'"),
        ("zizmor", 3, "fatal: no audit was performed\nerror: no inputs collected"),
    ],
    ids=["mypy-no-python-files", "zizmor-no-inputs"],
)
def test_declared_nothing_to_scan_exit_is_a_pass_with_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool_id: str, exit_code: int, message: str
) -> None:
    binary = _fake_binary(tmp_path, exit_code=exit_code, stderr=message)

    result = _run_fake(tmp_path, monkeypatch, tool_id=tool_id, binary=binary)

    assert result.tool_error is False
    assert result.skipped is False, result.skip_reason
    assert result.findings == []
    assert (result.pass_reason or "").startswith("nothing to scan")


@pytest.mark.parametrize(
    ("tool_id", "exit_code", "message"),
    [
        ("mypy", 2, "mypy: error: INTERNAL ERROR"),
        ("mypy", 1, "There are no .py[i] files in directory '.'"),
        ("zizmor", 1, "error: no inputs collected"),
    ],
    ids=["mypy-same-code-other-output", "mypy-marker-other-code", "zizmor-marker-other-code"],
)
def test_other_nonzero_exits_stay_tool_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool_id: str, exit_code: int, message: str
) -> None:
    binary = _fake_binary(tmp_path, exit_code=exit_code, stderr=message)

    result = _run_fake(tmp_path, monkeypatch, tool_id=tool_id, binary=binary)

    assert result.tool_error is True
    reason = result.skip_reason or ""
    assert reason.startswith(f"tool-error {tool_id}: analyzer exited {exit_code}")


def test_pipeline_reports_nothing_to_scan_as_passed_with_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.analyzers import pipeline

    binary = _fake_binary(tmp_path, exit_code=2, stderr="There are no .py[i] files in directory")
    plan = AnalyzerPlan(manifest_id="mypy", mode="repo-native", argv=(binary,), cwd=tmp_path)
    _stub_to_real_run_plan(monkeypatch, plan)
    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_: [get_manifest("mypy")])

    state = pipeline.run_analyzer_pipeline(
        repo_root=tmp_path, changed_files=["src/app.py"], tier="trusted", shell="restricted"
    )

    row = next(row for row in state.analyzers if row.id == "mypy")
    assert row.status == "passed"
    assert (row.reason or "").startswith("nothing to scan")


@pytest.mark.parametrize(
    ("exit_code", "clean"),
    [(128, True), (127, False)],
    ids=["no-package-sources", "general-error"],
)
def test_osv_scanner_no_package_sources_exit_is_a_clean_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int, clean: bool
) -> None:
    from mergecraft.analyzers import supply_chain

    binary = _fake_binary(tmp_path, exit_code=exit_code, stderr="No package sources found")
    plan = AnalyzerPlan(manifest_id="osv-scanner", mode="managed", argv=(binary,), cwd=tmp_path)
    monkeypatch.setattr("mergecraft.analyzers.resolve.resolve_analyzer", lambda **_kwargs: plan)
    monkeypatch.setattr(supply_chain, "_provision_plan", lambda p, **_kwargs: (p, None))
    monkeypatch.setattr(supply_chain, "finalize_plan", lambda p, **_kwargs: p)
    monkeypatch.setattr(
        supply_chain,
        "plan_sandbox",
        lambda **_kwargs: SimpleNamespace(can_run=True, skip_reason=None, context=None),
    )
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    def _scan() -> tuple[list[Any], str | None]:
        return supply_chain._run_osv_scan(
            manifest=get_manifest("osv-scanner"),
            repo_root=tmp_path,
            lockfiles=["uv.lock"],
            tier="trusted",
        )

    if clean:
        assert _scan() == ([], None)
    else:
        # Not declared benign: the text is not an OSV report, so it never reads as clean.
        with pytest.raises(ValueError, match="JSON"):
            _scan()
