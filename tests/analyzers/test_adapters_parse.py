"""Tests for analyzer skip-reason classification at the parse boundary.

Distinguishes "analyzer did not run (no output)" from "output present but
unparseable" so the skip reason is honest, without touching sandbox/execution
logic in execution.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import pytest

from mergecraft.analyzers.adapters import run_adapter
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.analyzers.run import AnalyzerOutcome

_TOOL_ID = "ruff"


def _stub_chain(monkeypatch: pytest.MonkeyPatch, *, output_text: str, tmp_path: Path) -> None:
    """Wire run_adapter to reach the parse boundary with a canned output file.

    Everything between manifest resolution and run_plan is stubbed; only the
    parse classification (adapters.py lines ~291-302) is exercised for real.
    """
    from mergecraft.analyzers import adapters as adapters_mod

    def _get_manifest(tool_id: str):
        registry = __import__("mergecraft.analyzers.registry", fromlist=["load_catalog"])
        for m in registry.load_catalog():
            if m.id == tool_id:
                return m
        raise AssertionError(f"no manifest for {tool_id}")

    def _filter_changed(_manifest, changed_files):
        return list(changed_files)

    plan = AnalyzerPlan(manifest_id=_TOOL_ID, mode="repo-native", argv=("trufflehog",))

    def _resolve_analyzer(**_kwargs):
        return plan

    def _provision_managed_argv(_plan, **_kwargs):
        return plan

    def _plan_sandbox(**_kwargs):
        return type(
            "D",
            (),
            {"can_run": True, "skip_reason": None, "context": None},
        )()

    def _finalize_plan(_plan, **_kwargs):
        return plan

    out_path = tmp_path / f"{_TOOL_ID}.out"
    out_path.write_text(output_text, encoding="utf-8")

    def _run_plan(_plan, **_kwargs):
        return AnalyzerOutcome(
            name=_TOOL_ID,
            command="trufflehog",
            status="passed",
            output=output_text,
            exit_code=0,
            output_path=str(out_path),
        )

    monkeypatch.setattr(adapters_mod, "get_manifest", _get_manifest)
    monkeypatch.setattr(
        "mergecraft.analyzers.registry.filter_changed_files_for_manifest", _filter_changed
    )
    monkeypatch.setattr(adapters_mod, "resolve_analyzer", _resolve_analyzer)
    monkeypatch.setattr(adapters_mod, "provision_managed_argv", _provision_managed_argv)
    monkeypatch.setattr(adapters_mod, "plan_sandbox", _plan_sandbox)
    monkeypatch.setattr(adapters_mod, "finalize_plan", _finalize_plan)
    monkeypatch.setattr(adapters_mod, "run_plan", _run_plan)


def test_empty_output_yields_did_not_run_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_chain(monkeypatch, output_text="", tmp_path=tmp_path)

    result = run_adapter(
        tool_id=_TOOL_ID,
        repo_root=tmp_path,
        changed_files=["src/app.py"],
        tier="trusted",
    )
    assert result.skipped is True
    reason = result.skip_reason or ""
    assert "did not run" in reason, reason
    assert "sandbox unavailable" in reason, reason
    assert "failed to parse" not in reason, reason


def test_none_output_yields_did_not_run_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_chain(monkeypatch, output_text="   \n  ", tmp_path=tmp_path)

    result = run_adapter(
        tool_id=_TOOL_ID,
        repo_root=tmp_path,
        changed_files=["src/app.py"],
        tier="trusted",
    )
    assert result.skipped is True
    assert "did not run" in (result.skip_reason or ""), result.skip_reason


def test_nonempty_invalid_json_yields_parse_failure_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_chain(monkeypatch, output_text="not valid json {", tmp_path=tmp_path)

    result = run_adapter(
        tool_id=_TOOL_ID,
        repo_root=tmp_path,
        changed_files=["src/app.py"],
        tier="trusted",
    )
    assert result.skipped is True
    reason = result.skip_reason or ""
    assert "failed to parse analyzer output" in reason, reason
    assert "did not run" not in reason, reason


def test_jscpd_parses_scratch_report_when_stdout_has_no_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """jscpd writes ``jscpd-report.json``; adapters rewrite output_path onto it."""
    from mergecraft.analyzers import adapters as adapters_mod

    tool_id = "jscpd"
    report_json = Path(__file__).resolve().parent / "fixtures" / "native" / "jscpd-minimal.json"
    captured: list[AnalyzerPlan] = []

    plan = AnalyzerPlan(
        manifest_id=tool_id,
        mode="repo-native",
        argv=("jscpd", "--reporters", "json", "--silent", "."),
    )

    def _filter_changed(_manifest, changed_files):
        return list(changed_files)

    def _resolve_analyzer(**_kwargs):
        return plan

    def _provision_managed_argv(_plan, **_kwargs):
        return plan

    def _plan_sandbox(**_kwargs):
        return type(
            "D",
            (),
            {"can_run": True, "skip_reason": None, "context": None},
        )()

    def _finalize_plan(_plan, **_kwargs):
        return _plan

    def _run_plan(received: AnalyzerPlan, **_kwargs):
        captured.append(received)
        report = tmp_path / ".mergecraft" / "analyzer-scratch" / tool_id / "jscpd-report.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(report_json.read_text(encoding="utf-8"), encoding="utf-8")
        return AnalyzerOutcome(
            name=tool_id,
            command="jscpd",
            status="passed",
            output="",
            exit_code=0,
            output_path=None,
        )

    monkeypatch.setattr(
        "mergecraft.analyzers.registry.filter_changed_files_for_manifest", _filter_changed
    )
    monkeypatch.setattr(adapters_mod, "resolve_analyzer", _resolve_analyzer)
    monkeypatch.setattr(adapters_mod, "provision_managed_argv", _provision_managed_argv)
    monkeypatch.setattr(adapters_mod, "plan_sandbox", _plan_sandbox)
    monkeypatch.setattr(adapters_mod, "finalize_plan", _finalize_plan)
    monkeypatch.setattr(adapters_mod, "run_plan", _run_plan)

    result = run_adapter(
        tool_id=tool_id,
        repo_root=tmp_path,
        changed_files=["src/clone-a.js"],
        tier="trusted",
    )
    assert captured, "run_plan must receive the jscpd argv patch"
    argv = captured[0].argv
    assert "--output" in argv
    assert str(tmp_path / ".mergecraft" / "analyzer-scratch" / tool_id) in argv
    assert result.skipped is False, result.skip_reason
    assert result.findings, "jscpd-report.json must parse through the generic output_path path"
    assert result.findings[0].rule_id == "clone"


def test_successful_empty_stdout_is_passed_not_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real exit-0 run with no stdout (tsc --noEmit) is a pass, not a skip."""
    from mergecraft.analyzers import adapters as adapters_mod

    tool_id = "tsc"
    plan = AnalyzerPlan(manifest_id=tool_id, mode="repo-native", argv=("tsc", "--noEmit"))

    def _filter_changed(_manifest, changed_files):
        return list(changed_files)

    def _resolve_analyzer(**_kwargs):
        return plan

    def _provision_managed_argv(_plan, **_kwargs):
        return plan

    def _plan_sandbox(**_kwargs):
        return type(
            "D",
            (),
            {"can_run": True, "skip_reason": None, "context": None},
        )()

    def _finalize_plan(_plan, **_kwargs):
        return _plan

    def _run_plan(_plan, **_kwargs):
        return AnalyzerOutcome(
            name=tool_id,
            command="tsc --noEmit --pretty false",
            status="passed",
            output="",
            exit_code=0,
            output_path=None,
        )

    monkeypatch.setattr(
        "mergecraft.analyzers.registry.filter_changed_files_for_manifest", _filter_changed
    )
    monkeypatch.setattr(adapters_mod, "resolve_analyzer", _resolve_analyzer)
    monkeypatch.setattr(adapters_mod, "provision_managed_argv", _provision_managed_argv)
    monkeypatch.setattr(adapters_mod, "plan_sandbox", _plan_sandbox)
    monkeypatch.setattr(adapters_mod, "finalize_plan", _finalize_plan)
    monkeypatch.setattr(adapters_mod, "run_plan", _run_plan)

    result = run_adapter(
        tool_id=tool_id,
        repo_root=tmp_path,
        changed_files=["src/index.ts"],
        tier="trusted",
    )
    assert result.skipped is False, result.skip_reason
    assert result.findings == []


