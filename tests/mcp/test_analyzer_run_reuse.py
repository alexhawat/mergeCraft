"""``run_analyzers`` reuses a recorded pre-pass instead of re-running the pipeline.

An offline ``mergecraft review`` runs the catalog pipeline once as a pre-pass and
once more when the reviewing agent calls ``run_analyzers``. These tests pin the
reuse seam: identical inputs must not execute the pipeline twice, and *any*
keyed input differing — or no pre-pass at all, which is the GitHub Action path —
must run it exactly as before.
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
from mergecraft.mcp.tool_state import (
    AnalyzerRunState,
    AnalyzerStatusRow,
    analyzer_run_key,
    init_tool_state,
)
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

DIFF_TEXT = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-x = 1
+x = 2
"""

CHANGED = ["app.py"]
BASE_REF = "origin/main"
# ``AnalyzerSettings.inline_budget`` default — no ``.mergecraft/config.yaml``
# exists under the temporary repo root these tests use.
INLINE_BUDGET = 8


def _ctx(
    tmp_path: Path,
    *,
    shell: str = "restricted",
    tier: str = "trusted",
    mode: str = "auto",
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
        analyzers_settings_enabled=True,
        analyzers_mode=mode,  # type: ignore[arg-type]
        trust_tier=tier,  # type: ignore[arg-type]
    )


def _prepass_state(
    tmp_path: Path,
    *,
    changed_files: list[str] | None = None,
    tier: str = "trusted",
    shell: str = "restricted",
    mode: str = "auto",
    diff_text: str = DIFF_TEXT,
    base_ref: str | None = BASE_REF,
) -> AnalyzerRunState:
    """A recorded pre-pass result, keyed the way ``run_offline_analyze`` keys it."""
    state = AnalyzerRunState(
        ran=True,
        analyzers=[AnalyzerStatusRow(id="actionlint", status="failed", finding_count=1)],
        findings=[{"fingerprint": "fp-1", "severity": "Major"}],
        inline=[{"finding": {"fingerprint": "fp-1"}, "path": "app.py"}],
        mechanical_section="### 🔧 Mechanical findings",
        pre_merge_summary="Analyzers | fail",
        lockfile_digest="sha256:abc",
    )
    state.key = analyzer_run_key(
        repo_root=tmp_path,
        changed_files=CHANGED if changed_files is None else changed_files,
        tier=tier,
        shell=shell,
        mode=mode,
        inline_budget=INLINE_BUDGET,
        offline=True,
        base_ref=base_ref,
        diff_text=diff_text,
    )
    return state


@pytest.fixture
def diff_path(tmp_path: Path) -> Path:
    path = tmp_path / "review.diff"
    path.write_text(DIFF_TEXT, encoding="utf-8")
    return path


