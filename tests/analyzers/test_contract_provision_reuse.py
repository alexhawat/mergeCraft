"""Contract tools provision once while retaining the normal sandbox execution path."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers import adapters, execution
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.analyzers.run import AnalyzerOutcome
from mergecraft.analyzers.sandbox import SandboxPlan


@pytest.mark.parametrize(
    ("tool", "paths", "expected_runs"),
    [
        ("oasdiff", ["openapi/first.yaml", "openapi/second.yaml"], 2),
        ("buf", ["proto/first.proto", "proto/second.proto"], 4),
    ],
    ids=["oasdiff-two-files", "buf-breaking-and-lint-two-files"],
)
def test_contract_files_reuse_one_provisioned_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    paths: list[str],
    expected_runs: int,
) -> None:
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        path.with_name(f"{path.stem}.base{path.suffix}").write_text("", encoding="utf-8")
    provisions = []
    runs = []
    sandbox_calls = []

    def provision(plan: AnalyzerPlan, **_kwargs: Any) -> AnalyzerPlan:
        provisions.append(plan.manifest_id)
        return replace(plan, argv=(f"/managed/{tool}",))

    def sandbox(**kwargs: Any) -> SandboxPlan:
        sandbox_calls.append(kwargs["tier"])
        return SandboxPlan(can_run=True)

    def run(plan: AnalyzerPlan, **_kwargs: Any) -> AnalyzerOutcome:
        runs.append(plan.argv)
        return AnalyzerOutcome(name=tool, command=tool, status="passed", output="", exit_code=0)

    monkeypatch.setattr(execution, "provision_managed_argv", provision)
    monkeypatch.setattr(execution, "plan_sandbox", sandbox)
    monkeypatch.setattr(execution, "run_plan", run)
    result = adapters.run_adapter(
        tool_id=tool,
        repo_root=tmp_path,
        changed_files=paths,
        tier="trusted",
        base_ref="fixture-base",
        allow_repo_binaries=False,
    )
    assert not result.skipped
    assert len(runs) == expected_runs
    assert sandbox_calls == ["trusted"] * expected_runs
    assert all(argv[0] == f"/managed/{tool}" for argv in runs)
    assert provisions == [tool]