def test_tsc_help_stdout_is_parse_failure_not_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tsc without tsconfig prints help and exits 1; that must not be a clean pass."""
    from mergecraft.analyzers import adapters as adapters_mod

    tool_id = "tsc"
    help_text = (
        "tsc: The TypeScript Compiler - Version 5.8.3\n\n"
        "COMMON COMMANDS\n\n"
        "  tsc\n"
        "  Compiles the current project (tsconfig.json in the working directory.)\n"
    )
    out_path = tmp_path / "tsc.out"
    out_path.write_text(help_text, encoding="utf-8")
    plan = AnalyzerPlan(manifest_id=tool_id, mode="repo-native", argv=("tsc", "--noEmit"))

    def _filter_changed(_manifest, changed_files):
        return list(changed_files)

    def _resolve_analyzer(**_kwargs):
        return plan

    def _provision_managed_argv(_plan, **_kwargs):
        return plan

    def _plan_sandbox(**_kwargs):
        return type(
            "D",
            (),
            {"can_run": True, "skip_reason": None, "context": None},
        )()

    def _finalize_plan(_plan, **_kwargs):
        return _plan

    def _run_plan(_plan, **_kwargs):
        return AnalyzerOutcome(
            name=tool_id,
            command="tsc --noEmit --pretty false",
            status="failed",
            output=help_text,
            exit_code=1,
            output_path=str(out_path),
        )

    monkeypatch.setattr(
        "mergecraft.analyzers.registry.filter_changed_files_for_manifest", _filter_changed
    )
    monkeypatch.setattr(adapters_mod, "resolve_analyzer", _resolve_analyzer)
    monkeypatch.setattr(adapters_mod, "provision_managed_argv", _provision_managed_argv)
    monkeypatch.setattr(adapters_mod, "plan_sandbox", _plan_sandbox)
    monkeypatch.setattr(adapters_mod, "finalize_plan", _finalize_plan)
    monkeypatch.setattr(adapters_mod, "run_plan", _run_plan)

    result = run_adapter(
        tool_id=tool_id,
        repo_root=tmp_path,
        changed_files=["src/index.ts"],
        tier="trusted",
    )
    assert result.skipped is True
    assert result.findings == []
    reason = result.skip_reason or ""
    assert "failed to parse" in reason, reason


def test_unreadable_output_logs_exception_without_leaking_into_skip_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skip reason stays generic; the OSError is logged."""
    _stub_chain(monkeypatch, output_text="{}", tmp_path=tmp_path)
    canary = "disk exploded"
    original = Path.read_text

    def _read(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == f"{_TOOL_ID}.out":
            raise OSError(canary)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read)
    records: list[str] = []
    handler = logger.add(lambda message: records.append(str(message)), level="INFO")
    try:
        result = run_adapter(
            tool_id=_TOOL_ID,
            repo_root=tmp_path,
            changed_files=["src/app.py"],
            tier="trusted",
        )
    finally:
        logger.remove(handler)

    assert result.skipped is True
    reason = result.skip_reason or ""
    assert "could not read analyzer output" in reason
    assert canary not in reason
    assert any(canary in rec for rec in records)


def test_parse_failure_logs_exception_without_leaking_into_skip_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skip reason stays generic; the parse exception is logged."""
    _stub_chain(monkeypatch, output_text="not valid json {", tmp_path=tmp_path)
    records: list[str] = []
    handler = logger.add(lambda message: records.append(str(message)), level="INFO")
    try:
        result = run_adapter(
            tool_id=_TOOL_ID,
            repo_root=tmp_path,
            changed_files=["src/app.py"],
            tier="trusted",
        )
    finally:
        logger.remove(handler)

    assert result.skipped is True
    reason = result.skip_reason or ""
    assert "failed to parse analyzer output" in reason
    assert "{" not in reason
    assert records, "parse skip must log the exception"