@pytest.fixture
def pipeline_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record every ``run_analyzer_pipeline`` invocation and return a fresh run."""
    calls: list[dict[str, Any]] = []

    def _fake(**kwargs: Any) -> AnalyzerRunState:
        calls.append(kwargs)
        return AnalyzerRunState(
            ran=True,
            analyzers=[AnalyzerStatusRow(id="actionlint", status="failed", finding_count=1)],
            findings=[{"fingerprint": "fp-1", "severity": "Major"}],
            inline=[{"finding": {"fingerprint": "fp-1"}, "path": "app.py"}],
            mechanical_section="### 🔧 Mechanical findings",
            pre_merge_summary="Analyzers | fail",
            lockfile_digest="sha256:abc",
        )

    monkeypatch.setattr("mergecraft.analyzers.pipeline.run_analyzer_pipeline", _fake)
    return calls


async def _run(ctx: ToolContext, **params: Any) -> dict[str, Any]:
    from mergecraft.mcp.analyzers import run_analyzers_tool

    result = await run_analyzers_tool(ctx).execute(params)
    return json.loads(result.content[0]["text"])


@pytest.mark.asyncio
async def test_matching_prepass_is_reused_without_rerunning(
    tmp_path: Path, diff_path: Path, pipeline_calls: list[dict[str, Any]]
) -> None:
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = _prepass_state(tmp_path)

    payload = await _run(ctx, changed_files=CHANGED, diff_path=str(diff_path))

    assert pipeline_calls == []
    assert payload["ran"] is True
    assert payload["findingCount"] == 1
    assert payload["preMergeSummary"] == "Analyzers | fail"
    assert payload["lockfileDigest"] == "sha256:abc"


@pytest.mark.asyncio
async def test_changed_file_order_does_not_defeat_reuse(
    tmp_path: Path, diff_path: Path, pipeline_calls: list[dict[str, Any]]
) -> None:
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = _prepass_state(tmp_path, changed_files=["b.py", "a.py"])

    await _run(ctx, changed_files=["a.py", "b.py", "a.py"], diff_path=str(diff_path))

    assert pipeline_calls == []


@pytest.mark.asyncio
async def test_no_prepass_runs_the_pipeline(
    tmp_path: Path, diff_path: Path, pipeline_calls: list[dict[str, Any]]
) -> None:
    """The GitHub Action path records no pre-pass, so nothing is reused."""
    ctx = _ctx(tmp_path)
    assert ctx.tool_state.analyzer_run is None

    payload = await _run(ctx, changed_files=CHANGED, diff_path=str(diff_path))

    assert len(pipeline_calls) == 1
    assert pipeline_calls[0]["changed_files"] == CHANGED
    assert pipeline_calls[0]["inline_budget"] == INLINE_BUDGET
    assert payload["ran"] is True


@pytest.mark.asyncio
async def test_unkeyed_prior_run_is_never_reused(
    tmp_path: Path, diff_path: Path, pipeline_calls: list[dict[str, Any]]
) -> None:
    """A run stored by the tool itself (or by ``confirm``) carries no key."""
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = AnalyzerRunState(ran=True)

    await _run(ctx, changed_files=CHANGED, diff_path=str(diff_path))

    assert len(pipeline_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prepass_kwargs", "ctx_kwargs"),
    [
        pytest.param({"changed_files": ["other.py"]}, {}, id="changed-files"),
        pytest.param({"tier": "untrusted"}, {}, id="tier"),
        pytest.param({"shell": "disabled"}, {}, id="shell"),
        pytest.param({"mode": "full"}, {}, id="mode"),
        pytest.param({"diff_text": "diff --git a/other b/other\n"}, {}, id="diff-digest"),
    ],
)
async def test_any_differing_keyed_input_reruns(
    tmp_path: Path,
    diff_path: Path,
    pipeline_calls: list[dict[str, Any]],
    prepass_kwargs: dict[str, Any],
    ctx_kwargs: dict[str, Any],
) -> None:
    ctx = _ctx(tmp_path, **ctx_kwargs)
    ctx.tool_state.analyzer_run = _prepass_state(tmp_path, **prepass_kwargs)

    await _run(ctx, changed_files=CHANGED, diff_path=str(diff_path))

    assert len(pipeline_calls) == 1


@pytest.mark.asyncio
async def test_different_repo_root_reruns(
    tmp_path: Path, diff_path: Path, pipeline_calls: list[dict[str, Any]]
) -> None:
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = _prepass_state(tmp_path)
    other = tmp_path / "other"
    other.mkdir()

    await _run(ctx, changed_files=CHANGED, diff_path=str(diff_path), repo_root=str(other))

    assert len(pipeline_calls) == 1


@pytest.mark.asyncio
async def test_explicit_matching_base_ref_reuses(
    tmp_path: Path, diff_path: Path, pipeline_calls: list[dict[str, Any]]
) -> None:
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = _prepass_state(tmp_path)

    await _run(ctx, changed_files=CHANGED, diff_path=str(diff_path), base_ref=BASE_REF)

    assert pipeline_calls == []


@pytest.mark.asyncio
async def test_different_explicit_base_ref_reruns(
    tmp_path: Path, diff_path: Path, pipeline_calls: list[dict[str, Any]]
) -> None:
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = _prepass_state(tmp_path)

    await _run(ctx, changed_files=CHANGED, diff_path=str(diff_path), base_ref="origin/release")

    assert len(pipeline_calls) == 1
    assert pipeline_calls[0]["base_ref"] == "origin/release"


@pytest.mark.asyncio
async def test_prepass_without_base_ref_is_not_matched_by_an_explicit_one(
    tmp_path: Path, diff_path: Path, pipeline_calls: list[dict[str, Any]]
) -> None:
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = _prepass_state(tmp_path, base_ref=None)

    await _run(ctx, changed_files=CHANGED, diff_path=str(diff_path), base_ref=BASE_REF)

    assert len(pipeline_calls) == 1


@pytest.mark.asyncio
async def test_reused_payload_matches_the_freshly_computed_one(
    tmp_path: Path, diff_path: Path, pipeline_calls: list[dict[str, Any]]
) -> None:
    fresh = await _run(_ctx(tmp_path), changed_files=CHANGED, diff_path=str(diff_path))
    assert len(pipeline_calls) == 1

    reusing = _ctx(tmp_path)
    reusing.tool_state.analyzer_run = _prepass_state(tmp_path)
    reused = await _run(reusing, changed_files=CHANGED, diff_path=str(diff_path))

    assert len(pipeline_calls) == 1
    assert reused == fresh


@pytest.mark.asyncio
async def test_reuse_preserves_session_verified_ids(
    tmp_path: Path, diff_path: Path, pipeline_calls: list[dict[str, Any]]
) -> None:
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = _prepass_state(tmp_path)
    ctx.tool_state.verified_ids = {"fp-1"}

    await _run(ctx, changed_files=CHANGED, diff_path=str(diff_path))

    assert pipeline_calls == []
    stored = ctx.tool_state.analyzer_run
    assert stored is not None
    assert "fp-1" in stored.verified_ids
