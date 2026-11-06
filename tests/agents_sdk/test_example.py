"""The executable example must leave its tracked demo fixture unchanged."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("agents")

from mergecraft.agents_sdk.types import ReviewFinding, ReviewFindingsReport


@pytest.mark.asyncio
async def test_example_uses_disposable_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    import mergecraft.agents_sdk as sdk
    from agents import Runner

    spec = importlib.util.spec_from_file_location(
        "review_loop_example", "examples/agents-sdk/review_loop.py"
    )
    assert spec is not None
    assert spec.loader is not None
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    fixture = example.WORKSPACE / "src" / "demo.py"
    original = fixture.read_bytes()
    workspaces: list[Path] = []

    def fake_agent(*, repo_root: Path, **kwargs: object) -> Path:
        assert repo_root != example.WORKSPACE
        workspaces.append(repo_root)
        return repo_root

    async def fake_run(workspace: Path, **kwargs: object) -> SimpleNamespace:
        body = (workspace / "src" / "demo.py").read_text(encoding="utf-8")
        findings = (
            []
            if "if b == 0" in body
            else [ReviewFinding(severity="Major", file="src/demo.py", message="Division by zero")]
        )
        return SimpleNamespace(final_output=ReviewFindingsReport(findings=findings))

    monkeypatch.setattr(example, "_has_model_credentials", lambda: True)
    monkeypatch.setattr(sdk, "resolve_model_config", lambda **kwargs: None)
    monkeypatch.setattr(sdk, "review_agent", fake_agent)
    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setenv("MERGECRAFT_AGENTS_SDK_MAX_ROUNDS", "2")
    assert await example.main() == 0
    assert await example.main() == 0
    assert fixture.read_bytes() == original
    assert len(set(workspaces)) == 2
    assert all(not workspace.exists() for workspace in workspaces)
