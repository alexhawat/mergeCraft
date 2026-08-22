"""The offline pre-pass and the ``run_analyzers`` tool must run the pipeline once.

``_OfflineDiffReviewRun.analyze`` runs the catalog pipeline before the agent
starts, and the reviewing agent then calls ``run_analyzers`` over the same diff.
This exercises both halves against one stub pipeline and asserts it executes a
single time end-to-end.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import AnalyzerRunState, AnalyzerStatusRow, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review.offline_stages import run_offline_analyze
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.offline_diff import DiffMaterialization

if TYPE_CHECKING:
    from pathlib import Path

PATCH = "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"


def _materialization(out_dir: Path, *, base_ref: str | None = "origin/main") -> DiffMaterialization:
    path = out_dir / "change.diff"
    path.write_text(PATCH, encoding="utf-8")
    return DiffMaterialization(
        path=path,
        base_ref=base_ref,
        line_count=PATCH.count("\n"),
        empty=False,
    )


def _tool_context(cwd: Path, *, shell: str) -> ToolContext:
    """The context ``run_offline_agent_review`` builds for the offline agent."""
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="local", name=cwd.name),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown", title="offline diff-review"),
            shell=shell,  # type: ignore[arg-type]
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="local", name=cwd.name, dir=str(cwd)),
        mcp_server_url="",
        tmpdir=str(cwd),
        analyzers_settings_enabled=True,
        analyzers_mode="auto",
        trust_tier="trusted",
    )


@pytest.fixture
def pipeline_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _fake(**kwargs: Any) -> AnalyzerRunState:
        calls.append(kwargs)
        return AnalyzerRunState(
            ran=True,
            analyzers=[AnalyzerStatusRow(id="ruff", status="failed", finding_count=1)],
            findings=[{"fingerprint": "fp-1"}],
            pre_merge_summary="Analyzers | fail",
        )

    monkeypatch.setattr("mergecraft.review.offline_stages.run_analyzer_pipeline", _fake)
    monkeypatch.setattr("mergecraft.analyzers.pipeline.run_analyzer_pipeline", _fake)
    return calls


async def _call_tool(ctx: ToolContext, **params: Any) -> dict[str, Any]:
    from mergecraft.mcp.analyzers import run_analyzers_tool

    result = await run_analyzers_tool(ctx).execute(params)
    return json.loads(result.content[0]["text"])


@pytest.mark.asyncio
@pytest.mark.parametrize("shell", ["disabled", "restricted"])
async def test_prepass_then_tool_runs_pipeline_once(
    tmp_path: Path, pipeline_calls: list[dict[str, Any]], shell: str
) -> None:
    materialization = _materialization(tmp_path)
    prepass = await run_offline_analyze(
        cwd=tmp_path,
        materialization=materialization,
        trust_tier="trusted",
        shell=shell,  # type: ignore[arg-type]
    )
    assert prepass is not None
    assert prepass.key is not None
    assert len(pipeline_calls) == 1

    ctx = _tool_context(tmp_path, shell=shell)
    # ``run_offline_agent_review`` hands the pre-pass over via ``_store_run_state``.
    from mergecraft.mcp.analyzers import _store_run_state

    _store_run_state(ctx, prepass)

    payload = await _call_tool(
        ctx,
        changed_files=["demo.py"],
        diff_path=str(materialization.path),
    )

    assert len(pipeline_calls) == 1, "the tool must reuse the pre-pass, not re-run the pipeline"
    assert payload["ran"] is True
    assert payload["findingCount"] == 1
    assert payload["preMergeSummary"] == "Analyzers | fail"


@pytest.mark.asyncio
async def test_failed_prepass_is_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pipeline_calls: list[dict[str, Any]]
) -> None:
    """A pipeline that raised records no key, so the agent still gets a real run."""

    def _boom(**_kwargs: Any) -> AnalyzerRunState:
        raise RuntimeError("boom")

    monkeypatch.setattr("mergecraft.review.offline_stages.run_analyzer_pipeline", _boom)
    materialization = _materialization(tmp_path)
    prepass = await run_offline_analyze(
        cwd=tmp_path,
        materialization=materialization,
        trust_tier="trusted",
    )
    assert prepass is not None
    assert prepass.ran is False
    assert prepass.key is None

    ctx = _tool_context(tmp_path, shell="restricted")
    from mergecraft.mcp.analyzers import _store_run_state

    _store_run_state(ctx, prepass)
    await _call_tool(ctx, changed_files=["demo.py"], diff_path=str(materialization.path))

    assert len(pipeline_calls) == 1
